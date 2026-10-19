package main

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func testLabelBundle(t *testing.T, filename string) []byte {
	t.Helper()
	manifest := LabelManifest{Version: 1, RunID: strings.Repeat("a", 32), Receipt: strings.Repeat("b", 64), Printer: "Microsoft Print to PDF", WidthMM: 100, HeightMM: 50, Pages: []LabelPage{{File: "1.pdf", Filename: filename}}}
	buffer := &bytes.Buffer{}
	archive := zip.NewWriter(buffer)
	data, _ := json.Marshal(manifest)
	writer, _ := archive.Create("manifest.json")
	writer.Write(data)
	writer, _ = archive.Create("1.pdf")
	writer.Write([]byte("%PDF-test"))
	archive.Close()
	return buffer.Bytes()
}
func TestLabelBundleRejectsUnsafeFilename(t *testing.T) {
	for _, name := range []string{"../bad.pdf", `C:\bad.pdf`, "CON.pdf"} {
		if _, _, err := decodeLabelBundle(testLabelBundle(t, name)); err == nil {
			t.Fatalf("accepted %s", name)
		}
	}
	if _, _, err := decodeLabelBundle(testLabelBundle(t, "单号_3_SN123.pdf")); err != nil {
		t.Fatal(err)
	}
}
func TestDesktopProxyAndOriginIsolation(t *testing.T) {
	central := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/me" && r.URL.Path != "/login" {
			t.Errorf("unexpected path %s", r.URL.Path)
		}
		if r.Host == "127.0.0.1:9110" {
			t.Error("proxy kept local host")
		}
		w.Write([]byte("central"))
	}))
	defer central.Close()
	api := NewLocalAPI(&Config{ServerURL: central.URL, Listen: "127.0.0.1:9110"}, &LocalPrinters{})
	for _, path := range []string{"/api/me", "/app/login"} {
		req := httptest.NewRequest("GET", path, nil)
		req.Header.Set("Origin", "http://127.0.0.1:9110")
		result := httptest.NewRecorder()
		api.Handler().ServeHTTP(result, req)
		if result.Code != 200 || result.Body.String() != "central" {
			t.Fatal(result)
		}
	}
	req := httptest.NewRequest("POST", "/print-labels", nil)
	req.Header.Set("Origin", "https://untrusted.example")
	result := httptest.NewRecorder()
	api.Handler().ServeHTTP(result, req)
	if result.Code != 403 {
		t.Fatalf("untrusted origin accepted: %d", result.Code)
	}
}
