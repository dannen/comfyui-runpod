"""Output Name From Image: a filename prefix taken from the image that was
loaded, so results are saved as <folder>/<photo>_<suffix>_00001.png instead of
ComfyUI_00001.png. Connect its output to a Save node's filename_prefix.

ComfyUI's Load Image node doesn't output its file name, and the frontend's
%Load Image.image% token keeps the extension. This node takes the image as an
input (so ComfyUI reruns it whenever the image changes; hidden inputs aren't
part of the cache key), follows that link back through the job to the Load
Image node, and uses its file name without folder or extension.
"""

import re
from pathlib import PurePosixPath


def _source_image_name(prompt, node_id):
    """File name of the Load Image node upstream of node_id, or None."""
    seen, todo = set(), [str(node_id)]
    while todo:
        nid = todo.pop(0)
        if nid in seen or nid not in prompt:
            continue
        seen.add(nid)
        node = prompt[nid]
        if node.get("class_type") == "LoadImage" and nid != str(node_id):
            return node.get("inputs", {}).get("image")
        for value in node.get("inputs", {}).values():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                todo.append(str(value[0]))
    return None


class OutputNameFromImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "Connect the Load Image output; its file name is used."}),
                "suffix": ("STRING", {"default": "result", "tooltip": "Added after the image's name."}),
                "folder": ("STRING", {"default": "", "tooltip": "Subfolder of ComfyUI's output folder."}),
            },
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filename_prefix",)
    FUNCTION = "name"
    CATEGORY = "utils"
    DESCRIPTION = "Filename prefix <folder>/<image>_<suffix>, from the image loaded by Load Image."

    def name(self, image, suffix, folder, prompt=None, unique_id=None):
        raw = _source_image_name(prompt or {}, unique_id) or "image"
        raw = re.sub(r"\s*\[[a-z]+\]$", "", str(raw))  # "photo.jpg [input]" annotations
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePosixPath(raw).stem).strip("_") or "image"
        parts = [p for p in (folder.strip("/"), f"{stem}_{suffix}" if suffix else stem) if p]
        return ("/".join(parts),)


NODE_CLASS_MAPPINGS = {"OutputNameFromImage": OutputNameFromImage}
NODE_DISPLAY_NAME_MAPPINGS = {"OutputNameFromImage": "Output Name From Image"}
