# Krea 2 Turbo (int8)

Krea 2 Turbo text to image, int8 model, with the template's style LoRA.

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `image_krea2_turbo_t2i_int8`.

## Image

**cu130** for comfy-kitchen's int8 kernels; cu128 falls back to the eager path.

## GPU and volume

- 24GB is enough: an RTX 4090 pod ran Krea 2 Turbo.
- Volume: 19.5GB of models, so 30GB.

## Notes

- In that datacenter, the pod downloaded from Hugging Face at well under 1 MB/s. Fill the volume first with `tools/fill-volume.py` (another datacenter's pod) or from R2, rather than at boot.

## Start a project from it

```bash
tools/new-project.sh krea2 ../my-krea2
```

Then follow the README there (build, test locally, volume, pod).

## Status

Not yet built or run from this baseline: the model list, custom nodes and workflows come straight from the official templates; GPU advice is from the model sizes; an RTX 4090 ran Krea 2 in an earlier project.
