#!/usr/bin/env bash
# fetch-models.sh: keep ComfyUI models (safetensors, LoRAs, project data) in a
# Cloudflare R2 bucket and copy them onto a pod's own disk at boot, so a pod
# doesn't need a RunPod network volume. R2 charges nothing for downloads.
#
#   fetch-models.sh [DEST]          copy R2_BUCKET/R2_PREFIX -> DEST (default:
#                                   /workspace/models if /workspace exists, else ./models)
#   fetch-models.sh --push SRC      upload SRC -> R2_BUCKET/R2_PREFIX (needs a read-write token)
#   fetch-models.sh --list          list what's in the bucket, with sizes
#
# Credentials come from the environment, or from R2_ENV_FILE
# (default ~/.api/cloudflare/r2.env) for any that are unset:
#   R2_ACCOUNT_ID         Cloudflare account ID (the endpoint is <id>.r2.cloudflarestorage.com)
#   R2_ACCESS_KEY_ID      R2 API token's Access Key ID
#   R2_SECRET_ACCESS_KEY  R2 API token's Secret Access Key
#   R2_BUCKET             bucket name
#   R2_PREFIX             folder inside the bucket (default: models)
#   R2_ENDPOINT           optional, e.g. https://<id>.eu.r2.cloudflarestorage.com for an EU bucket
# Pods should get a read-only token; keep the read-write one on your own machine.
#
# Only missing or changed files are copied (size + modification time, within
# 1 s), so a rerun after a reboot is quick. rclone downloads to a .partial name and renames
# when done, and checks each file's MD5 when R2 has one (rclone stores it for
# its own multipart uploads, so upload with --push). Exits non-zero on any
# failure, so a boot script can fall back to another source.
#
# Tuning: FETCH_TRANSFERS (files at once, default 4), FETCH_STREAMS (parallel
# streams per big file, default 16), FETCH_SKIP_SPACE_CHECK=1, FETCH_FLAGS (extra
# rclone flags for the copy, e.g. --checksum to compare MD5s instead of mtimes).
# rclone: the pinned version is downloaded (SHA-256 checked) and used, even if
# another rclone is on PATH (pod images can carry an old one); RCLONE=/path overrides.
set -euo pipefail

RCLONE_VERSION=v1.71.2
declare -A RCLONE_SHA256=(
  [amd64]=ab9fa5877cee91c64fdfd61a27028a458cf618b39259e5c371dc2ec34a12e415
  [arm64]=e2e2efc7ed143026352d60216ef0d46d3fa4fe9d647eff1bd929e6fea498e6f1
)

log() { echo "[fetch-models] $*"; }
die() { echo "[fetch-models] ERROR: $*" >&2; exit 1; }

mode=fetch
arg=""
case "${1:-}" in
  --push) mode=push; arg="${2:?usage: fetch-models.sh --push SRC}" ;;
  --list) mode=list ;;
  -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
  -*) die "unknown option $1 (try --help)" ;;
  *) arg="${1:-}" ;;
esac

# Fill unset variables from the env file, without overriding the environment.
env_file="${R2_ENV_FILE:-$HOME/.api/cloudflare/r2.env}"
if [[ -f "$env_file" ]]; then
  for v in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET R2_PREFIX R2_ENDPOINT; do
    if [[ -z "${!v:-}" ]]; then
      val="$(sed -n "s/^\(export \)\{0,1\}$v=//p" "$env_file" | tail -1)"
      val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
      [[ -n "$val" ]] && printf -v "$v" '%s' "$val"
    fi
  done
fi
for v in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET; do
  [[ -n "${!v:-}" ]] || die "$v is not set (environment or $env_file)"
done
R2_PREFIX="${R2_PREFIX-models}"
R2_PREFIX="${R2_PREFIX#/}"; R2_PREFIX="${R2_PREFIX%/}"

