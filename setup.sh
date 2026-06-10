#!/bin/bash
# One-time setup: vendor static binaries + register the Higgsfield MCP server.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p bin assets work output

if [ ! -x bin/yt-dlp ]; then
  echo "Fetching yt-dlp…"
  curl -fL -o bin/yt-dlp \
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
  chmod +x bin/yt-dlp
fi

if [ ! -x bin/ffmpeg ]; then
  ARCH=$(uname -m)
  if [ "$ARCH" = "arm64" ]; then F="ffmpeg-darwin-arm64"; else F="ffmpeg-darwin-x64"; fi
  echo "Fetching ffmpeg ($F)…"
  curl -fL -o bin/ffmpeg \
    "https://github.com/eugeneware/ffmpeg-static/releases/latest/download/$F"
  chmod +x bin/ffmpeg
fi

if ! claude mcp list 2>/dev/null | grep -q "higgsfield"; then
  echo "Registering Higgsfield MCP server (user scope)…"
  claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp
fi

echo ""
echo "Setup complete. Two manual steps remain:"
echo "  1. Authorize Higgsfield once: run 'claude', type '/mcp', pick higgsfield, log in."
echo "  2. Save a clear front-facing photo of yourself as assets/me.jpg"
