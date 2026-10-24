# Qwen-Image 2.1 (text to image, edit, background removal)

Qwen-Image 2.1: text to image, multi-reference image editing, and RGBA output (background removal), with the optional prompt enhancers.

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `image_qwen_image_2_1_t2i`, `image_qwen_image_2_1_image_edit`, `image_qwen_image_2_1_background_removal`.

## Image

Its int8_convrot weights run fastest on the **cu130** image (comfy-kitchen's CUDA kernels; CUDA 13 hosts). cu128 works through the slower eager fallback.

## GPU and volume

- 24GB works: an RTX 4090 pod ran all three templates.
- 48GB if you use the prompt enhancer: it loads a second ~9.5GB LLM next to the 7.3GB model and the 9.4GB text encoder.
- Volume: 36GB of models, so 50GB.

## Notes

- With the CUDA 13 filter on, the 48GB cards were often out of stock; the 4090 had stock.
- Transparent output: start the prompt with "This is an RGBA image with transparency." and end it with "The image has alpha channel and the background is transparent."
- Comfy-Org's repo also has bf16 weights (14.2GB model, 17.5GB encoder) for 48GB+ cards.

## Start a project from it

```bash
tools/new-project.sh qwen-image ../my-qwen-image
```

Then follow the README there (build, test locally, volume, pod).

## Status

Not yet built or run from this baseline: the model list, custom nodes and workflows come straight from the official templates; GPU advice is from the model sizes; an RTX 4090 ran these templates in an earlier project.
