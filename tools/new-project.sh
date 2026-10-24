#!/usr/bin/env bash
# Start a new project from this baseline, optionally from one of examples/.
#
#   tools/new-project.sh EXAMPLE DEST     e.g. tools/new-project.sh wan2.2 ../my-wan
#   tools/new-project.sh --empty DEST     the baseline alone (its example model, no workflows)
#   tools/new-project.sh --list           the examples
#
# Copies the baseline (the files git tracks here, without examples/) to DEST, then the
# example's models.txt, custom_nodes.txt and workflows/, and sets its project.conf
# values (example.conf). The example's README becomes DEST/EXAMPLE.md. DEST must not
# exist. Nothing is built, pushed or created on RunPod.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() { sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 2; }
[[ $# -ge 1 ]] || usage
if [[ "$1" == --list ]]; then
  for d in "$ROOT"/examples/*/; do
    printf '  %-16s %s\n' "$(basename "$d")" "$(head -1 "$d/README.md" | sed 's/^# //')"
  done
  exit 0
fi
[[ $# -eq 2 ]] || usage
example=$1 dest=$2
if [[ "$example" != --empty ]]; then
  ex="$ROOT/examples/$example"
  [[ -f "$ex/example.conf" ]] || { echo "ERROR: no example $example (tools/new-project.sh --list)" >&2; exit 1; }
fi
[[ ! -e "$dest" ]] || { echo "ERROR: $dest already exists" >&2; exit 1; }

# The baseline: tracked files only (no models, local config or caches), never examples/.
mkdir -p "$dest"
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$ROOT" ls-files -z | grep -zv '^examples/' | (cd "$ROOT" && xargs -0 cp --parents -t "$(realpath "$dest")")
else
  rsync -a --exclude examples/ --exclude models/ --exclude results/ --exclude .git/ \
        --exclude project.local.conf --exclude __pycache__/ "$ROOT/" "$dest/"
fi

if [[ -n "${ex:-}" ]]; then
  cp "$ex/models.txt" "$ex/custom_nodes.txt" "$dest/"
  rm -f "$dest/workflows/.gitkeep"
  cp "$ex"/workflows/*.json "$dest/workflows/"
  cp "$ex/README.md" "$dest/EXAMPLE.md"
  # example.conf's KEY=value lines replace the same keys in project.conf (TEMPLATES* are
  # kept as a note at the end, for refreshing the lists later).
  python3 - "$ex/example.conf" "$dest/project.conf" <<'PY'
import re, sys
ex = [l for l in open(sys.argv[1]).read().splitlines() if re.match(r"^[A-Z_][A-Z0-9_]*=", l)]
conf = open(sys.argv[2]).read()
notes = []
for line in ex:
    key = line.split("=", 1)[0]
    if key.startswith("TEMPLATES"):
        notes.append(line)
        continue
    conf, n = re.subn(rf"^{key}=.*$", lambda m: line, conf, count=1, flags=re.M)
    if not n:
        conf += f"\n{line}\n"
if notes:
    conf += ("\n# Where models.txt, custom_nodes.txt and workflows/ came from (tools/template-models.py\n"
             "# $TEMPLATES --ref $TEMPLATES_REF --write . refreshes them).\n" + "\n".join(notes) + "\n")
open(sys.argv[2], "w").write(conf)
PY
fi

echo "Created $dest${ex:+ from examples/$example}."
echo "Next:"
echo "  cd $dest && git init"
echo "  edit project.conf: IMAGE (your Docker Hub user), DATACENTERS; create the AUTH_FILE it names"
[[ -n "${ex:-}" ]] && echo "  read EXAMPLE.md (GPU, volume size, notes)"
echo "  ./build.sh --cu128 --cache && ./run-local.sh   (README: Build and test locally)"
