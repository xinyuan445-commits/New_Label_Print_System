//go:build !windows

package main

import "errors"

func dispatchDriverLabels(manifest LabelManifest, files map[string][]byte) (string, error) {
	return "", errors.New("windows_printer_required")
}
