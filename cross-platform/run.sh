#!/bin/sh
# Starts QRKeyboard on macOS / Linux. Everything it needs (uv, Python, libraries) is downloaded
# into this folder (.tools/ and .venv/) on first run; nothing is installed system-wide.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
UV_VERSION=0.9.5
TOOLS="$HERE/.tools"

export UV_CACHE_DIR="$TOOLS/cache"
export UV_PYTHON_INSTALL_DIR="$TOOLS/python"
export UV_PYTHON_BIN_DIR="$TOOLS/bin"
export UV_PYTHON_PREFERENCE=only-managed
export UV_PROJECT_ENVIRONMENT="$HERE/.venv"
export UV_NO_CONFIG=1

if [ ! -x "$TOOLS/uv" ]; then
    case "$(uname -m)" in
        arm64|aarch64) ARCH=aarch64 ;;
        x86_64|amd64)  ARCH=x86_64 ;;
        *) echo "Unsupported CPU: $(uname -m)" >&2; exit 1 ;;
    esac
    case "$(uname -s)" in
        Darwin) TARGET="$ARCH-apple-darwin" ;;
        Linux)  TARGET="$ARCH-unknown-linux-gnu" ;;
        *) echo "Unsupported OS: $(uname -s). On Windows use run.bat." >&2; exit 1 ;;
    esac
    URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$TARGET.tar.gz"
    echo "Downloading uv $UV_VERSION into $TOOLS ..."
    mkdir -p "$TOOLS"
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$URL" -o "$TOOLS/uv.tar.gz"
    else wget -qO "$TOOLS/uv.tar.gz" "$URL"; fi
    tar -xzf "$TOOLS/uv.tar.gz" -C "$TOOLS" --strip-components=1
    rm -f "$TOOLS/uv.tar.gz"
fi

exec "$TOOLS/uv" run --project "$HERE" --frozen python "$HERE/qrkeyboard.py" "$@"
