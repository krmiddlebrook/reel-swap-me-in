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

# Optional: local face-restore pass (FaceFusion). Re-imposes your real face
# onto the swapped video — the swap engines drift on facial identity.
# ~2 GB of tooling + models, so it's opt-in: ./setup.sh --face-restore
FACE_RESTORE=0
for arg in "$@"; do
  [ "$arg" = "--face-restore" ] && FACE_RESTORE=1
done

if [ "$FACE_RESTORE" = "1" ]; then
  FF_VERSION=3.6.1
  mkdir -p vendor
  case "$OS-$ARCH" in
    Darwin-arm64)              UV_PKG="uv-aarch64-apple-darwin" ;;
    Darwin-*)                  UV_PKG="uv-x86_64-apple-darwin" ;;
    Linux-aarch64|Linux-arm64) UV_PKG="uv-aarch64-unknown-linux-gnu" ;;
    Linux-x86_64)              UV_PKG="uv-x86_64-unknown-linux-gnu" ;;
  esac
  UV_VERSION=0.11.20
  if [ ! -x vendor/uv ]; then
    echo "Fetching uv $UV_VERSION ($UV_PKG)…"
    curl -fL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$UV_PKG.tar.gz" | tar -xz -C vendor
    mv "vendor/$UV_PKG/uv" vendor/uv
    rm -rf "vendor/$UV_PKG"
  fi
  export UV_CACHE_DIR="$PWD/vendor/.uv-cache" UV_PYTHON_INSTALL_DIR="$PWD/vendor/pythons"
  vendor/uv python install 3.12 --no-bin
  if [ ! -d vendor/facefusion ]; then
    echo "Fetching FaceFusion $FF_VERSION…"
    curl -fL "https://github.com/facefusion/facefusion/archive/refs/tags/$FF_VERSION.tar.gz" | tar -xz -C vendor
    mv "vendor/facefusion-$FF_VERSION" vendor/facefusion
  fi
  [ -d vendor/ff-venv ] || vendor/uv venv vendor/ff-venv --python 3.12
  vendor/uv pip install --python vendor/ff-venv/bin/python -r vendor/facefusion/requirements.txt
  echo "Face restore ready — models (~1 GB) download on first use."
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
