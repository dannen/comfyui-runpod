#!/usr/bin/env python3
"""Fill a network volume from inside its datacenter with a throwaway pod.

    fill-volume.py DC [VOLUME_ID]               models.txt's URLs -> the volume (only what's missing)
    fill-volume.py DC [VOLUME_ID] --source r2   your R2 bucket -> the volume (tools/fetch-models.sh)
    fill-volume.py DC [VOLUME_ID] --push        the volume's models/ -> R2 (read-write key)
    fill-volume.py DC [VOLUME_ID] --check       only check the SHA-256s from models.txt

Without VOLUME_ID, the datacenter's volume is found by VOLUME_NAME (project.conf).
The pod writes to /workspace directly, so nothing goes through the S3 gateway
(which can't upload a file bigger than about half a volume, DESIGN.md section 4),
and the download runs at datacenter speed instead of your home line's.

It tries cheap CPU pods first (GraphQL deployCpuPod), then GPU pods (REST), and
retries while the datacenter has no supply. It follows the pod's log (port 8000,
through RunPod's proxy) and always deletes the pod at the end: on success,
failure, timeout or Ctrl-C. Every file with a SHA-256 in models.txt is checked
on the volume (or, with --sha256 FILE, the files in that sha256sum-style list,
paths relative to models/). Exit status 0 = the job succeeded.

R2 credentials: R2_ENV_FILE_RO (fetch, read-only token) and R2_ENV_FILE (push,
read-write) from project.conf, files of R2_ACCOUNT_ID=, R2_ACCESS_KEY_ID=,
R2_SECRET_ACCESS_KEY=, R2_BUCKET= (and optionally R2_PREFIX=) lines. The pod gets
them as env vars, which is one more reason it is deleted at the end. HF_TOKEN
from your environment is passed on for gated models (--source urls).
"""

import argparse
import base64
import os
import sys
import time
import urllib.request
from pathlib import Path

import rp
from pod import find_volume

HERE = Path(__file__).resolve().parent
CPUS = "cpu3c-4-8,cpu5c-4-8,cpu3g-4-16,cpu5g-4-16,cpu3c-2-4,cpu3g-2-8,cpu5c-2-4,cpu3c-8-16"
GPUS = ("NVIDIA RTX A4000,NVIDIA RTX A4500,NVIDIA RTX 2000 Ada Generation,NVIDIA RTX 4000 Ada Generation,"
        "NVIDIA RTX A5000,NVIDIA GeForce RTX 3090,NVIDIA L4,NVIDIA GeForce RTX 4090,NVIDIA RTX A6000,NVIDIA L40S")
R2_KEYS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


def read_r2_env(path):
    env = {}
    for line in Path(path).expanduser().read_text().splitlines():
        k, sep, v = line.strip().partition("=")
        if sep and not k.startswith("#"):
            env[k.removeprefix("export ").strip()] = v.strip().strip("'\"")
    missing = [k for k in R2_KEYS if not env.get(k)]
    if missing:
        sys.exit(f"ERROR: {path}: missing {', '.join(missing)}")
    return {k: env[k] for k in (*R2_KEYS, "R2_PREFIX") if env.get(k)}


def manifest_and_sums(path):
    """models.txt as is, and a sha256sum -c list (paths relative to models/) of its SHA-256s."""
    text = Path(path).read_text()
    sums = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.lstrip().startswith("#"):
            sums.append(f"{parts[2]}  {parts[0]}/{parts[1].split('?')[0].rsplit('/', 1)[-1]}")
    return text, "".join(s + "\n" for s in sums)


def build_script(manifest, sums):
    b64 = lambda s: base64.b64encode(s.encode() if isinstance(s, str) else s).decode()
    return ((HERE / "volume-job.sh").read_text()
            .replace("__FETCH_B64__", b64((HERE / "fetch-models.sh").read_bytes()))
            .replace("__SHA_B64__", b64(sums))
            .replace("__MANIFEST_B64__", b64(manifest)))


def try_cpu(a, name, script, env):
    b64 = base64.b64encode(script.encode()).decode()
    for inst in a.cpu.split(","):
        inp = {"instanceId": inst, "cloudType": "SECURE", "dataCenterId": a.dc, "networkVolumeId": a.volume,
               "volumeMountPath": "/workspace", "containerDiskInGb": 10, "deployCost": 0.5, "imageName": a.image,
               "name": name, "startJupyter": False, "startSsh": False, "ports": "8000/http",
               "dockerArgs": f"bash -c 'echo {b64} | base64 -d | bash'",
               "env": [{"key": k, "value": v} for k, v in env.items()]}
        try:
            pod = rp.graphql("mutation($input: deployCpuPodInput!) { deployCpuPod(input: $input) { id costPerHr } }",
                             {"input": inp}).get("deployCpuPod")
        except rp.ApiError:
            pod = None
        if pod:
            return pod["id"], f"CPU {inst}, ${pod['costPerHr']}/hr"
    return None, None


