package main

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"
)

const labelBundleLimit = 64 << 20

var runPattern = regexp.MustCompile(`^[0-9a-f]{32}$`)
var receiptPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

type LabelPage struct {
	File     string `json:"file"`
	Filename string `json:"filename"`
}
type LabelManifest struct {
	Version  int         `json:"version"`
	RunID    string      `json:"run_id"`
	Receipt  string      `json:"receipt"`
	Printer  string      `json:"printer"`
	WidthMM  float64     `json:"width_mm"`
	HeightMM float64     `json:"height_mm"`
	Reprint  bool        `json:"reprint"`
	Pages    []LabelPage `json:"pages"`
}
type LabelResult struct {
	RunID        string `json:"run_id"`
	Status       string `json:"status"`
	Receipt      string `json:"receipt"`
	BundleSHA256 string `json:"bundle_sha256"`
	Printer      string `json:"printer"`
	Printed      int    `json:"printed"`
	OutputDir    string `json:"output_dir,omitempty"`
	Error        string `json:"error,omitempty"`
}

func labelJobPath(id string) (string, error) {
	if !runPattern.MatchString(id) {
		return "", errors.New("invalid_run")
	}
	base, err := os.UserCacheDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(base, "blg-connector", "label-jobs")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return "", err
	}
	return filepath.Join(dir, id+".json"), nil
}
func saveLabelResult(path string, result LabelResult) error {
	data, err := json.Marshal(result)
	if err != nil {
		return err
	}
	temporary := path + ".tmp"
	if err = os.WriteFile(temporary, data, 0600); err != nil {
		return err
	}
	return os.Rename(temporary, path)
}
func readLabelResult(path string) (LabelResult, error) {
	var result LabelResult
	data, err := os.ReadFile(path)
	if err == nil {
		err = json.Unmarshal(data, &result)
	}
	return result, err
}
func (a *LocalAPI) handleLabelStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", 405)
		return
	}
	path, err := labelJobPath(strings.TrimPrefix(r.URL.Path, "/label-jobs/"))
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": "invalid_run"})
		return
	}
	result, err := readLabelResult(path)
	if err != nil {
		writeJSON(w, 404, map[string]string{"error": "job_not_found"})
		return
	}
	writeJSON(w, 200, result)
}

