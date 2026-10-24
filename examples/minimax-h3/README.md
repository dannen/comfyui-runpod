# MiniMax H3 (text, image and reference to video)

MiniMax H3 video with audio: text to video and image to video (FL2VA model) and reference to video (Ref2VA model), with their turbo LoRAs.

Templates (in `workflows/`, from [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates)): `video_minimax_h3_t2v`, `video_minimax_h3_i2v`, `video_minimax_h3_r2v`.

## Image

**cu130**: the int8_convrot models and the nvfp4 text encoder use comfy-kitchen's CUDA kernels (nvfp4 is fastest on Blackwell). cu128 works through the slower fallback.

## GPU and volume

- 80-96GB: a 21GB video model, the 15.7GB Qwen3-VL-32B text encoder (nvfp4), VAEs, and long video latents. An earlier setup chose an RTX PRO 6000 (96GB).
- Volume: 65GB of models (both models), so 80GB.

## Notes

- Comfy-Org's repo also has an int8 text encoder (27GB) and an fp16 video VAE (5.2GB) that some community workflows load; add them only if a workflow asks.
- Community fine-tunes and extra LoRAs for H3 add up fast (an earlier volume reached 160GB): size the volume for what you will actually load.

## Start a project from it

```bash
tools/new-project.sh minimax-h3 ../my-minimax-h3
```

Then follow the README there (build, test locally, volume, pod).

## Status

Not yet built or run from this baseline: the model list, custom nodes and workflows come straight from the official templates; GPU advice is from the model sizes.
