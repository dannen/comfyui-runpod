# comfyui-runpod

A baseline for running a ComfyUI-based tool on a persistent RunPod Pod (and on
your own GPU with the same image). Copy it to start a new project; read
[DESIGN.md](DESIGN.md) for the reasoning and the lessons behind it.

What you get:

- **A pinned image** (`Dockerfile`, `build.sh`): ComfyUI core, torch from the CUDA
  index (cu130, or cu128 for older drivers), custom nodes pinned by commit, our
  own nodes, workflows. The build fails if a node pack doesn't import.
- **A boot script** (`start.sh`) that waits for the volume, keeps ComfyUI's
  folders on it, fetches missing models from `models.txt` (Hugging Face, an R2
  bucket or another volume) with SHA-256 checks, and puts a password (nginx basic
  auth) in front of ComfyUI, because RunPod's proxy URLs are public.
- **Tools** (`tools/`, Python standard library only):
  - `pod.py`: create / update / recreate / stop / start / delete the pod, volumes; tries
    datacenter x GPU lists in order; never drops the password on an update.
  - `gpus.py`: GPU stock by datacenter, ranked by price per GB of VRAM; `--cheapest` for the
    cheapest in-stock GPUs anywhere (secure, community and spot prices).
  - `comfy.py`: run an API-format workflow on the pod or locally, upload inputs,
    download results without overwriting; `check` lists node types a workflow
    uses that the running ComfyUI doesn't have.
  - `hf-sha256.py`: fill `models.txt`'s SHA-256 column from Hugging Face.
  - `template-models.py`: `models.txt` and `custom_nodes.txt` lines from official ComfyUI
    templates (or any workflow file), with sizes, SHA-256s and pinned node commits.
  - `new-project.sh`: a new project folder from the baseline, optionally from an example.
  - `fill-volume.py`: fill a volume from inside its datacenter with a throwaway pod (from the
    `models.txt` URLs or R2), check the SHA-256s, delete the pod.
  - `populate-volume.sh`: seed a volume from your machine through the S3 gateway (small files).
  - `fetch-models.sh`: copy models from a Cloudflare R2 bucket (also used at boot).
- **Local runs** (`run-local.sh`): the image on your GPU, folders mounted, no password.

**Using an AI coding agent?** Point it at [AGENTS.md](AGENTS.md). It covers
what to ask you up front, which steps need your confirmation (anything
billable), the order of work, and a first message you can give it.

## Layout

```
project.conf        names, image, datacenters, GPUs, ports: edit this first
project.local.conf  your machine's overrides (gitignored)
models.txt          every model: <subdir> <url> [sha256]
custom_nodes.txt    third-party nodes: <git url> <commit>
custom_nodes/       our own nodes (example: Output Name From Image)
workflows/          UI workflows, seeded into ComfyUI's Workflows sidebar
api/                API-format workflows for tools/comfy.py (smoke.json needs no model)
examples/           ready model lists, pinned nodes and workflows per model family
app/                optional second web app next to ComfyUI (see app/README.md)
Dockerfile build.sh start.sh run-local.sh
tools/              pod.py gpus.py comfy.py hf-sha256.py template-models.py new-project.sh
                    fill-volume.py rp.py
                    volume-job.sh populate-volume.sh fetch-models.sh
```

## Starting a new project

From an example ([examples/](examples/README.md): FLUX.1, Qwen-Image, Krea 2,
Marigold, LTX-2.3, Wan 2.2, Wan 2.2 Animate, MiniMax H3), which brings its
models, pinned nodes, workflows and settings:

```bash
tools/new-project.sh --list
tools/new-project.sh qwen-image ../my-qwen && cd ../my-qwen && git init
```

Or from scratch:

```bash
tools/new-project.sh --empty ../my-tool && cd ../my-tool && git init
$EDITOR project.conf                       # PROJECT, IMAGE, POD_NAME, VOLUME_NAME, AUTH_FILE, ...
(umask 077; mkdir -p ~/.api/runpod; echo 'me:a-long-password' > ~/.api/runpod/my-tool.auth)
$EDITOR models.txt && tools/hf-sha256.py --write
```

