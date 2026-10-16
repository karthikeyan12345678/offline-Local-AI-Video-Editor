"""Image generation: any OpenAI-compatible images API, the free Pollinations web service, or a local Stable Diffusion model."""

from __future__ import annotations

import base64
import io
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

IMAGE_PROVIDERS: dict[str, dict[str, Any]] = {
    "pollinations": {"name": "Pollinations (free, online)", "needs_key": False, "base_url": "https://image.pollinations.ai", "model": "flux",
                     "help": "No account needed. Needs internet. Your prompt is sent to a public service."},
    "openai": {"name": "OpenAI-compatible API", "needs_key": True, "base_url": "https://api.openai.com/v1", "model": "gpt-image-1",
               "help": "OpenAI or any server with /images/generations (set the address, key and model)."},
    "local": {"name": "On this PC (Stable Diffusion Turbo)", "needs_key": False, "base_url": "", "model": "stabilityai/sd-turbo",
              "help": "Private and offline after a one-time ~2.5 GB download. Works on a 4 GB graphics card (slower on CPU)."},
}
SIZES = {"square": (1024, 1024), "landscape": (1280, 720), "portrait": (768, 1152)}


class ImageError(RuntimeError):
    pass


@dataclass
class ImageConfig:
    provider: str = "pollinations"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    local_dir: str = ""  # folder of the downloaded picture model, when the studio has installed it


def image_config_from(saved: dict[str, Any]) -> ImageConfig:
    prov = saved.get("provider", "pollinations")
    p = IMAGE_PROVIDERS.get(prov, IMAGE_PROVIDERS["pollinations"])
    mine = saved.get(prov, {}) if isinstance(saved.get(prov), dict) else {}
    return ImageConfig(prov, (mine.get("base_url") or p["base_url"]).rstrip("/"), mine.get("api_key", ""), mine.get("model") or p["model"])


def _check_image(data: bytes) -> tuple[bytes, tuple[int, int]]:
    from PIL import Image

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # noqa: BLE001 - any decoder failure means "not an image"
        raise ImageError("The service did not return a picture. It may be busy or may have refused the prompt. Try again or reword it.") from exc
    out = io.BytesIO()
    im.convert("RGBA" if im.mode in ("RGBA", "LA", "P") else "RGB").save(out, "PNG")
    return out.getvalue(), im.size


def slug(prompt: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40]
    return s or "image"


def _remote_openai(cfg: ImageConfig, prompt: str, size: tuple[int, int], seed: int | None) -> bytes:
    sizes = ["1024x1024", "1536x1024", "1024x1536"]
    ratio = size[0] / size[1]
    wanted = sizes[1] if ratio > 1.2 else sizes[2] if ratio < 0.85 else sizes[0]
    headers = {"content-type": "application/json"}
    if cfg.api_key:
        headers["authorization"] = f"Bearer {cfg.api_key}"
    body: dict[str, Any] = {"model": cfg.model, "prompt": prompt, "n": 1, "size": wanted}
    if cfg.model.startswith("dall-e"):
        body["response_format"] = "b64_json"
    try:
        r = httpx.post(cfg.base_url + "/images/generations", headers=headers, json=body, timeout=httpx.Timeout(180.0, connect=8.0))
    except httpx.ConnectError as exc:
        raise ImageError(f"Cannot reach the image server at {cfg.base_url}. Check the address in Settings and your connection.") from exc
    except httpx.HTTPError as exc:
        raise ImageError(f"The image server did not answer in time: {exc}") from exc
    if r.status_code in (401, 403):
        raise ImageError("The image service did not accept the API key. Check it in Settings.")
    if r.status_code == 429:
        raise ImageError("The image service says you have hit its limit. Wait and retry.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            msg = r.text[:200]
        raise ImageError(f"The image service refused the request ({r.status_code}). {msg}".strip())
    try:
        item = r.json()["data"][0]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ImageError("The image service sent an answer this app does not understand.") from exc
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        try:
            return httpx.get(item["url"], timeout=60.0, follow_redirects=True).content
        except httpx.HTTPError as exc:
            raise ImageError("The picture was made but could not be downloaded.") from exc
    raise ImageError("The image service returned no picture.")


def _pollinations(cfg: ImageConfig, prompt: str, size: tuple[int, int], seed: int | None) -> bytes:
    q = {"width": size[0], "height": size[1], "nologo": "true", "model": cfg.model or "flux"}
    if seed is not None:
        q["seed"] = seed
    url = f"{cfg.base_url or 'https://image.pollinations.ai'}/prompt/{urllib.parse.quote(prompt, safe='')}?{urllib.parse.urlencode(q)}"
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = httpx.get(url, timeout=httpx.Timeout(120.0, connect=8.0), follow_redirects=True)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 + attempt * 3)
                last = ImageError(f"The free service is busy ({r.status_code}).")
                continue
            if r.status_code >= 400:
                raise ImageError(f"The free image service refused the request ({r.status_code}).")
            return r.content
        except httpx.HTTPError as exc:
            last = exc
    if isinstance(last, ImageError):
        raise ImageError(str(last) + " Try again in a minute, or switch to another image engine in Settings.")
    raise ImageError("Cannot reach the free image service. Check your internet connection, or use the on-this-PC engine in Settings.") from last


