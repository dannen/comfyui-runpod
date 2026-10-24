"""Shared helpers for the tools in this folder: project.conf, the RunPod API
key, REST and GraphQL calls, and the pod password.

Standard library only, so every tool runs with a bare python3.
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REST_BASE = "https://rest.runpod.io/v1"
GRAPHQL_URL = "https://api.runpod.io/graphql"
KEY_FILE = "~/.api/runpod/api.key"
TOML_FILE = "~/.runpod/config.toml"
S3_CREDENTIALS = "~/.api/runpod/s3-credentials"


# ---------------------------------------------------------------- config

def _parse_conf(path):
    """KEY=value lines of a project.conf-style file, as a dict. Read, never executed."""
    out = {}
    for n, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            sys.exit(f"ERROR: {path}:{n}: not KEY=value: {line}")
        key, val = (s.strip() for s in line.split("=", 1))
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        val = re.sub(r"^~(?=/|$)", str(Path.home()), val)
        val = val.replace("${HOME}", str(Path.home())).replace("$HOME", str(Path.home()))
        out[key] = val
    return out


_conf = None


def conf(key, default=""):
    """A setting: the environment, then project.local.conf, then project.conf."""
    global _conf
    if _conf is None:
        _conf = {}
        for name in ("project.conf", "project.local.conf"):
            if (ROOT / name).is_file():
                _conf.update(_parse_conf(ROOT / name))
    return os.environ.get(key) or _conf.get(key) or default


def conf_list(key, default=""):
    return [s.strip() for s in conf(key, default).split(",") if s.strip()]


def user_agent():
    return f"{conf('PROJECT', 'comfyui-runpod')}-tools/1.0"


# ---------------------------------------------------------------- credentials

def api_key():
    """RUNPOD_API_KEY, else the file in RUNPOD_KEY_FILE (default ~/.api/runpod/api.key),
    else runpodctl's config.toml."""
    key = os.environ.get("RUNPOD_API_KEY", "").strip()
    key_file = conf("RUNPOD_KEY_FILE", KEY_FILE)
    if not key:
        path = Path(key_file).expanduser()
        if path.is_file():
            key = path.read_text().strip()
    if not key:
        path = Path(TOML_FILE).expanduser()
        if path.is_file():
            m = re.search(r'apikey\s*=\s*"(.+?)"', path.read_text())
            key = m.group(1) if m else ""
    if not key:
        sys.exit(f"ERROR: no RunPod API key: set RUNPOD_API_KEY or create {key_file} (mode 600)")
    return key


def s3_credentials():
    """(access key, secret) for RunPod's S3 gateway: AWS_* env, else the file in
    S3_CREDENTIALS_FILE (default ~/.api/runpod/s3-credentials)."""
    kid, secret = os.environ.get("AWS_ACCESS_KEY_ID"), os.environ.get("AWS_SECRET_ACCESS_KEY")
    if kid and secret:
        return kid, secret
    path = Path(conf("S3_CREDENTIALS_FILE", S3_CREDENTIALS)).expanduser()
    if path.is_file():
        text = path.read_text()
        kid = re.search(r"aws_access_key_id\s*=\s*(\S+)", text)
        secret = re.search(r"aws_secret_access_key\s*=\s*(\S+)", text)
        if kid and secret:
            return kid.group(1), secret.group(1)
    sys.exit("ERROR: no S3 credentials: set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or create "
             + conf("S3_CREDENTIALS_FILE", S3_CREDENTIALS))


def pod_auth():
    """user:password for the pod's nginx, from POD_AUTH or the file in AUTH_FILE; None if unset."""
    auth = os.environ.get("POD_AUTH", "").strip()
    if not auth and conf("AUTH_FILE"):
        try:
            auth = Path(conf("AUTH_FILE")).expanduser().read_text().strip()
        except OSError:
            auth = ""
    return auth if ":" in auth else None


def is_pod_url(url):
    p = urllib.parse.urlsplit(url)
    return p.scheme == "https" and (p.hostname or "").endswith(".proxy.runpod.net")


def auth_headers(url):
    """Basic auth for the pod's proxy URLs only: the password never goes anywhere else."""
    auth = pod_auth()
    if not auth or not is_pod_url(url):
        return {}
    return {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()}


def proxy_url(pod_id, port=8188):
    return f"https://{pod_id}-{port}.proxy.runpod.net"


# ---------------------------------------------------------------- RunPod API

class ApiError(RuntimeError):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def _request(req, timeout, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code >= 500 and attempt + 1 < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise ApiError(f"{req.get_method()} {req.full_url} -> HTTP {e.code}: {detail[:400]}", e.code) from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt + 1 < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise ApiError(f"{req.get_method()} {req.full_url}: {e}") from None


def rest(method, path, body=None, params=None, timeout=30):
    url = REST_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        url, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}",
                 "User-Agent": user_agent()})
    # Only GETs are retried on 5xx: a POST that timed out may have created the pod anyway.
    return _request(req, timeout, retries=3 if method == "GET" else 1)


def graphql(query, variables=None, timeout=60):
    """data of a GraphQL call; raises ApiError with the first error message."""
    payload = {"query": query, **({"variables": variables} if variables else {})}
    req = urllib.request.Request(
        GRAPHQL_URL, method="POST", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}",
                 "User-Agent": user_agent()})   # no User-Agent -> 403 from Cloudflare
    r = _request(req, timeout, retries=1)
    if r.get("errors"):
        raise ApiError("GraphQL: " + (r["errors"][0].get("message") or json.dumps(r["errors"])[:300]))
    return r.get("data") or {}


if __name__ == "__main__":
    # For the shell scripts: `python3 tools/rp.py conf KEY [DEFAULT]` prints one setting,
    # so the config is parsed in one place only.
    if len(sys.argv) in (3, 4) and sys.argv[1] == "conf":
        print(conf(sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else ""))
    else:
        sys.exit("usage: rp.py conf KEY [DEFAULT]")