# rclone: the pinned release unless RCLONE is set. Not whatever is on PATH: a
# RunPod CPU pod had an old rclone that doesn't know the Cloudflare provider.
RCLONE="${RCLONE:-}"
if [[ -z "$RCLONE" ]]; then
  case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) die "no rclone build pinned for $(uname -m)" ;;
  esac
  bin_dir="${XDG_CACHE_HOME:-$HOME/.cache}/fetch-models"
  RCLONE="$bin_dir/rclone-$RCLONE_VERSION"
  if [[ ! -x "$RCLONE" ]]; then
    log "installing rclone $RCLONE_VERSION"
    mkdir -p "$bin_dir"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    zip="rclone-$RCLONE_VERSION-linux-$arch.zip"
    curl -fsSL --retry 3 -o "$tmp/$zip" "https://downloads.rclone.org/$RCLONE_VERSION/$zip"
    echo "${RCLONE_SHA256[$arch]}  $tmp/$zip" | sha256sum -c --quiet - || die "rclone download failed its SHA-256 check"
    # Pod images often lack unzip; Python's zipfile does the same job.
    if command -v unzip > /dev/null; then
      unzip -q -j "$tmp/$zip" "*/rclone" -d "$tmp"
    else
      python3 -c 'import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
n = next(i for i in z.namelist() if i.endswith("/rclone"))
open(sys.argv[2], "wb").write(z.read(n))' "$tmp/$zip" "$tmp/rclone"
    fi
    install -m 755 "$tmp/rclone" "$RCLONE"
  fi
fi

# The remote is configured through environment variables: no rclone.conf, and
# the secret never lands on disk. no_check_bucket: a token scoped to one bucket
# may not list or create buckets.
export RCLONE_CONFIG=  # empty: run without a config file, and say nothing about it
export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ENDPOINT="${R2_ENDPOINT:-https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com}"
export RCLONE_CONFIG_R2_REGION=auto
export RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
export RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
remote="r2:$R2_BUCKET${R2_PREFIX:+/$R2_PREFIX}"
log "using $("$RCLONE" version 2>/dev/null | head -1) ($RCLONE)"

common=(${FETCH_FLAGS:-} --stats 30s --stats-one-line --stats-log-level NOTICE --retries 5 --low-level-retries 20 --contimeout 15s --exclude "*.partial")
# Listing first, with few retries: a wrong account ID or key fails in seconds, not minutes.
quick=(--retries 1 --low-level-retries 2 --contimeout 15s --timeout 60s)

case "$mode" in
  list)
    "$RCLONE" ls "$remote" "${quick[@]}"
    "$RCLONE" size "$remote" "${quick[@]}"
    ;;

  push)
    [[ -d "$arg" ]] || die "$arg is not a directory"
    log "uploading $arg -> $remote"
    "$RCLONE" copy "$arg" "$remote" "${common[@]}" \
      --transfers "${FETCH_TRANSFERS:-4}" --s3-upload-concurrency 8 --s3-chunk-size 64M
    log "done"
    ;;

  fetch)
    dest="$arg"
    if [[ -z "$dest" ]]; then
      if [[ -d /workspace ]]; then dest=/workspace/models; else dest=./models; fi
    fi
    mkdir -p "$dest"

    # A pod volume has a fixed size: fail early instead of half way through.
    if [[ "${FETCH_SKIP_SPACE_CHECK:-0}" != 1 ]]; then
      size_json="$("$RCLONE" size --json "$remote" "${quick[@]}")" \
        || die "can't list $remote (check R2_ACCOUNT_ID, the token and R2_BUCKET)"
      remote_bytes="$(python3 -c 'import json, sys; print(json.loads(sys.argv[1])["bytes"])' "$size_json")"
      local_bytes="$(du -sb "$dest" | cut -f1)"
      free_bytes="$(df -B1 --output=avail "$dest" | tail -1 | tr -d ' ')"
      need=$(( remote_bytes - local_bytes ))
      (( need < 0 )) && need=0
      log "bucket $(( remote_bytes / 1000000 )) MB, already here $(( local_bytes / 1000000 )) MB, free $(( free_bytes / 1000000 )) MB"
      (( free_bytes > need + 1000000000 )) || die "not enough space in $dest: need ~$(( need / 1000000 )) MB (+1 GB margin)"
    fi

    log "copying $remote -> $dest"
    start=$SECONDS
    # --modify-window 1s: RunPod network volumes keep whole-second mtimes; without it
    # every rerun re-hashes (MD5) all files uploaded with sub-second mtimes.
    "$RCLONE" copy "$remote" "$dest" "${common[@]}" --modify-window 1s \
      --transfers "${FETCH_TRANSFERS:-4}" \
      --multi-thread-streams "${FETCH_STREAMS:-16}" --multi-thread-cutoff 256M
    log "done in $(( SECONDS - start )) s"
    ;;
esac