_local_pipe: Any = None


def local_available() -> tuple[bool, str]:
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False, "The on-this-PC image engine needs PyTorch, which is included in LTX Portable Studio but not in this app. Choose the free online engine or your own API here."
    return True, ""


def _local(cfg: ImageConfig, prompt: str, size: tuple[int, int], seed: int | None, hf_endpoint: str = "") -> bytes:
    global _local_pipe
    ok, why = local_available()
    if not ok:
        raise ImageError(why)
    import torch
    from diffusers import AutoPipelineForText2Image

    cuda = torch.cuda.is_available()
    if _local_pipe is None:
        import os

        if hf_endpoint:
            os.environ.setdefault("HF_ENDPOINT", hf_endpoint)
        try:
            if cfg.local_dir and Path(cfg.local_dir).exists():
                pipe = AutoPipelineForText2Image.from_pretrained(cfg.local_dir, torch_dtype=torch.float16 if cuda else torch.float32, variant="fp16", local_files_only=True)
            else:
                pipe = AutoPipelineForText2Image.from_pretrained(cfg.model or "stabilityai/sd-turbo", torch_dtype=torch.float16 if cuda else torch.float32,
                                                                 variant="fp16" if cuda else None)
        except Exception as exc:  # noqa: BLE001
            raise ImageError("The local image model could not be loaded. If this is the first use it needs a one-time download: check your internet connection and free disk space (about 3 GB).") from exc
        if cuda:
            pipe.enable_model_cpu_offload()  # keeps peak memory low enough for a 4 GB card
            pipe.enable_attention_slicing()
            pipe.enable_vae_slicing()
        _local_pipe = pipe
    w = min(768, max(256, size[0] // 64 * 64 // (2 if size[0] > 768 else 1)))
    h = min(768, max(256, size[1] // 64 * 64 // (2 if size[1] > 768 else 1)))
    gen = torch.Generator("cuda" if cuda else "cpu").manual_seed(seed if seed is not None else int(time.time()) % 2**31)
    try:
        img = _local_pipe(prompt, num_inference_steps=2, guidance_scale=0.0, width=w, height=h, generator=gen).images[0]
    except torch.cuda.OutOfMemoryError as exc:  # type: ignore[attr-defined]
        torch.cuda.empty_cache()
        raise ImageError("The graphics card ran out of memory. Pick the square size or close other programs.") from exc
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def generate_image(cfg: ImageConfig, prompt: str, out_dir: Path, shape: str = "square", seed: int | None = None, hf_endpoint: str = "") -> dict[str, Any]:
    prompt = prompt.strip()
    if len(prompt) < 3:
        raise ImageError("Describe the picture you want, for example “a lighthouse at sunset, watercolor”.")
    if len(prompt) > 1500:
        raise ImageError("That description is too long. Keep it under about 1,500 characters.")
    size = SIZES.get(shape, SIZES["square"])
    fn: Callable[..., bytes]
    if cfg.provider == "openai":
        if not cfg.base_url:
            raise ImageError("No image server address is set. Open Settings.")
        raw = _remote_openai(cfg, prompt, size, seed)
    elif cfg.provider == "local":
        raw = _local(cfg, prompt, size, seed, hf_endpoint)
    else:
        raw = _pollinations(cfg, prompt, size, seed)
    png, real = _check_image(raw)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(prompt)}.png"
    n = 2
    while path.exists():
        path = out_dir / f"{path.stem.rsplit('~', 1)[0]}~{n}.png"
        n += 1
    path.write_bytes(png)
    return {"path": str(path), "name": path.name, "width": real[0], "height": real[1], "prompt": prompt, "provider": cfg.provider, "bytes": len(png)}
