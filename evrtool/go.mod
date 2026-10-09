module arenacolours/evrtool

go 1.25.0

require github.com/EchoTools/cosmetic-editor v0.0.0

require github.com/klauspost/compress v1.20.0 // indirect

// cosmetic-editor (github.com/EchoTools/cosmetic-editor, MIT) is vendored in vendor/, so
// this builds from the repo alone; the replace below only records where it was vendored from.
replace github.com/EchoTools/cosmetic-editor => ../../EchoVR-Cosmetics-Editor
