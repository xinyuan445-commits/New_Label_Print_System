//go:build windows

package main

import (
	"context"
	"embed"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

//go:embed print-label-pages.ps1
var driverScript embed.FS

func saveLabelPDFs(manifest LabelManifest, files map[string][]byte, folder string) (string, error) {
	if manifest.Reprint {
		folder = filepath.Join(folder, "补打", manifest.RunID)
	}
	if err := os.MkdirAll(folder, 0700); err != nil {
		return "", err
	}
	created := []string{}
	for _, page := range manifest.Pages {
		path := filepath.Join(folder, page.Filename)
		f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err == nil {
			created = append(created, path)
			_, err = f.Write(files[page.File])
			closeErr := f.Close()
			if err == nil {
				err = closeErr
			}
		}
		if err != nil {
			for _, own := range created {
				_ = os.Remove(own)
			}
			return "", err
		}
	}
	return folder, nil
}

func dispatchDriverLabels(manifest LabelManifest, files map[string][]byte) (string, error) {
	if manifest.Printer == "Microsoft Print to PDF" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		return saveLabelPDFs(manifest, files, filepath.Join(home, "Downloads", "标签打印"))
	}
	folder, err := os.MkdirTemp("", "blg-labels-")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(folder)
	paths := []string{}
	for _, page := range manifest.Pages {
		path := filepath.Join(folder, page.File)
		if err = os.WriteFile(path, files[page.File], 0600); err != nil {
			return "", err
		}
		paths = append(paths, path)
	}
	list := filepath.Join(folder, "pages.txt")
	if err = os.WriteFile(list, []byte(strings.Join(paths, "\n")), 0600); err != nil {
		return "", err
	}
	script, err := driverScript.ReadFile("print-label-pages.ps1")
	if err != nil {
		return "", err
	}
	scriptPath := filepath.Join(folder, "print.ps1")
	if err = os.WriteFile(scriptPath, append([]byte{0xef, 0xbb, 0xbf}, script...), 0600); err != nil {
		return "", err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()
	command := exec.CommandContext(ctx, "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", scriptPath, "-PrinterName", manifest.Printer, "-PageListPath", list, "-WidthMm", strconv.FormatFloat(manifest.WidthMM, 'f', 4, 64), "-HeightMm", strconv.FormatFloat(manifest.HeightMM, 'f', 4, 64))
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if output, err := command.CombinedOutput(); err != nil {
		return "", fmt.Errorf("driver rejected job: %w: %s", err, output)
	}
	if ctx.Err() != nil {
		return "", errors.New("print_result_unknown")
	}
	return "", nil
}
