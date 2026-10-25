#!/usr/bin/env bash
# Container entrypoint (pods and local runs). Software is all in the image, so
# this only wires up storage, models and the password:
#  1. Wait for /workspace to be a mountpoint (a network volume, a pod volume or a
#     local bind mount). An empty dir there could be the container's overlay fs,
#     which would silently put everything on disk that dies with the container.
#  2. Serialize boots with a lock on the volume.
#  3. Move ComfyUI's models/input/output/user onto the volume, symlinked back.
#  4. Fetch what's missing from models.txt (MODELS_SOURCE below), check SHA-256s.
#  5. Seed the bundled workflows (never overwriting edited copies).
#  6. Start the optional app (app/run.sh). With PUID set (local runs), hand files to that user.
#  7. Put nginx with basic auth (POD_AUTH) in front of ComfyUI and the app, and
#     exec ComfyUI as PID 1 so RunPod's stop signals reach it.
#
# Environment:
#   POD_AUTH             user:password. Unset: open, with a warning. "off": open, no warning (local).
#   MODELS_SOURCE        url (default: each models.txt URL) | r2 (fetch-models.sh copies the
#                        project's R2 prefix, R2_PREFIX, with R2_* read-only creds; then URLs
#                        for anything left; tools/pod.py sets all of it) | s3:<DC>:<volume id>
#                        (another volume's S3 gateway; needs AWS_ACCESS_KEY_ID/SECRET, which
#                        open every volume: remove them from the pod afterwards)
#   SKIP_MODEL_DOWNLOAD  true: don't look at models.txt at all
#   VERIFY_MODELS        true: re-hash files already present (slow: ~90 MiB/s on a cold volume)
#   HF_TOKEN             sent to huggingface.co only, for gated models
#   COMFY_ARGS           extra ComfyUI arguments, e.g. "--cache-lru 10"
#   REQUIRE_MOUNT        false: boot without a mounted /workspace (throwaway tests)
#   PUID, PGID           local runs: chown new root-owned files under /workspace
set -euo pipefail

COMFY_ROOT=/opt/ComfyUI
VOLUME_ROOT=/workspace
log() { echo "[boot] $*"; }

# ---- 1. the volume
if [[ "${REQUIRE_MOUNT:-true}" != false ]]; then
  log "waiting for $VOLUME_ROOT to mount..."
  for i in $(seq 1 30); do
    mountpoint -q "$VOLUME_ROOT" && break
    (( i == 30 )) && { echo "[FATAL] $VOLUME_ROOT never became a mountpoint: create the pod with a network volume" \
                            "in its datacenter or a pod volume (REQUIRE_MOUNT=false to skip)" >&2; exit 1; }
    sleep 2
  done
fi
mkdir -p "$VOLUME_ROOT"

# ---- 2. one boot at a time
exec 9>"$VOLUME_ROOT/.boot.lock"
flock -w 300 9 || { echo "[FATAL] boot lock still held after 300 s" >&2; exit 1; }

# ---- 3. persistent dirs
for d in models input output user; do
  mkdir -p "$VOLUME_ROOT/$d"
  [[ -L "$COMFY_ROOT/$d" ]] && continue
  if [[ -d "$COMFY_ROOT/$d" ]]; then
    rsync -a --ignore-existing "$COMFY_ROOT/$d/" "$VOLUME_ROOT/$d/"   # keep ComfyUI's stub files
    rm -rf "${COMFY_ROOT:?}/$d"
  fi
  ln -s "$VOLUME_ROOT/$d" "$COMFY_ROOT/$d"
done

# ---- 4. models
# models.txt: <models/ subdir> <url> [sha256]. The file name is the URL's basename (no query).
# "r2:<name>" instead of a URL: a file that exists only in the project's R2 prefix
# (<R2_PREFIX>/<subdir>/<name>), so it can only come from MODELS_SOURCE=r2.
manifest_entries() { grep -vE '^\s*(#|$)' "$COMFY_ROOT/models.txt" || true; }
target_of() { local u="${2#r2:}"; u="${u%%\?*}"; echo "$VOLUME_ROOT/models/$1/$(basename "$u")"; }

