//go:build !windows

package main

// dllFindable is only meaningful on Windows; elsewhere every import counts as found.
func dllFindable(name, dir string) bool { return true }
