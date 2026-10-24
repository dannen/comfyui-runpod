# Wan 2.2 Animate 14B (character animation)

Wan 2.2 Animate: animate a reference character from a driving video, or replace a person in it, with the relight and lightx2v LoRAs.

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `video_wan2_2_14B_animate`.

## Image

cu128 is fine (fp8).

## GPU and volume

- 48GB recommended: the 18.4GB model, the 6.7GB text encoder, CLIP vision, plus pose/segmentation models and video latents.
- Volume: 29GB of models (the pose and segmentation packs fetch a few more on first use), so 40GB.

## Notes

- **Custom nodes:** KJNodes, segment-anything-2 and controlnet_aux, pinned in `custom_nodes.txt` to the commits the template was made with. The build fails if one doesn't import. Two of them import OpenCV, which needs libGL/libxcb; the baseline's Dockerfile installs those.
- An earlier attempt with a community Animate workflow stalled on a node pack nobody could identify; the official template avoids that. Run the template unchanged first, before adding community graphs.

## Start a project from it

```bash
tools/new-project.sh wan2.2-animate ../my-wan2.2-animate
```

Then follow the README there (build, test locally, volume, pod).

## Status

Image built from this baseline (cu128, 2026-10-24): all three packs import, and every node type in the template is registered (`tools/comfy.py check`). Not run with the models or on a pod yet; GPU advice is from the model sizes.