fetch_url() {   # url dest
  local hdr=()
  [[ -n "${HF_TOKEN:-}" && "$1" == https://huggingface.co/* ]] && hdr=(-H "Authorization: Bearer $HF_TOKEN")
  curl -L --fail --show-error --retry 3 --retry-delay 5 -C - -sS "${hdr[@]}" -o "$2" "$1"
}

fetch_s3() {    # key dest; get-object, not "aws s3 cp": the gateway rejects HeadObject
  local spec="${MODELS_SOURCE#s3:}"; local dc="${spec%%:*}" vol="${spec#*:}"
  dc="${dc,,}"   # the gateway wants the region in lower case
  /opt/awscli/bin/aws --endpoint-url "https://s3api-$dc.runpod.io" --region "$dc" --cli-read-timeout 600 \
    s3api get-object --bucket "$vol" --key "$1" "$2" > /dev/null
}

check_sha() {   # file expected-sha (empty: skip). A bad file is renamed, never used.
  [[ -z "$2" ]] && return 0
  local got; got=$(sha256sum "$1" | cut -d' ' -f1)
  [[ "$got" == "$2" ]] && return 0
  echo "[boot] ERROR: $(basename "$1"): SHA-256 $got, expected $2; moved to $(basename "$1").bad" >&2
  mv -f "$1" "$1.bad"
  return 1
}

model_errors=0
if [[ "${SKIP_MODEL_DOWNLOAD:-false}" == true ]]; then
  log "SKIP_MODEL_DOWNLOAD=true: not checking models.txt"
else
  missing=()
  while read -r subdir url sha _; do
    t=$(target_of "$subdir" "$url")
    if [[ -f "$t" ]]; then
      [[ "${VERIFY_MODELS:-false}" == true ]] && { check_sha "$t" "${sha:-}" || missing+=("$subdir $url ${sha:-}"); }
    else
      missing+=("$subdir $url ${sha:-}")
    fi
  done < <(manifest_entries)
  log "models: ${#missing[@]} of $(manifest_entries | wc -l) missing (source: ${MODELS_SOURCE:-url})"

  # R2 first, in one go (parallel streams); whatever it didn't bring comes from the URLs below.
  if (( ${#missing[@]} )) && [[ "${MODELS_SOURCE:-url}" == r2 ]]; then
    XDG_CACHE_HOME="$VOLUME_ROOT/.cache" FETCH_SKIP_SPACE_CHECK="${FETCH_SKIP_SPACE_CHECK:-1}" \
      "$COMFY_ROOT/fetch-models.sh" "$VOLUME_ROOT/models" || log "WARNING: fetch from R2 failed; falling back to URLs"
  fi

  for entry in "${missing[@]}"; do
    read -r subdir url sha <<< "$entry"
    t=$(target_of "$subdir" "$url"); name=$(basename "$t")
    mkdir -p "$(dirname "$t")"
    if [[ ! -f "$t" ]]; then
      # .partial + mv: a killed transfer never passes for a complete file.
      if [[ "$url" == r2:* ]]; then
        if [[ "${MODELS_SOURCE:-url}" == r2 ]]; then
          echo "[boot] ERROR: $subdir/$name: not in R2 under ${R2_PREFIX:-models}/$subdir/ (tools/r2.sh push)" >&2
        else
          echo "[boot] ERROR: $subdir/$name: only in R2; set MODELS_SOURCE=r2 in project.conf and update the pod" >&2
        fi
        model_errors=$((model_errors + 1)); continue
      elif [[ "${MODELS_SOURCE:-url}" == s3:* ]] && fetch_s3 "models/$subdir/$name" "$t.partial"; then
        log "  $name: from ${MODELS_SOURCE#s3:}"
      else
        log "  $name: downloading"
        fetch_url "$url" "$t.partial" || { echo "[boot] ERROR: $name: download failed (401/403 from Hugging Face: gated or private, set HF_TOKEN)" >&2; model_errors=$((model_errors + 1)); continue; }
      fi
      mv "$t.partial" "$t"
    fi
    check_sha "$t" "${sha:-}" || model_errors=$((model_errors + 1))
  done
  (( model_errors )) && log "WARNING: $model_errors model file(s) missing or bad; ComfyUI starts anyway, jobs using them will fail"
fi

# ---- 5. workflows
mkdir -p "$VOLUME_ROOT/user/default/workflows"
rsync -a --ignore-existing /opt/workflows/ "$VOLUME_ROOT/user/default/workflows/"

flock -u 9

# ---- 6. local ownership, optional app
if [[ -n "${PUID:-}" ]]; then
  owner="${PUID}:${PGID:-$PUID}"
  log "files under $VOLUME_ROOT go to $owner"
  ( while true; do find "$VOLUME_ROOT" -uid 0 -print0 2>/dev/null | xargs -0 -r chown -h "$owner"; sleep 5; done ) &
fi

AUTH="${POD_AUTH:-}"
protected=false
[[ "$AUTH" == *:* && -x /usr/sbin/nginx ]] && protected=true
APP_INTERNAL=$(( ${APP_PORT:-8770} + 10000 ))

if [[ -x /opt/app/run.sh && "${APP:-on}" != off ]]; then
  app_host=0.0.0.0 app_port="${APP_PORT:-8770}"
  $protected && app_host=127.0.0.1 app_port=$APP_INTERNAL
  log "starting app on $app_host:$app_port"
  ( while true; do
      APP_HOST=$app_host APP_LISTEN_PORT=$app_port VOLUME_ROOT=$VOLUME_ROOT /opt/app/run.sh >> /tmp/app.log 2>&1
      echo "[app] exited ($?), restarting in 5 s" >> /tmp/app.log; sleep 5
    done ) &
fi

# ---- 7. nginx + ComfyUI
cd "$COMFY_ROOT"
# shellcheck disable=SC2206
extra=(${COMFY_ARGS:-})
if $protected; then
  ( umask 077
    hash=$(printf '%s' "${AUTH#*:}" | openssl passwd -apr1 -stdin)   # the password via stdin, not argv
    printf '%s:%s\n' "${AUTH%%:*}" "$hash" > /etc/nginx/pod.htpasswd )
  chgrp www-data /etc/nginx/pod.htpasswd && chmod 640 /etc/nginx/pod.htpasswd
  server() {  # public-port internal-port
    cat <<NGINX
server {
    listen $1 default_server;
    client_max_body_size 200m;
    location / {
        auth_basic "$(echo "${PROJECT:-pod}" | tr -cd 'A-Za-z0-9_-')";
        auth_basic_user_file /etc/nginx/pod.htpasswd;
        proxy_pass http://127.0.0.1:$2;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header Authorization "";
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 1d;
        proxy_send_timeout 1d;
    }
}
NGINX
  }
  { echo 'map $http_upgrade $connection_upgrade { default upgrade; "" close; }'
    server 8188 8189
    [[ -x /opt/app/run.sh ]] && server "${APP_PORT:-8770}" "$APP_INTERNAL"
  } > /etc/nginx/conf.d/pod.conf
  # Fail closed: if nginx doesn't start, ComfyUI stays on 127.0.0.1 and is unreachable.
  { nginx -t -q && nginx; } || log "ERROR: nginx didn't start; ComfyUI stays local-only"
  log "ComfyUI on 127.0.0.1:8189 behind nginx on :8188 (password required)"
  exec ./venv/bin/python main.py --listen 127.0.0.1 --port 8189 "${extra[@]}"
fi
[[ "$AUTH" == off ]] || log "WARNING: POD_AUTH (user:password) not set: ComfyUI has no password"
log "ComfyUI on 0.0.0.0:8188"
exec ./venv/bin/python main.py --listen 0.0.0.0 --port 8188 "${extra[@]}"
