# Marigold V2 (depth, normals, albedo)

Marigold V2 dense prediction from one photo: depth, surface normals and albedo (three LoRAs on one shared 20.5GB backbone).

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `image_marigold_v2_depth_estimation`, `image_marigold_v2_surface_normal_estimation`, `image_marigold_v2_albedo_estimation`.

## Image

Either. cu130 uses comfy-kitchen's int8 kernels; cu128's eager fallback gave depth maps within ~1% of cu130's, and ran on a 16GB local card through ComfyUI's dynamic VRAM loading (2496 px in 24 s on an RTX 4060 Ti). Needs ComfyUI >= v0.36.0.

## GPU and volume

- 24GB is enough: ~20 GiB of weights, plus about 0.5 GiB per job at 2496 px and at most 1.8 GiB up to ~3500 px. 48GB fits up to ~4600 px.
- Prefer a cheap card: jobs take seconds (1.3 s at 1168 px, ~5 s at 2500 px, 13 s at 3500 px on an L40S).
- Volume: 26.4GB of models, so 30GB.

## Notes

- **Size:** quality is best at about a 2500 px long edge; it falls off between 2500 and 3750 px (out-of-focus areas lose separation, flat areas get banding). Panoramas: ~4000 px.
- Resize to sides that are multiples of 16 before the model, so the map has exactly the photo's shape.
- First job after boot: ~2 min to load the backbone from the volume; switching between depth, normals and albedo: 30-45 s.
- Crop film-scan borders first: a black frame comes out as the nearest surface.
- Save the map as a 32-bit EXR; never put ComfyUI's lanczos resize (8-bit PIL) after the model.

## Start a project from it

```bash
tools/new-project.sh marigold-v2 ../my-marigold-v2
```

Then follow the README there (build, test locally, volume, pod).

## Status

Not yet built or run from this baseline: the model list, custom nodes and workflows come straight from the official templates; GPU advice is from the model sizes; the numbers are from an earlier project that ran these templates on L40S, A40, RTX PRO 6000 MIG and a local 16GB card.
