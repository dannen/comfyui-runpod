#!/usr/bin/env bash
# Run the pod image on this machine's NVIDIA GPU (needs the NVIDIA Container
# Toolkit). Ports are bound to 127.0.0.1 only, so it runs without a password.
#
#   ./run-local.sh           start (or restart) the container
#   ./run-local.sh stop      stop and remove it
#   ./run-local.sh logs      follow its log
#   ./run-local.sh --cpu     no GPU (smoke tests of the image: start.sh, nodes, workflows)
#
# Settings (environment > project.local.conf > project.conf): LOCAL_NAME,
# LOCAL_IMAGE (default IMAGE:latest + LOCAL_IMAGE_SUFFIX), LOCAL_COMFY_PORT,
# LOCAL_APP_PORT, and the folders mounted into /workspace:
#   LOCAL_STATE  -> /workspace          ComfyUI's user settings, workflows, the app's state
#   LOCAL_MODELS -> /workspace/models   models.txt files missing here are downloaded on start
#   LOCAL_INPUT  -> /workspace/input    uploads
#   LOCAL_OUTPUT -> /workspace/output   results
# Files the container writes there are handed to you (PUID/PGID), not left to root.
set -euo pipefail
cd "$(dirname "$0")"
conf() { python3 tools/rp.py conf "$@"; }
path() { local p; p=$(conf "$1"); [[ "$p" == /* ]] && echo "$p" || echo "$PWD/${p#./}"; }

cmd=start gpu=(--gpus all) comfy_args=""
for a in "$@"; do
  case "$a" in
    start|stop|logs) cmd=$a ;;
    --cpu) gpu=() comfy_args="--cpu" ;;
    *) echo "usage: $0 [start|stop|logs] [--cpu]" >&2; exit 2 ;;
  esac
done

name=$(conf LOCAL_NAME "$(conf PROJECT)-local")
case "$cmd" in
  stop) docker rm -f "$name" >/dev/null && echo "stopped $name"; exit ;;
  logs) exec docker logs -f "$name" ;;
esac

image=$(conf LOCAL_IMAGE "$(conf IMAGE):latest$(conf LOCAL_IMAGE_SUFFIX)")
comfy_port=$(conf LOCAL_COMFY_PORT 8188)
app_port=$(conf LOCAL_APP_PORT)
state=$(path LOCAL_STATE) models=$(path LOCAL_MODELS) input=$(path LOCAL_INPUT) output=$(path LOCAL_OUTPUT)

# Create the folders as you, or Docker creates them owned by root (the last ones are mount points).
mkdir -p "$state" "$models" "$input" "$output" "$state"/{models,input,output}
ours=$(docker port "$name" 2>/dev/null | sed 's/.*://' || true)
for port in $comfy_port $app_port; do
  if ss -ltn "sport = :$port" | grep -q LISTEN && ! grep -qx "$port" <<< "$ours"; then
    echo "ERROR: port $port is in use; set LOCAL_COMFY_PORT / LOCAL_APP_PORT in project.local.conf" >&2; exit 1
  fi
done

ports=(-p "127.0.0.1:$comfy_port:8188")
[[ -n "$app_port" ]] && ports+=(-p "127.0.0.1:$app_port:$(conf APP_PORT 8770)")
docker rm -f "$name" >/dev/null 2>&1 || true
docker run -d --name "$name" "${gpu[@]}" \
  -v "$state:/workspace" -v "$models:/workspace/models" \
  -v "$input:/workspace/input" -v "$output:/workspace/output" \
  -e POD_AUTH=off -e PUID="$(id -u)" -e PGID="$(id -g)" -e COMFY_ARGS="$comfy_args" \
  "${ports[@]}" "$image" >/dev/null

echo "starting $name ($image)..."
for _ in $(seq 1 600); do
  curl -sf -o /dev/null "http://127.0.0.1:$comfy_port/system_stats" && break
  if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" != true ]]; then
    docker logs "$name" 2>&1 | tail -30; echo "ERROR: $name stopped" >&2; exit 1
  fi
  sleep 3
done
echo "ComfyUI: http://127.0.0.1:$comfy_port"
[[ -n "$app_port" ]] && echo "App:     http://127.0.0.1:$app_port"
echo "Models:  $models"
echo "Input:   $input"
echo "Output:  $output"
