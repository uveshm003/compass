#!/bin/sh
# Compass bootstrap installer for macOS and Linux, run from a clone:
#
#   ./install.sh                                   # asks its questions
#   ./install.sh --editable -- --yes --scope user --mode files
#
# It holds no logic of its own (IN-12): it makes sure uv is installed, installs
# the compass CLI from this folder with `uv tool install`, then runs
# `compass install`, passing on everything after `--`.
# Run it from the repository you want Compass in, or pass --repo <path>.
set -eu

SOURCE=$(cd "$(dirname "$0")" && pwd)
EDITABLE=""
REPO=$(pwd)
YES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --editable) EDITABLE="--editable"; shift ;;
    --repo) REPO="$2"; shift 2 ;;
    --yes-uv) YES=1; shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done

find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return; fi
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$candidate" ]; then echo "$candidate"; return; fi
  done
}

UV=$(find_uv || true)
if [ -z "$UV" ]; then
  if [ -z "$YES" ]; then
    printf "uv is not installed. Install it with uv's official installer? [Y/n] "
    read -r answer || answer=""
    case "$answer" in [nN]*) echo "uv is needed for the compass CLI; see https://docs.astral.sh/uv/" >&2; exit 1 ;; esac
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  UV=$(find_uv || true)
  [ -n "$UV" ] || { echo "uv was installed but cannot be found; open a new terminal and run this again" >&2; exit 1; }
fi
echo "uv: $UV"

# shellcheck disable=SC2086  # EDITABLE is empty or one word
# 3.12, as CI tests: uv would otherwise take its newest Python, for which some pinned packages have no wheels yet
"$UV" tool install --force --compile-bytecode --python 3.12 $EDITABLE "$SOURCE"

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *)
    PATH="$HOME/.local/bin:$PATH"; export PATH
    "$UV" tool update-shell >/dev/null 2>&1 || true
    echo "Added ~/.local/bin to PATH; open a new terminal before starting Claude Code."
    ;;
esac

exec compass -C "$REPO" install --skip-cli "$@"
