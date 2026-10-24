#!/usr/bin/env python3
"""Run an API-format workflow on ComfyUI (the pod or a local run) and download
what it saved.

    comfy.py status
    comfy.py run api/smoke.json --set 1.image=@photo.jpg --out ./results
    comfy.py run wf.json --set 5.seed=42 --set 6.text="a red door" --pod

--set NODE.INPUT=VALUE changes one input; VALUE is JSON if it parses (numbers,
true, lists), else a string, and @FILE uploads FILE to ComfyUI's input folder
and puts the uploaded name there. Export workflows with "Export (API)" in
ComfyUI's menu; the UI format won't run.

Where: --url URL, --pod (the running POD_NAME pod's proxy URL), or
http://127.0.0.1:LOCAL_COMFY_PORT. The pod's password (POD_AUTH or AUTH_FILE)
is sent to *.proxy.runpod.net only.

Downloads never overwrite: an existing name gets -001, -002, ... Each file's
size is checked against what ComfyUI sent.
"""

import argparse
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import rp

UPLOAD_LIMIT = 100 * 1000 * 1000   # Cloudflare (RunPod's proxy) refuses bigger request bodies


class Comfy:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def request(self, path, data=None, headers=None, timeout=60, retries=3):
        h = {"User-Agent": rp.user_agent(), **rp.auth_headers(self.url), **(headers or {})}
        for attempt in range(retries):
            req = urllib.request.Request(self.url + path, data=data, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                if e.code == 401:
                    sys.exit("ERROR: the pod wants its password: set POD_AUTH or AUTH_FILE (project.conf)")
                if e.code < 500 or attempt + 1 == retries:
                    raise RuntimeError(f"{path}: HTTP {e.code}: {body[:500]}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt + 1 == retries:
                    raise RuntimeError(f"{self.url}{path}: {e}") from None
            time.sleep(3 * (attempt + 1))

    def json(self, path, payload=None, **kw):
        data = json.dumps(payload).encode() if payload is not None else None
        return json.loads(self.request(path, data, {"Content-Type": "application/json"} if data else None, **kw))

    def upload(self, path):
        path = Path(path)
        size = path.stat().st_size
        if size > UPLOAD_LIMIT and rp.is_pod_url(self.url):
            sys.exit(f"ERROR: {path} is {size / 1e6:.0f}MB; the proxy takes at most 100MB (resize, re-encode, "
                     "or copy it into the volume's input/ through the S3 gateway)")
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = b"".join([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n".encode(), path.read_bytes(),
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"type\"\r\n\r\ninput\r\n--{boundary}--\r\n".encode()])
        r = json.loads(self.request("/upload/image", body, {"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                    timeout=600, retries=1))
        return f"{r['subfolder']}/{r['name']}" if r.get("subfolder") else r["name"]


def resolve_url(args):
    if args.url:
        return args.url
    if args.pod:
        name = rp.conf("POD_NAME")
        for p in rp.rest("GET", "/pods", params={"name": name}) or []:
            if p.get("name") == name and p.get("desiredStatus") == "RUNNING":
                return rp.proxy_url(p["id"])
        sys.exit(f"ERROR: no running pod named {name}")
    return f"http://127.0.0.1:{rp.conf('LOCAL_COMFY_PORT', '8188')}"


def apply_sets(comfy, wf, sets):
    for item in sets:
        target, _, value = item.partition("=")
        node, _, inp = target.partition(".")
        if not _ or node not in wf:
            sys.exit(f"ERROR: --set {item!r}: no node {node!r} in the workflow (keys: {', '.join(wf)})")
        if value.startswith("@"):
            value = comfy.upload(value[1:])
            print(f"uploaded {item.split('@', 1)[1]} as {value}")
        else:
            try:
                value = json.loads(value)
            except ValueError:
                pass
        wf[node].setdefault("inputs", {})[inp] = value


def free_name(path):
    if not path.exists():
        return path
    for n in range(1, 1000):
        p = path.with_name(f"{path.stem}-{n:03d}{path.suffix}")
        if not p.exists():
            return p
    sys.exit(f"ERROR: too many copies of {path}")


def run(comfy, args):
    wf = json.loads(Path(args.workflow).read_text())
    if "nodes" in wf and "links" in wf:
        sys.exit("ERROR: that's a UI-format workflow; export it with Export (API)")
    apply_sets(comfy, wf, args.set)
    client = uuid.uuid4().hex
    r = comfy.json("/prompt", {"prompt": wf, "client_id": client}, retries=1)
    if r.get("node_errors"):
        sys.exit("ERROR: " + json.dumps(r["node_errors"], indent=1))
    pid = r["prompt_id"]
    print(f"queued {pid} (queue position {r.get('number')})")
    t0 = time.time()
    while True:
        hist = comfy.json(f"/history/{pid}").get(pid)
        if hist:   # a job only shows up in /history once it has finished (or failed)
            break
        if args.timeout and time.time() - t0 > args.timeout:
            sys.exit(f"ERROR: not done after {args.timeout} s (still queued or running on the server)")
        time.sleep(2)
    status = hist.get("status", {})
    if status.get("status_str") == "error":
        msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
        sys.exit("ERROR: " + (json.dumps(msgs[-1][1], indent=1)[:2000] if msgs else "execution failed"))
    print(f"done in {time.time() - t0:.0f} s")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for node_out in hist.get("outputs", {}).values():
        for items in node_out.values():
            if not isinstance(items, list):
                continue
            for f in items:
                if not isinstance(f, dict) or "filename" not in f or f.get("type") != "output":
                    continue
                q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                            "type": "output"})
                data = comfy.request(f"/view?{q}", timeout=600)
                dest = free_name(out / f["filename"])
                dest.write_bytes(data)
                if dest.stat().st_size != len(data) or not data:
                    sys.exit(f"ERROR: {dest}: short write")
                print(f"  {dest}  ({len(data) / 1e6:.1f}MB)" if len(data) >= 1e5 else f"  {dest}  ({len(data) / 1e3:.1f}KB)")
                n += 1
    if not n:
        print("  (no output files: does the workflow have a Save node?)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "run"])
    ap.add_argument("workflow", nargs="?", help="API-format workflow JSON (run)")
    ap.add_argument("--set", action="append", default=[], metavar="NODE.INPUT=VALUE")
    ap.add_argument("--out", default="results", help="download folder (default ./results)")
    ap.add_argument("--timeout", type=int, default=0, help="give up waiting after N s (default: wait)")
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--url")
    where.add_argument("--pod", action="store_true", help="the running pod (POD_NAME)")
    args = ap.parse_args()

    comfy = Comfy(resolve_url(args))
    try:
        if args.command == "status":
            s = comfy.json("/system_stats")
            print(f"{comfy.url}: ComfyUI {s['system'].get('comfyui_version')}, "
                  f"python {s['system'].get('python_version', '').split()[0]}, "
                  f"pytorch {s['system'].get('pytorch_version')}")
            for d in s.get("devices", []):
                print(f"  {d['name']}: {d['vram_free'] / 2**30:.1f} of {d['vram_total'] / 2**30:.1f} GiB free")
        else:
            if not args.workflow:
                ap.error("run needs a workflow")
            run(comfy, args)
    except RuntimeError as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
