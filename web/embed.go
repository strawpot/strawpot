package web

import "embed"

// Files holds the compiled React SPA from web/dist/.
// Build the frontend first: cd web && npm install && npm run build
//
//go:embed dist
var Files embed.FS
