#!/bin/bash
# One-time setup: vendor the yt-dlp + ffmpeg static binaries for this OS.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p bin assets work output

OS=$(uname -s)
ARCH=$(uname -m)

case "$OS" in
  Darwin)
    YT="yt-dlp_macos"
    if [ "$ARCH" = "arm64" ]; then FF="ffmpeg-darwin-arm64"; else FF="ffmpeg-darwin-x64"; fi
    ;;
  Linux)
    case "$ARCH" in
      aarch64|arm64) YT="yt-dlp_linux_aarch64"; FF="ffmpeg-linux-arm64" ;;
      x86_64)        YT="yt-dlp_linux";         FF="ffmpeg-linux-x64" ;;
      *) echo "Unsupported Linux arch: $ARCH" >&2; exit 1 ;;
    esac
    ;;
  *) echo "Unsupported OS: $OS (macOS and Linux supported)" >&2; exit 1 ;;
esac

if [ ! -x bin/yt-dlp ]; then
  echo "Fetching yt-dlp ($YT)…"
  curl -fL -o bin/yt-dlp \
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/$YT"
  chmod +x bin/yt-dlp
fi

if [ ! -x bin/ffmpeg ]; then
  echo "Fetching ffmpeg ($FF)…"
  curl -fL -o bin/ffmpeg \
    "https://github.com/eugeneware/ffmpeg-static/releases/latest/download/$FF"
  chmod +x bin/ffmpeg
fi

# Optional: registering the MCP server with Claude Code enables the Claude
# agent fallback path. Not required — the app talks to Higgsfield directly.
if command -v claude >/dev/null 2>&1; then
  if ! claude mcp list 2>/dev/null | grep -q "higgsfield"; then
    echo "Optional: registering Higgsfield MCP with Claude Code (fallback)…"
    claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp || true
  fi
fi

echo ""
echo "Setup complete. Now run:"
echo "  python3 -m app.server"
echo "then open http://localhost:8787 — the page walks you through"
echo "connecting your Higgsfield account and adding your photo."
