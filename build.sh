#!/usr/bin/env bash
# Build the image locally and tag it by git commit.
#
#   ./build.sh                 IMAGE:<sha>          (cu130) + IMAGE:latest
#   ./build.sh --cu128         IMAGE:<sha>-cu128    (CUDA 12.8 hosts, local GPUs) + IMAGE:latest-cu128
#   ./build.sh --push          also push both tags
#   ./build.sh --cache         reuse cached layers (quick local iterations only)
#
# Release builds use --no-cache: a cached layer can hold an old custom node or
# pip resolution forever. Uncommitted changes give a <sha>-dirty tag, which
# --push refuses: a tag must say exactly what's in the image. Build here, not
# in GitHub Actions: hosted runners run out of disk on images like this.
set -euo pipefail
cd "$(dirname "$0")"
conf() { python3 tools/rp.py conf "$@"; }

variant="" push=false cache=(--no-cache)
for a in "$@"; do
  case "$a" in
    --cu128) variant=-cu128 ;;
    --push) push=true ;;
    --cache) cache=() ;;
    *) echo "usage: $0 [--cu128] [--push] [--cache]" >&2; exit 2 ;;
  esac
done

image=$(conf IMAGE)
[[ "$image" == YOUR_DOCKERHUB_USER/* ]] && { echo "ERROR: set IMAGE in project.conf first" >&2; exit 1; }
sha=$(git rev-parse --short HEAD 2>/dev/null || echo nogit)
[[ -z "$(git status --porcelain 2>/dev/null)" && "$sha" != nogit ]] || sha="$sha-dirty"
if $push && [[ "$sha" == *-dirty || "$sha" == nogit* ]]; then
  echo "ERROR: commit first: --push needs a clean tree (tag $sha)" >&2; exit 1
fi

args=(--build-arg "PROJECT=$(conf PROJECT)")
[[ -n "$(conf APP_PORT)" ]] && args+=(--build-arg "APP_PORT=$(conf APP_PORT)")
[[ -n "$variant" ]] && args+=(--build-arg BASE_IMAGE=nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04 --build-arg CUDA_TAG=cu128)

tag="$image:$sha$variant" latest="$image:latest$variant"
echo "building $tag"
docker build "${cache[@]}" "${args[@]}" -t "$tag" -t "$latest" .
if $push; then
  docker push "$tag"
  docker push "$latest"
  echo "pushed $tag and $latest"
fi
echo "roll out: tools/pod.py update --image $tag"