Then add workflows (`workflows/`, and API exports in `api/`) and, only if needed,
custom nodes (`custom_nodes.txt`). DESIGN.md section 12 is the full checklist.

## Build and test locally

```bash
./build.sh --cu128 --cache            # quick local build: IMAGE:<sha>-cu128 + latest-cu128
./run-local.sh                        # or --cpu without a GPU
tools/comfy.py status
tools/comfy.py run api/smoke.json --set 1.image=@some.png --out results/
tools/comfy.py check workflows/*.json   # every node type installed?
./run-local.sh stop
```

Release builds: commit, then `./build.sh --push` and `./build.sh --cu128 --push`
(no cache, clean tree required, tagged by commit).

## Run on RunPod

API key: `RUNPOD_API_KEY`, or the file in `RUNPOD_KEY_FILE` (default
`~/.api/runpod/api.key`). S3 key (for the gateway): the file in
`S3_CREDENTIALS_FILE` (default `~/.api/runpod/s3-credentials`, with
`aws_access_key_id = ...` and `aws_secret_access_key = ...`). Set `DATACENTERS`
in `project.conf` first.

```bash
tools/gpus.py --vram 24                         # who has stock, where
tools/pod.py create-volume US-KS-2              # VOLUME_NAME-ks, VOLUME_GB
tools/fill-volume.py US-KS-2                    # models.txt -> that volume, by a throwaway pod
tools/pod.py create --image IMAGE:<sha>-cu128   # tries DATACENTERS x GPU_TYPES
tools/pod.py status                             # URLs; open ComfyUI, log in with AUTH_FILE's user:password
tools/comfy.py run api/smoke.json --pod --set 1.image=@some.png
tools/pod.py update --image IMAGE:<new sha>-cu128
tools/pod.py stop                               # or: delete --yes (network volumes stay)
```

Filling the volume first (above) makes the pod's first boot quick. Otherwise
models arrive on first boot from their `models.txt` URLs. Other sources, via
`--env` on `create`/`update`:

- `MODELS_SOURCE=r2` plus read-only `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (and `R2_PREFIX`, default `models`).
- `MODELS_SOURCE=s3:<DC>:<volume id>` plus `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`:
  copy from another seeded volume. That key opens every volume; update the pod
  without it afterwards.
- `HF_TOKEN` for gated Hugging Face repos; `COMFY_ARGS="--cache-lru 10"` and
  other ComfyUI flags.

No network volume where the GPUs are: `tools/pod.py create --pod-volume-gb 50`
(the pod's own disk; deleted with the pod).

## Status

Tested 2026-10-24 on the local machine:

- `./build.sh --cu128` builds the image, including the node-import check.
- `run-local.sh --cpu` boots it. `start.sh` downloads the example model and
  checks its SHA-256, renames a file with the wrong checksum to `.bad`, and
  carries on when a download fails. Files end up owned by the host user.
- `tools/comfy.py` runs `api/smoke.json` (upload, queue, wait, download).
- With `POD_AUTH` set: 401 without the password or with a wrong one, 200 with
  it, websockets pass, and the password is not visible in the process list.
- The read-only API calls (`gpus.py`, `pod.py status` and `volumes`) work.
- `examples/`: every workflow's node types exist in the baseline's ComfyUI; the
  wan2.2-animate image builds with its three node packs (examples/README.md).
- On RunPod, `fill-volume.py` filled a test volume from the `models.txt` URLs
  and from R2 (CPU pods), checked the SHA-256s, reported a wrong checksum as a
  failure (exit 1), and deleted the pod each time.

Not tested yet in this baseline:

- `pod.py create`, `update` and the other billable calls. Their code is carried
  over from earlier projects, where it ran.
- The cu130 build.
- `MODELS_SOURCE=r2` and `s3:` at boot. `fetch-models.sh` itself is proven.
- `fill-volume.py --push`.
- `populate-volume.sh` with the SHA-256 column.

Serverless isn't included; DESIGN.md section 10 has the notes for it.

## License and thanks

MIT (see [LICENSE](LICENSE)). Copy it, change it, build on it. ComfyUI, the
models and any custom nodes you add come under their own licenses.

If this saved you time and you're new to RunPod, signing up through my
[referral link](https://runpod.io?ref=jon5epyp) is a way to say thanks.
