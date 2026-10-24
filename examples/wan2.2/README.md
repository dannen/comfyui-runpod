# Wan 2.2 14B (text and image to video)

Wan 2.2 A14B text to video and image to video: a high-noise and a low-noise expert per task (fp8), with the 4-step lightx2v LoRAs the templates can switch on.

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `video_wan2_2_14B_t2v`, `video_wan2_2_14B_i2v`.

## Image

cu128 is fine (fp8).

## GPU and volume

- The two 14.3GB experts run one after the other, so one at a time needs to fit: 24GB works with offloading, 48GB is comfortable at 720p.
- Volume: 69GB of models (both tasks), so 90GB. Drop the t2v or i2v lines to halve it.

## Notes

- Not run in an earlier project. Measure VRAM and time at your resolution and length first (DESIGN.md section 7).

## Start a project from it

```bash
tools/new-project.sh wan2.2 ../my-wan2.2
```

Then follow the README there (build, test locally, volume, pod).

## Status

Not yet built or run from this baseline: the model list, custom nodes and workflows come straight from the official templates; GPU advice is from the model sizes.
