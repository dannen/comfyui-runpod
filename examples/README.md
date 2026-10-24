# Examples

Starting points for common model families, each made from ComfyUI's official
workflow templates. An example holds a `models.txt` (URLs, folders, sizes,
SHA-256s), a `custom_nodes.txt` (pinned to the commits the templates were made
with), the templates themselves in `workflows/`, its `project.conf` values
(`example.conf`), and a README with the GPU, volume and image advice, plus what
earlier projects learned running that model.

| Example | What | Models | Volume | Custom node packs |
|---|---|---|---|---|
| [`flux1`](flux1/README.md) | FLUX.1 (schnell + dev) | 51.41GB | 60GB | none |
| [`krea2`](krea2/README.md) | Krea 2 Turbo (int8) | 19.46GB | 30GB | none |
| [`ltx-2.3`](ltx-2.3/README.md) | LTX-2.3 (text and image to video) | 42.96GB | 60GB | none |
| [`marigold-v2`](marigold-v2/README.md) | Marigold V2 (depth, normals, albedo) | 26.38GB | 30GB | none |
| [`minimax-h3`](minimax-h3/README.md) | MiniMax H3 (text, image and reference to video) | 64.96GB | 80GB | none |
| [`qwen-image`](qwen-image/README.md) | Qwen-Image 2.1 (text to image, edit, background removal) | 36.23GB | 50GB | none |
| [`wan2.2`](wan2.2/README.md) | Wan 2.2 14B (text and image to video) | 69.07GB | 90GB | none |
| [`wan2.2-animate`](wan2.2-animate/README.md) | Wan 2.2 Animate 14B (character animation) | 28.83GB | 40GB | 3 |

## Use one

```bash
tools/new-project.sh --list
tools/new-project.sh wan2.2 ../my-wan      # the baseline + this example, in a new folder
```

Trim before you build: drop `models.txt` lines for templates you won't use (the
comment above each line names the templates that load it), and their workflows.

## Make or refresh one

```bash
tools/template-models.py <template> [<template> ...] --ref <workflow_templates commit> --write examples/<name>
```

Template names are the file names (without `.json`) in
[Comfy-Org/workflow_templates/templates](https://github.com/Comfy-Org/workflow_templates/tree/main/templates);
a local workflow file works too. Pin `--ref` to a commit so the lists can be
regenerated exactly. Then write `example.conf` and `README.md` by hand.

## Status

Checked 2026-10-24: every node type in all 17 workflows is registered in the
baseline's ComfyUI (v0.41.3), and the wan2.2-animate image (the one example
with custom nodes) builds with all its packs importing. None has been run with
its models or on a pod yet. The lists are only as right as the templates:
check the first boot's log and ComfyUI's missing-model warnings, and run
`tools/comfy.py check workflows/*.json` against your image.

The workflow files are Comfy-Org's, from
[workflow_templates](https://github.com/Comfy-Org/workflow_templates) (MIT
license). The models have their own licenses: check each model card.
