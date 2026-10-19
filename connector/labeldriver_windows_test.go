//go:build windows

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestPDFOutputNeverOverwritesAndCleansOnlyOwnFiles(t *testing.T) {
	folder := t.TempDir()
	manifest := LabelManifest{Pages: []LabelPage{{File: "1.pdf", Filename: "RK001_1_SN1.pdf"}, {File: "2.pdf", Filename: "RK001_1_SN2.pdf"}}}
	files := map[string][]byte{"1.pdf": []byte("%PDF-one"), "2.pdf": []byte("%PDF-two")}
	existing := filepath.Join(folder, "RK001_1_SN2.pdf")
	os.WriteFile(existing, []byte("original"), 0600)
	if _, err := saveLabelPDFs(manifest, files, folder); err == nil {
		t.Fatal("overwrote existing output")
	}
	if _, err := os.Stat(filepath.Join(folder, "RK001_1_SN1.pdf")); !os.IsNotExist(err) {
		t.Fatal("left partial output")
	}
	data, _ := os.ReadFile(existing)
	if string(data) != "original" {
		t.Fatal("existing file changed")
	}
}
