//go:build windows

package main

import (
	"path/filepath"
	"syscall"
	"unsafe"
)

var (
	kernel32          = syscall.NewLazyDLL("kernel32.dll")
	procLoadLibraryEx = kernel32.NewProc("LoadLibraryExW")
	procFreeLibrary   = kernel32.NewProc("FreeLibrary")
)

// dllFindable: can Windows load `name` the way the DLL importing it would (its
// own folder, then the system)? Loaded as a data file, so no code runs.
func dllFindable(name, dir string) bool {
	const dataFile = 0x00000002 | 0x00000020 // LOAD_LIBRARY_AS_DATAFILE | AS_IMAGE_RESOURCE
	for _, p := range []string{filepath.Join(dir, name), name} {
		s, _ := syscall.UTF16PtrFromString(p)
		h, _, _ := procLoadLibraryEx.Call(uintptr(unsafe.Pointer(s)), 0, dataFile)
		if h != 0 {
			procFreeLibrary.Call(h)
			return true
		}
	}
	// api-ms-win-* are API sets, resolved by the loader rather than files.
	return len(name) > 7 && (name[:7] == "api-ms-" || name[:7] == "API-MS-")
}
