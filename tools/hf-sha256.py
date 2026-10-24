#!/usr/bin/env python3
"""Fill in models.txt's sha256 column from Hugging Face, and print sizes.

    hf-sha256.py                 show size + SHA-256 for every Hugging Face line
    hf-sha256.py --write         also add missing SHA-256s to models.txt (existing ones are compared, not replaced)

HF answers a HEAD on .../resolve/... with a redirect whose X-Linked-Etag is the
file's SHA-256 and X-Linked-Size its size, so nothing is downloaded. HF_TOKEN
is sent for gated repos (to huggingface.co only).
"""

import argparse
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import rp


def human(n):
    return f"{n / 1e9:6.2f}GB" if n >= 1e8 else f"{n / 1e6:6.1f}MB"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def head(url):
    headers = {"User-Agent": rp.user_agent()}
    if os.environ.get("HF_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
    for _ in range(5):
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        try:
            r = urllib.request.build_opener(NoRedirect).open(req, timeout=30)
        except urllib.error.HTTPError as e:   # the redirects land here
            r = e
        # A renamed repo answers with a relative redirect to its new name first; the
        # redirect to the file's storage (the one with X-Linked-Etag) comes after it.
        loc = r.headers.get("Location", "")
        if r.status in (301, 302, 307, 308) and not r.headers.get("X-Linked-Etag") and loc.startswith("/"):
            url = urllib.parse.urljoin(url, loc)
            continue
        break
    sha =(r.headers.get("X-Linked-Etag") or r.headers.get("ETag") or "").strip('"').removeprefix("W/").strip('"')
    size = r.headers.get("X-Linked-Size") or r.headers.get("Content-Length")
    return r.status, sha if len(sha) == 64 else "", int(size) if size else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", nargs="?", default=str(rp.ROOT / "models.txt"))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    lines = open(args.manifest).read().splitlines()
    total, bad = 0, 0
    for i, line in enumerate(lines):
        parts = line.split()
        if not parts or line.lstrip().startswith("#") or len(parts) < 2:
            continue
        subdir, url, have = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
        if "huggingface.co/" not in url:
            print(f"  {'?':>8}  {subdir}/{url.rsplit('/', 1)[-1]}  (not Hugging Face: add its SHA-256 by hand)")
            continue
        status, sha, size = head(url)
        total += size
        name = f"{subdir}/{url.split('?')[0].rsplit('/', 1)[-1]}"
        if status >= 400 or not sha:
            print(f"  ERROR {name}: HTTP {status}{' (gated? set HF_TOKEN)' if status in (401, 403) else ''}, no SHA-256")
            bad += 1
            continue
        note = ""
        if have and have != sha:
            note, bad = f"  MISMATCH: models.txt has {have}", bad + 1
        elif not have and args.write:
            lines[i] = f"{subdir} {url} {sha}"
            note = "  (written)"
        print(f"  {human(size)}  {name}  {sha}{note}")
    print(f"  {human(total)}  total")
    if args.write:
        open(args.manifest, "w").write("\n".join(lines) + "\n")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
