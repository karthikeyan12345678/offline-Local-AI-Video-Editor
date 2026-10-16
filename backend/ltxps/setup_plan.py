"""The one-click "install everything that suits this PC" plan. Pure logic, so it is easy to test."""

from __future__ import annotations

from typing import Any

from .catalog import APPROX_BYTES, AUX, BASE_ID, MODELS


def build_plan(*, ram_gb: float, vram_gb: float, gpu_ok: bool, disk_free_gb: float, default_model: str, is_installed, want_images: bool = True, gpu_name: str = "", gpu_usable: bool | None = None, torch_version: str | None = None, sizes: dict[str, int] | None = None) -> dict[str, Any]:
    """Choose the best set of downloads for this computer.

    - Video model: the fast distilled one is the best all-round choice and the only one that fits small cards.
    - Captions: "small" understands Tamil, Hindi and other languages best, so it is used when there is enough memory.
    - Pictures: Stable Diffusion Turbo, the smallest good model; fast on a graphics card, slower on the processor.
    """
    model = default_model if default_model in MODELS else "ltxv-2b-distilled"
    whisper = "whisper-small" if ram_gb >= 12 else "whisper-base"
    rows = [
        (BASE_ID, "Video brain (text understanding)", "Lets the video maker understand your words. Needed for every video."),
        (model, MODELS[model].label, "The video maker itself." + (" Picked because it is fast and fits your graphics card." if gpu_ok else " Your PC has no supported graphics card, so videos will be slow.")),
        (whisper, AUX[whisper].label, "Listens to speech and writes captions" + (" in Tamil, Hindi and many languages." if whisper == "whisper-small" else ". Picked because it is light for your memory.")),
    ]
    if want_images:
        rows.append(("image-sd-turbo", AUX["image-sd-turbo"].label, "Draws pictures from words (AI Assistant → Images)." + ("" if gpu_ok else " Slower on this PC because it has no graphics card.")))
    if want_images and gpu_ok:
        rows.append(("image-inpaint", AUX["image-inpaint"].label, "Lets the chat editor remove, change or add things inside your video (a hill, a person, a cap, shoes)."))
    real = sizes or {}
    items = [{"id": i, "label": label, "why": why, "approx_bytes": real.get(i) or APPROX_BYTES.get(i, 0), "size_known": i in real, "installed": bool(is_installed(i))} for i, label, why in rows]
    missing = sum(x["approx_bytes"] for x in items if not x["installed"])
    need_gb = missing / 1024**3 * 1.15
    usable = gpu_ok if gpu_usable is None else gpu_usable
    gpu = {"name": gpu_name, "vram_gb": vram_gb, "present": bool(gpu_name or vram_gb), "usable": bool(usable and gpu_ok),
           "needs_gpu_build": bool((gpu_name or vram_gb) and not usable)}
    engine = {"installed": bool(torch_version), "version": torch_version or "", "kind": "gpu" if gpu["usable"] else ("cpu" if torch_version else "")}
    summary = (f"{gpu_name or 'Graphics card'} · {vram_gb} GB" if gpu["present"] else "No graphics card") + f" · {ram_gb} GB memory"
    return {"items": items, "gpu": gpu, "engine": engine, "missing_bytes": missing, "disk_free_gb": disk_free_gb, "enough_disk": disk_free_gb >= need_gb,
            "need_gb": round(need_gb, 1), "summary": summary}
