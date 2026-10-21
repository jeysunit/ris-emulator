#!/usr/bin/env bash
# 画面の htmx を、版を固定して取り、sha256 を確かめて置く。置いた物は commit する。
# 利用者はこれを流さなくてよい（版を上げるときだけ使う）。
#
# 使い方: bash scripts/fetch_web_assets.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATIC="$ROOT/app/web/static"

HTMX_VERSION="v2.0.9"
HTMX_URL="https://github.com/bigskysoftware/htmx/releases/download/$HTMX_VERSION/htmx.min.js"
HTMX_SHA256="57d9191515339922bd1356d7b2d80b1ee3b29f1b3a2c65a078bb8b2e8fd9ae5f"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 -o "$tmp" "$HTMX_URL"
actual="$(sha256sum "$tmp" | cut -d' ' -f1)"
if [[ "$actual" != "$HTMX_SHA256" ]]; then
  echo "sha256 mismatch: htmx.min.js (expected $HTMX_SHA256, got $actual)" >&2
  exit 1
fi
install -m 0644 "$tmp" "$STATIC/htmx.min.js"
echo "htmx $HTMX_VERSION -> $STATIC/htmx.min.js"
