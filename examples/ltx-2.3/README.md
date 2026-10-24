# LTX-2.3 (text and image to video)

LTX-2.3 22B video with audio: text to video and image to video, two-stage with the x2 spatial upscaler and the distilled LoRA.

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `video_ltx2_3_t2v`, `video_ltx2_3_i2v`.

## Image

cu128 is fine (fp8 checkpoint).

## GPU and volume

- 48GB: the fp8 checkpoint is 29GB, the Gemma 3 12B text encoder 9.5GB, plus the upscaler and activations for long or large clips.
- 80GB for longer clips at high resolution.
- Volume: 43GB of models, so 60GB (outputs are videos).

## Notes

- An earlier setup ran LTX-2.3 as a **serverless** endpoint on GGUF weights (Q8, 23GB, on 48GB; bf16 at 42GB was too tight). It needed several patches to custom node packs and a handler patch for video outputs, and serverless silently dropped outputs above its payload limit. On a pod with the official template (core nodes only), none of that applies.
- Outputs are big: pull them with `tools/comfy.py` or through the S3 gateway.

## Start a project from it

```bash
tools/new-project.sh ltx-2.3 ../my-ltx-2.3
```

Then follow the README there (build, test locally, volume, pod).

## Status

Not yet built or run from this baseline: the model list, custom nodes and workflows come straight from the official templates; GPU advice is from the model sizes.
