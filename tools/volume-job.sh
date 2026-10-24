#!/bin/bash
# Runs on a throwaway RunPod pod with a network volume at /workspace (tools/fill-volume.py
# starts it and fills in the __*_B64__ placeholders). JOB is one of:
#   urls   models.txt's URLs -> /workspace/models (only what's missing), then the SHA-256 check
#   r2     R2 -> /workspace/models (fetch-models.sh), then the SHA-256 check
#   push   the SHA-256 check, then /workspace/models -> R2 (MD5 compare: files already in R2 stay)
#   check  the SHA-256 check only
# The log is served on port 8000 through RunPod's proxy. It holds file names and
# timings, never keys. It ends with JOBDONE or JOBFAILED; then the pod idles until deleted.
mkdir -p /srv && : > /srv/log.txt
python3 -m http.server 8000 --directory /srv > /dev/null 2>&1 &
exec >> /srv/log.txt 2>&1
export DEBIAN_FRONTEND=noninteractive R2_ENV_FILE=/nonexistent
echo "pod ${RUNPOD_POD_ID:-?} dc ${RUNPOD_DC_ID:-?} job $JOB $(date -u +%FT%TZ)"
command -v curl > /dev/null || { apt-get update -qq > /dev/null && apt-get install -y -qq curl ca-certificates > /dev/null; }
echo "__FETCH_B64__" | base64 -d > /fetch-models.sh && chmod +x /fetch-models.sh
echo "__SHA_B64__" | base64 -d > /expected.sha256
echo "__MANIFEST_B64__" | base64 -d > /models.txt
mkdir -p /workspace/models && cd /workspace/models || exit 1

check() {
  if [[ ! -s /expected.sha256 ]]; then echo "=== no SHA-256s in models.txt, skipping the check"; return 0; fi
  echo "=== sha256 ($(wc -l < /expected.sha256) files)"; local t=$SECONDS
  sha256sum -c /expected.sha256 && echo "  all OK ($(( SECONDS - t )) s)"
}

from_urls() {
  local fail=0 subdir url name hdr
  while read -r subdir url _; do
    [[ -z "$subdir" || "$subdir" == \#* ]] && continue
    name=$(basename "${url%%\?*}")
    [[ -f "$subdir/$name" ]] && { echo "  $subdir/$name: present"; continue; }
    mkdir -p "$subdir"; hdr=()
    [[ -n "${HF_TOKEN:-}" && "$url" == https://huggingface.co/* ]] && hdr=(-H "Authorization: Bearer $HF_TOKEN")
    local t=$SECONDS
    if curl -L --fail -sS --retry 3 --retry-delay 5 -C - "${hdr[@]}" -o "$subdir/$name.partial" "$url"; then
      mv "$subdir/$name.partial" "$subdir/$name"
      echo "  $subdir/$name: $(du -h "$subdir/$name" | cut -f1) in $(( SECONDS - t )) s"
    else
      echo "  $subdir/$name: FAILED"; fail=1
    fi
  done < /models.txt
  return $fail
}

ok=0
case "$JOB" in
  urls)  echo "=== download"; from_urls && check && ok=1 ;;
  # df on a network volume shows the whole storage cluster, not the volume's quota.
  r2)    t=$SECONDS; FETCH_SKIP_SPACE_CHECK=1 /fetch-models.sh /workspace/models \
           && echo "  fetch took $(( SECONDS - t )) s" && check && ok=1
         find /workspace/models -name "*.partial" -print -delete ;;
  push)  check && FETCH_FLAGS="--checksum ${FETCH_FLAGS:-}" /fetch-models.sh --push /workspace/models \
           && /fetch-models.sh --list && ok=1 ;;
  check) check && ok=1 ;;
  *)     echo "unknown JOB '$JOB'" ;;
esac
[[ $ok == 1 ]] && echo "=== JOBDONE $(date -u +%FT%TZ)" || echo "=== JOBFAILED $(date -u +%FT%TZ)"
sleep infinity
