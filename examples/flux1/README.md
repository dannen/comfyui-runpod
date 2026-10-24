# FLUX.1 (schnell + dev)

Text to image with FLUX.1 [schnell] (4 steps) and FLUX.1 [dev].

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `flux_schnell`, `flux_dev_checkpoint_example`.

## Image

cu128 is fine (fp8 and bf16 weights, no comfy-kitchen kernels needed).

## GPU and volume

- schnell: the fp8 checkpoint (17GB, model + text encoders + VAE in one file) fits a 24GB card.
- dev: the template loads the bf16 model (24GB) plus T5 in fp16 (10GB): 48GB is comfortable. On 24GB, ComfyUI offloads and gets slower; or swap in an fp8 dev model.
- Volume: 51GB of models, so 60GB.

## Notes

- **Licenses differ:** FLUX.1 [schnell] is Apache-2.0; FLUX.1 [dev] is under a non-commercial license. Drop the dev lines from `models.txt` if that matters.
- An earlier pod ran FLUX.1 on an older torch/CUDA stack without trouble; nothing model-specific needed patching.

## Start a project from it

```bash
tools/new-project.sh flux1 ../my-flux1
```

Then follow the README there (build, test locally, volume, pod).

## Status

Not yet built or run from this baseline: the model list, custom nodes and workflows come straight from the official templates; GPU advice is from the model sizes.
