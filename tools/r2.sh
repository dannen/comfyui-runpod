#!/usr/bin/env bash
# This project's files in Cloudflare R2 (R2_PREFIX in project.conf), through fetch-models.sh.
#
#   tools/r2.sh list                 what's under the prefix, with sizes (read-only key)
#   tools/r2.sh push DIR             upload DIR (laid out like models/: loras/x.safetensors, ...)
#                                    with the read-write key; prints a models.txt line, with its
#                                    SHA-256, for each file models.txt doesn't list yet
#   tools/r2.sh fetch [DIR]          download the prefix to DIR (default ./models)
#
# One bucket serves every project; each project has its own prefix, so a pod copies only its
# own models. R2-only files go into models.txt as "<subdir> r2:<name> <sha256>".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
conf() { python3 "$ROOT/tools/rp.py" conf "$@"; }
cmd="${1:-}"
case "$cmd" in
  list|fetch) write=False ;;
  push) write=True; [[ -d "${2:-}" ]] || { echo "usage: $0 push DIR" >&2; exit 2; } ;;
  *) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 2 ;;
esac

# The R2_* values go to fetch-models.sh in its environment, never on a command line.
while IFS='=' read -r k v; do export "$k=$v"; done < <(cd "$ROOT/tools" && python3 -c "
import rp
for k, v in rp.r2_env(write=$write).items():
    print(f'{k}={v}')")
export R2_ENV_FILE=/nonexistent
echo "R2: $R2_BUCKET/$R2_PREFIX"

case "$cmd" in
  list)  exec "$ROOT/tools/fetch-models.sh" --list ;;
  fetch) exec "$ROOT/tools/fetch-models.sh" "${2:-$ROOT/models}" ;;
  push)
    dir=$(cd "$2" && pwd)
    "$ROOT/tools/fetch-models.sh" --push "$dir"
    echo "models.txt lines for files it doesn't list yet:"
    (cd "$dir" && find . -type f ! -name '*.partial' -printf '%P\n' | sort) | while read -r rel; do
      [[ "$rel" == */* ]] || { echo "  # $rel: not in a models/ subfolder (loras/, checkpoints/, ...), skipped"; continue; }
      sub="${rel%/*}" name="${rel##*/}"
      grep -qE "^$sub[[:space:]].*/$name([?[:space:]]|$)|^$sub[[:space:]]+r2:$name([[:space:]]|$)" "$ROOT/models.txt" && continue
      echo "$sub r2:$name $(sha256sum "$dir/$rel" | cut -d' ' -f1)"
    done
    ;;
esac
