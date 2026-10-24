#!/usr/bin/env python3
"""models.txt and custom_nodes.txt lines from official ComfyUI workflow templates.

    template-models.py flux_schnell video_wan2_2_14B_i2v
    template-models.py video_ltx2_3_i2v --workflows workflows/ --ref <commit>
    template-models.py ./my-workflow.json --no-sha

Each template (a name from github.com/Comfy-Org/workflow_templates/tree/main/templates,
without .json, or a local workflow file) lists the model files its loaders need, with
their URLs and folders, and the custom node packs it uses, with the commit the
template was made with. This prints:

  - models.txt lines (deduplicated, with sizes and Hugging Face's SHA-256s);
  - custom_nodes.txt lines: the pack's GitHub repo (from the Comfy Registry) and
    the commit the template names; with several commits of one pack, the newest.

--workflows DIR also saves the templates there (UI format, for the Workflows
sidebar). --write DIR writes DIR/models.txt and DIR/custom_nodes.txt (replacing
them) and saves the templates to DIR/workflows/, which is how examples/ is made. --ref pins the template repo to a commit or tag, so a project can
be rebuilt with the same templates later. Nothing is downloaded but the
templates' JSON and HTTP HEAD requests.
"""

import argparse
import importlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import rp

hf = importlib.import_module("hf-sha256")
RAW = "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/{ref}/templates/{name}.json"
REGISTRY = "https://api.comfy.org/nodes/{id}"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": rp.user_agent(), "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def load(template, ref):
    path = Path(template)
    if path.suffix == ".json" and path.is_file():
        return path.stem, json.loads(path.read_text())
    name = template.removesuffix(".json")
    try:
        return name, get_json(RAW.format(ref=ref, name=urllib.parse.quote(name)))
    except urllib.error.HTTPError as e:
        sys.exit(f"ERROR: template {name!r} at {ref}: HTTP {e.code} (names: github.com/Comfy-Org/workflow_templates)")


def nodes(wf):
    yield from wf.get("nodes") or []
    for sg in (wf.get("definitions") or {}).get("subgraphs") or []:
        yield from sg.get("nodes") or []


def repo_for(cnr_id, cache={}):
    """GitHub URL of a Comfy Registry pack id (ids are case-sensitive; lower case is tried too)."""
    if cnr_id not in cache:
        cache[cnr_id] = None
        for i in dict.fromkeys((cnr_id, cnr_id.lower())):
            try:
                cache[cnr_id] = get_json(REGISTRY.format(id=urllib.parse.quote(i))).get("repository")
                break
            except (urllib.error.URLError, ValueError):
                continue
    return cache[cnr_id]


def newest(repo, shas):
    """The most recent of several commits, by committer date (GitHub API, unauthenticated)."""
    m = re.match(r"https://github\.com/([^/]+/[^/.]+)", repo or "")
    if not m or len(shas) == 1:
        return sorted(shas)[0], False
    dated = []
    for sha in shas:
        try:
            date = get_json(f"https://api.github.com/repos/{m.group(1)}/commits/{sha}")["commit"]["committer"]["date"]
        except (urllib.error.URLError, KeyError, ValueError):
            return sorted(shas)[0], True
        dated.append((date, sha))
    return max(dated)[1], False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("templates", nargs="+")
    ap.add_argument("--ref", default="main", help="workflow_templates commit, tag or branch (default main)")
    ap.add_argument("--workflows", metavar="DIR", help="also save the templates here")
    ap.add_argument("--no-sha", action="store_true", help="skip the HEAD requests (no sizes or SHA-256s)")
    ap.add_argument("--write", metavar="DIR", help="write DIR/models.txt, DIR/custom_nodes.txt, DIR/workflows/")
    args = ap.parse_args()
    if args.write and not args.workflows:
        args.workflows = str(Path(args.write) / "workflows")

    models, packs, problems, core = {}, {}, [], set()
    for t in args.templates:
        name, wf = load(t, args.ref)
        if args.workflows:
            out = Path(args.workflows)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{name}.json").write_text(json.dumps(wf, indent=1) + "\n")
        for n in nodes(wf):
            props = n.get("properties") or {}
            for m in props.get("models") or []:
                if not m.get("url") or not m.get("directory"):
                    continue
                url = m["url"].split("?")[0]
                base = url.rsplit("/", 1)[-1]
                if m.get("name") and m["name"] != base:
                    problems.append(f"{m['name']}: the URL's file is {base} (rename it after download)")
                models.setdefault((m["directory"], url), set()).add(name)
            cnr, ver = props.get("cnr_id"), props.get("ver")
            if cnr == "comfy-core" and re.fullmatch(r"\d+\.\d+\.\d+", ver or ""):
                core.add(tuple(int(x) for x in ver.split(".")))
            if cnr and cnr != "comfy-core":
                packs.setdefault(cnr, set()).add(ver or "")

    src = f"{', '.join(args.templates)} (Comfy-Org/workflow_templates @ {args.ref})"
    need = "v" + ".".join(map(str, max(core))) if core else None
    mlines = [f"# Generated by tools/template-models.py from: {src}",
              *([f"# The templates were saved with ComfyUI {need}: COMFYUI_REF must be at least that."] if need else []),
              "# Format: <models/ subdir> <url> [sha256]. Comments: size; the templates that load the file.", ""]
    total = 0
    for (directory, url), users in sorted(models.items()):
        sha, note = "", ""
        if not args.no_sha and "huggingface.co/" in url:
            status, sha, size = hf.head(url)
            total += size
            note = f"{hf.human(size).strip()}" if status < 400 else f"HTTP {status}{', gated: HF_TOKEN' if status in (401, 403) else ''}"
        mlines += [f"# {note}{'; ' if note else ''}{', '.join(sorted(users))}", f"{directory} {url}{' ' + sha if sha else ''}"]
    if total:
        mlines += ["", f"# total {hf.human(total).strip()}"]

    nlines = [f"# Generated by tools/template-models.py from: {src}",
              "# Format: <git url> <full commit sha or tag>: the commits the templates were made with.", ""]
    if not packs:
        nlines.append("# none: these templates use core nodes only")
    for cnr, vers in sorted(packs.items()):
        repo = repo_for(cnr)
        shas = {v for v in vers if re.fullmatch(r"[0-9a-f]{40}", v)}
        if not repo:
            nlines.append(f"# {cnr}: not in the Comfy Registry; find its repo by hand")
        elif shas:
            pick, unsure = newest(repo, shas)
            extra = f"templates use {len(shas)} commits; {'newest unknown' if unsure else 'the newest'}" if len(shas) > 1 else ""
            if extra:
                nlines.append(f"# {extra}")
            nlines.append(f"{repo} {pick}")
        else:
            nlines.append(f"# {repo}  registry version(s) {', '.join(sorted(v for v in vers if v)) or '?'}: pin a full commit sha")

    if args.write:
        out = Path(args.write)
        (out / "models.txt").write_text("\n".join(mlines) + "\n")
        (out / "custom_nodes.txt").write_text("\n".join(nlines) + "\n")
        print(f"wrote {out}/models.txt ({len(models)} files{', ' + hf.human(total).strip() if total else ''}), "
              f"{out}/custom_nodes.txt ({len(packs)} packs), {args.workflows}/ ({len(args.templates)} workflows)"
              + (f"; needs ComfyUI >= {need}" if need else ""))
    else:
        print("\n".join(mlines) + "\n\n" + "\n".join(nlines))
    for p in problems:
        print(f"# NOTE {p}", file=sys.stderr)


if __name__ == "__main__":
    main()