func decodeLabelBundle(data []byte) (LabelManifest, map[string][]byte, error) {
	var manifest LabelManifest
	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return manifest, nil, errors.New("invalid_bundle")
	}
	if len(archive.File) < 2 || len(archive.File) > 1001 {
		return manifest, nil, errors.New("invalid_bundle")
	}
	files := map[string][]byte{}
	var size int64
	for _, file := range archive.File {
		if file.Name != filepath.Base(file.Name) || files[file.Name] != nil || file.UncompressedSize64 > labelBundleLimit {
			return manifest, nil, errors.New("invalid_bundle")
		}
		reader, err := file.Open()
		if err != nil {
			return manifest, nil, err
		}
		content, readErr := io.ReadAll(io.LimitReader(reader, labelBundleLimit+1))
		reader.Close()
		size += int64(len(content))
		if readErr != nil || len(content) > labelBundleLimit || size > 128<<20 {
			return manifest, nil, errors.New("print_job_too_large")
		}
		files[file.Name] = content
	}
	if err := json.Unmarshal(files["manifest.json"], &manifest); err != nil {
		return manifest, nil, errors.New("invalid_bundle")
	}
	if manifest.Version != 1 || !runPattern.MatchString(manifest.RunID) || !receiptPattern.MatchString(manifest.Receipt) || len(manifest.Pages) < 1 || len(manifest.Pages) > 1000 || len(files) != len(manifest.Pages)+1 || !(manifest.WidthMM > 0 && manifest.WidthMM <= 1000 && manifest.HeightMM > 0 && manifest.HeightMM <= 1000) {
		return manifest, nil, errors.New("invalid_bundle")
	}
	names := map[string]bool{}
	for i, page := range manifest.Pages {
		ext := ".png"
		signature := []byte("\x89PNG\r\n\x1a\n")
		if manifest.Printer == "Microsoft Print to PDF" {
			ext = ".pdf"
			signature = []byte("%PDF-")
		}
		if page.File != fmt.Sprintf("%d%s", i+1, ext) || !bytes.HasPrefix(files[page.File], signature) || !safeLabelFilename(page.Filename) || names[page.Filename] {
			return manifest, nil, errors.New("invalid_bundle")
		}
		names[page.Filename] = true
	}
	return manifest, files, nil
}
func safeLabelFilename(name string) bool {
	if !strings.HasSuffix(name, ".pdf") || utf8.RuneCountInString(name) > 240 || strings.Trim(name, " .") != name || strings.ContainsAny(name, `<>:"/\|?*`) {
		return false
	}
	for _, r := range name {
		if r < 32 {
			return false
		}
	}
	stem := strings.ToUpper(strings.Split(name, ".")[0])
	if stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" {
		return false
	}
	return !(len(stem) == 4 && (strings.HasPrefix(stem, "COM") || strings.HasPrefix(stem, "LPT")) && stem[3] >= '1' && stem[3] <= '9')
}
func (a *LocalAPI) handleLabelPrint(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", 405)
		return
	}
	if r.Header.Get("Content-Type") != "application/octet-stream" {
		writeJSON(w, 415, map[string]string{"error": "binary_required"})
		return
	}
	data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, labelBundleLimit))
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": "print_job_too_large"})
		return
	}
	manifest, files, err := decodeLabelBundle(data)
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": err.Error()})
		return
	}
	digest := sha256.Sum256(data)
	hash := hex.EncodeToString(digest[:])
	path, err := labelJobPath(manifest.RunID)
	if err != nil {
		writeJSON(w, 500, map[string]string{"error": "job_storage_failed"})
		return
	}
	// Serialize acceptance and dispatch. A persisted processing/error job is never replayed.
	a.labelMu.Lock()
	defer a.labelMu.Unlock()
	previous, err := readLabelResult(path)
	if err == nil {
		if previous.BundleSHA256 != hash {
			writeJSON(w, 409, map[string]string{"error": "job_conflict"})
			return
		}
		if previous.Status == "done" {
			writeJSON(w, 200, previous)
			return
		}
		writeJSON(w, 409, map[string]string{"error": "print_result_unknown"})
		return
	}
	if !os.IsNotExist(err) {
		writeJSON(w, 500, map[string]string{"error": "job_storage_failed"})
		return
	}
	if err := a.local.Refresh(); err != nil {
		writeJSON(w, 503, map[string]string{"error": "printer_not_found"})
		return
	}
	found := false
	for _, p := range a.local.Snapshot() {
		if p == manifest.Printer {
			found = true
			break
		}
	}
	if !found {
		writeJSON(w, 404, map[string]string{"error": "printer_not_found"})
		return
	}
	result := LabelResult{RunID: manifest.RunID, Status: "processing", Receipt: manifest.Receipt, BundleSHA256: hash, Printer: manifest.Printer}
	if err = saveLabelResult(path, result); err != nil {
		writeJSON(w, 500, map[string]string{"error": "job_storage_failed"})
		return
	}
	folder, err := dispatchDriverLabels(manifest, files)
	if err != nil {
		result.Status = "error"
		result.Error = "print_failed"
		_ = saveLabelResult(path, result)
		writeJSON(w, 502, map[string]string{"error": "print_result_unknown"})
		return
	}
	result.Status = "done"
	result.Printed = len(manifest.Pages)
	result.OutputDir = folder
	if err = saveLabelResult(path, result); err != nil {
		writeJSON(w, 500, map[string]string{"error": "print_result_unknown"})
		return
	}
	writeJSON(w, 200, result)
}