def try_gpu(a, name, script, env):
    body = {"name": name, "imageName": a.image, "cloudType": "SECURE",
            "gpuTypeIds": a.gpu.split(","), "gpuTypePriority": "custom", "gpuCount": 1,
            "dataCenterIds": [a.dc], "dataCenterPriority": "custom", "networkVolumeId": a.volume,
            "volumeMountPath": "/workspace", "containerDiskInGb": 10, "ports": ["8000/http"],
            "env": env, "dockerStartCmd": ["bash", "-c", script]}
    try:
        r = rp.rest("POST", "/pods", body=body)
    except rp.ApiError:
        return None, None
    if r.get("id"):
        return r["id"], f"GPU {(r.get('machine') or {}).get('gpuTypeId', '?')}, ${r.get('costPerHr')}/hr"
    return None, None


def follow(pod, timeout):
    url = rp.proxy_url(pod, 8000) + "/log.txt"
    seen, start = 0, time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": rp.user_agent()})
            lines = urllib.request.urlopen(req, timeout=20).read().decode(errors="replace").splitlines()
        except Exception:
            lines = []   # the pod is still booting, or the proxy hiccuped
        if lines and lines[0].startswith("pod "):
            for line in lines[seen:]:
                if line and not line.startswith("debconf"):
                    print(line, flush=True)
            seen = len(lines)
            if any("=== JOBDONE" in l for l in lines):
                return True
            if any("=== JOBFAILED" in l for l in lines):
                return False
        time.sleep(15)
    print(f"timed out after {timeout} s", flush=True)
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dc", help="the volume's datacenter, e.g. US-KS-2")
    p.add_argument("volume", nargs="?", help="network volume id (default: found by VOLUME_NAME)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--source", choices=["urls", "r2"], default="urls", help="where the models come from")
    mode.add_argument("--push", action="store_true", help="volume -> R2 instead")
    mode.add_argument("--check", action="store_true", help="only check the SHA-256s")
    p.add_argument("--manifest", default=str(rp.ROOT / "models.txt"))
    p.add_argument("--sha256", help="check this sha256sum-style list (paths relative to models/) "
                                    "instead of models.txt's SHA-256s")
    p.add_argument("--flags", help="extra rclone flags (FETCH_FLAGS), e.g. --flags='--max-size 1G' (with =)")
    p.add_argument("--cpu", default=CPUS, help="CPU instance ids to try, in order")
    p.add_argument("--gpu", default=GPUS, help="GPU types to fall back to, in order ('' = CPU only)")
    p.add_argument("--image", default="python:3.12-slim")
    p.add_argument("--tries", type=int, default=20, help="rounds of CPU+GPU attempts (default 20)")
    p.add_argument("--wait", type=int, default=30, help="seconds between rounds")
    p.add_argument("--timeout", type=int, default=3600, help="seconds to wait for the job")
    a = p.parse_args()
    job = "push" if a.push else "check" if a.check else a.source

    if not a.volume:
        vol = find_volume(a.dc, rp.conf("VOLUME_NAME"))
        if not vol:
            sys.exit(f"ERROR: no volume named {rp.conf('VOLUME_NAME')}* in {a.dc} (tools/pod.py volumes)")
        a.volume = vol["id"]
        print(f"volume {vol['name']} ({vol['id']})")

    env = {"JOB": job}
    if job in ("r2", "push"):
        creds = rp.conf("R2_ENV_FILE" if job == "push" else "R2_ENV_FILE_RO")
        if not creds:
            sys.exit("ERROR: set R2_ENV_FILE_RO / R2_ENV_FILE in project.conf")
        env.update(read_r2_env(creds))
    if job == "urls" and os.environ.get("HF_TOKEN"):
        env["HF_TOKEN"] = os.environ["HF_TOKEN"]
    if a.flags:
        env["FETCH_FLAGS"] = a.flags
    manifest, sums = manifest_and_sums(a.manifest)
    if a.sha256:
        sums = Path(a.sha256).read_text()
    script = build_script(manifest, sums)
    name = f"{rp.conf('PROJECT', 'comfyui')}-volume-{job}"

    pod = desc = None
    for t in range(1, a.tries + 1):
        pod, desc = try_cpu(a, name, script, env)
        if not pod and a.gpu:
            pod, desc = try_gpu(a, name, script, env)
        if pod:
            break
        print(f"try {t}/{a.tries}: no CPU or GPU pod in {a.dc}, retrying in {a.wait} s", flush=True)
        time.sleep(a.wait)
    if not pod:
        sys.exit(f"ERROR: no pod available in {a.dc}")
    print(f"pod {pod} ({desc}), job {job}", flush=True)

    ok = False
    try:
        ok = follow(pod, a.timeout)
    except KeyboardInterrupt:
        print("interrupted", flush=True)
    finally:
        try:
            rp.rest("DELETE", f"/pods/{pod}")
            print(f"pod {pod} deleted", flush=True)
        except rp.ApiError as e:
            print(f"ERROR: deleting pod {pod} failed ({e}): delete it by hand", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
