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

from .enhance import NEGATIVE_IMAGE

import httpx

IMAGE_PROVIDERS: dict[str, dict[str, Any]] = {
    "horde": {"name": "AI Horde (free, online, no logo)", "needs_key": False, "base_url": "https://aihorde.net/api/v2", "model": "",
              "help": "Free community service. No account, no watermark. Pictures can take from 20 seconds to a few minutes when it is busy."},
    "pollinations": {"name": "Pollinations (free, online, adds a small logo)", "needs_key": False, "base_url": "https://image.pollinations.ai", "model": "flux",
                     "help": "Quick, but the free tier stamps a pollinations.ai logo and limits how many pictures you can make."},
    "huggingface": {"name": "FLUX on Hugging Face (free token, sharp detail)", "needs_key": True, "base_url": "https://router.huggingface.co/hf-inference/models",
                    "model": "black-forest-labs/FLUX.1-schnell",
                    "help": "Free monthly credits. Make a token at huggingface.co/settings/tokens (allow “Inference”). FLUX makes far more detailed pictures than the quick engines."},
    "together": {"name": "FLUX on Together AI (free model, sharp detail)", "needs_key": True, "base_url": "https://api.together.xyz/v1",
                 "model": "black-forest-labs/FLUX.1-schnell-Free", "help": "Free FLUX model with a free key from api.together.ai. Very detailed pictures."},
    "openai": {"name": "OpenAI: DALL·E 3 / GPT Image (paid)", "needs_key": True, "base_url": "https://api.openai.com/v1", "model": "gpt-image-1",
               "help": "Paid per picture. Set the model to gpt-image-1 (best detail) or dall-e-3. Midjourney has no public API, so it cannot be connected."},
    "local": {"name": "On this PC (Stable Diffusion Turbo)", "needs_key": False, "base_url": "", "model": "stabilityai/sd-turbo",
              "help": "Private and offline after a one-time ~2.5 GB download. Works on a 4 GB graphics card (slower on CPU)."},
}
SIZES = {"square": (1024, 1024), "landscape": (1280, 720), "portrait": (768, 1152)}


class ImageError(RuntimeError):
    pass


@dataclass
class ImageConfig:
    provider: str = "horde"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    local_dir: str = ""  # folder of the downloaded picture model, when the studio has installed it


def image_config_from(saved: dict[str, Any]) -> ImageConfig:
    prov = saved.get("provider", "horde")
    if prov == "pollinations" and not saved.get("chosen"):
        prov = "horde"  # old default: the free tier adds a logo and often runs out, so nobody gets it unless they pick it on purpose
    if prov not in IMAGE_PROVIDERS:
        prov = "horde"
    p = IMAGE_PROVIDERS[prov]
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
    if cfg.model == "dall-e-3":
        body["size"] = {"1536x1024": "1792x1024", "1024x1536": "1024x1792"}.get(wanted, wanted)
        body["quality"] = "hd"
        body["response_format"] = "b64_json"
    elif cfg.model.startswith("dall-e"):
        body["response_format"] = "b64_json"
    elif cfg.model.startswith("gpt-image"):
        body["quality"] = "high"
    if "together" in cfg.base_url:  # Together takes pixel sizes and a step count instead of a named size
        body.pop("size", None)
        body.update(width=min(1024, size[0]), height=min(1024, size[1]), steps=4, response_format="b64_json")
        if "flux" not in cfg.model.lower():
            body["negative_prompt"] = NEGATIVE_IMAGE
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


def _huggingface(cfg: ImageConfig, prompt: str, size: tuple[int, int], seed: int | None) -> bytes:
    if not cfg.api_key:
        raise ImageError("Add your free Hugging Face token in Settings (huggingface.co/settings/tokens).")
    model = cfg.model or "black-forest-labs/FLUX.1-schnell"
    params: dict[str, Any] = {"width": min(1024, size[0] // 16 * 16), "height": min(1024, size[1] // 16 * 16), "num_inference_steps": 4 if "schnell" in model else 30}
    if "flux" not in model.lower():  # FLUX models have no negative prompt; the others take one
        params["negative_prompt"] = NEGATIVE_IMAGE
    if seed is not None:
        params["seed"] = seed
    try:
        r = httpx.post(f"{(cfg.base_url or 'https://router.huggingface.co/hf-inference/models').rstrip('/')}/{model}",
                       headers={"authorization": f"Bearer {cfg.api_key}", "accept": "image/png"}, json={"inputs": prompt, "parameters": params},
                       timeout=httpx.Timeout(180.0, connect=8.0))
    except httpx.ConnectError as exc:
        raise ImageError("Cannot reach Hugging Face. Check your internet connection.") from exc
    except httpx.HTTPError as exc:
        raise ImageError(f"Hugging Face did not answer in time: {exc}") from exc
    if r.status_code in (401, 403):
        raise ImageError("Hugging Face did not accept the token. Make one with the “Inference” permission and paste it in Settings.")
    if r.status_code == 402 or r.status_code == 429:
        raise ImageError("The free Hugging Face credits for this month are used up, or you are going too fast. Wait, or switch engine.")
    if r.status_code == 503:
        raise ImageError("The Hugging Face model is waking up. Try again in a minute.")
    if r.status_code >= 400:
        raise ImageError(f"Hugging Face refused the request ({r.status_code}). {r.text[:160]}".strip())
    return r.content


def _pollinations(cfg: ImageConfig, prompt: str, size: tuple[int, int], seed: int | None) -> bytes:
    q = {"width": size[0], "height": size[1], "nologo": "true", "model": cfg.model or "flux", "enhance": "true", "negative": NEGATIVE_IMAGE}
    if seed is not None:
        q["seed"] = seed
    url = f"{cfg.base_url or 'https://image.pollinations.ai'}/prompt/{urllib.parse.quote(prompt, safe='')}?{urllib.parse.urlencode(q)}"
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = httpx.get(url, timeout=httpx.Timeout(120.0, connect=8.0), follow_redirects=True)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(3 + attempt * 5)
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


HORDE_KEY = "0000000000"  # the public anonymous key
HORDE_WAIT_SECONDS = 420


def _horde(cfg: ImageConfig, prompt: str, size: tuple[int, int], seed: int | None, on_status: Callable[[str], None] | None = None) -> bytes:
    """AI Horde: volunteers' GPUs make the picture. No logo is added. Anonymous users are queued behind others."""
    base = (cfg.base_url or "https://aihorde.net/api/v2").rstrip("/")
    head = {"apikey": cfg.api_key or HORDE_KEY, "Client-Agent": "VKEditor:1:vkeditor-app", "content-type": "application/json"}
    w = max(256, min(768, size[0] // 64 * 64 // (2 if size[0] > 768 else 1)))
    h = max(256, min(768, size[1] // 64 * 64 // (2 if size[1] > 768 else 1)))
    body: dict[str, Any] = {"prompt": prompt + " ### blurry, watermark, text, logo, deformed, low quality", "nsfw": False, "censor_nsfw": True, "r2": True, "shared": False,
                            "params": {"width": w, "height": h, "steps": 32, "n": 1, "sampler_name": "k_euler_a", "cfg_scale": 7.5, "post_processing": ["GFPGAN"]}}
    if seed is not None:
        body["params"]["seed"] = str(seed)
    if cfg.model:
        body["models"] = [cfg.model]
    try:
        r = httpx.post(base + "/generate/async", headers=head, json=body, timeout=httpx.Timeout(30.0, connect=8.0))
    except httpx.HTTPError as exc:
        raise ImageError("Cannot reach the free image service (AI Horde). Check your internet connection.") from exc
    if r.status_code == 429:
        raise ImageError("The free image service says too many requests are waiting from your network. Wait a minute and retry.")
    if r.status_code >= 400:
        try:
            msg = str(r.json().get("message", ""))
        except (ValueError, AttributeError):
            msg = r.text[:160]
        raise ImageError(f"The free image service refused the request ({r.status_code}). {msg}".strip())
    try:
        job = r.json()["id"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ImageError("The free image service sent an answer this app does not understand.") from exc
    started = time.time()
    try:
        while time.time() - started < HORDE_WAIT_SECONDS:
            time.sleep(3)
            c = httpx.get(f"{base}/generate/check/{job}", headers=head, timeout=20.0)
            if c.status_code >= 400:
                continue
            info = c.json()
            if info.get("faulted"):
                raise ImageError("The free image service could not make that picture. Reword it and try again.")
            if on_status:
                on_status(f"Waiting in the free queue… position {info.get('queue_position', '?')}, about {info.get('wait_time', '?')} s")
            if info.get("done"):
                break
        else:
            raise ImageError("The free image service is very busy right now. Try again in a few minutes, or install the on-this-PC picture model.")
        st = httpx.get(f"{base}/generate/status/{job}", headers=head, timeout=30.0).json()
        gens = st.get("generations") or []
        if not gens:
            raise ImageError("The free image service finished without a picture. Try again.")
        if gens[0].get("censored"):
            raise ImageError("The free image service blocked that prompt. Reword it.")
        img = gens[0].get("img", "")
        if img.startswith("http"):
            return httpx.get(img, timeout=60.0, follow_redirects=True).content
        return base64.b64decode(img)
    except httpx.HTTPError as exc:
        raise ImageError("The connection to the free image service broke while waiting. Try again.") from exc
    finally:
        try:
            httpx.delete(f"{base}/generate/status/{job}", headers=head, timeout=5.0)  # frees the queue slot if we gave up
        except httpx.HTTPError:
            pass


_local_pipe: Any = None


def _vae_slicing(pipe: Any) -> None:
    for target, name in ((getattr(pipe, "vae", None), "enable_slicing"), (pipe, "enable_vae_slicing")):
        fn = getattr(target, name, None)
        if callable(fn):
            try:
                fn()
                return
            except Exception:  # noqa: BLE001
                continue


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
            try:
                pipe.enable_attention_slicing()
            except Exception:  # noqa: BLE001
                pass
            _vae_slicing(pipe)
        _local_pipe = pipe
    w = min(768, max(256, size[0] // 64 * 64 // (2 if size[0] > 768 else 1)))
    h = min(768, max(256, size[1] // 64 * 64 // (2 if size[1] > 768 else 1)))
    gen = torch.Generator("cuda" if cuda else "cpu").manual_seed(seed if seed is not None else int(time.time()) % 2**31)
    try:
        img = _local_pipe(prompt, num_inference_steps=4, guidance_scale=0.0, width=w, height=h, generator=gen).images[0]
    except torch.cuda.OutOfMemoryError as exc:  # type: ignore[attr-defined]
        torch.cuda.empty_cache()
        raise ImageError("The graphics card ran out of memory. Pick the square size or close other programs.") from exc
    except Exception as exc:  # noqa: BLE001 - driver / dtype / kernel errors: say what happened and let the caller fall back
        import logging

        logging.getLogger("ltxps.assistant").exception("local image generation failed")
        _local_pipe = None  # a half-broken pipeline must not be reused
        raise ImageError(f"The picture model on this PC failed ({type(exc).__name__}: {str(exc)[:140]}).") from exc
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def generate_image(cfg: ImageConfig, prompt: str, out_dir: Path, shape: str = "square", seed: int | None = None, hf_endpoint: str = "",
                   on_status: Callable[[str], None] | None = None) -> dict[str, Any]:
    prompt = prompt.strip()
    if len(prompt) < 3:
        raise ImageError("Describe the picture you want, for example “a lighthouse at sunset, watercolor”.")
    if len(prompt) > 1500:
        raise ImageError("That description is too long. Keep it under about 1,500 characters.")
    size = SIZES.get(shape, SIZES["square"])
    order = [cfg.provider]
    if cfg.provider in ("horde", "pollinations"):  # online engines back each other up; the logo-free one always goes first
        order += [p for p in ("horde", "pollinations") if p != cfg.provider]
    if cfg.provider in ("huggingface", "together"):
        order += ["horde", "pollinations"]  # a free key can run out of credit: the no-key engines take over and say why
    if cfg.provider == "local":
        order += ["horde", "pollinations"]  # the model on this PC failed (or is not usable): the free online engines take over
    if cfg.local_dir and cfg.provider != "local" and local_available()[0]:
        order.append("local")  # installed on this PC: the last resort when the online services are busy
    used, errors, raw = "", [], b""
    for prov in dict.fromkeys(order):
        try:
            if prov == "huggingface":
                raw = _huggingface(cfg, prompt, size, seed)
            elif prov in ("openai", "together"):
                if not cfg.base_url:
                    raise ImageError("No image server address is set. Open Settings.")
                raw = _remote_openai(cfg, prompt, size, seed)
            elif prov == "local":
                raw = _local(cfg, prompt, size, seed, hf_endpoint)
            elif prov == "horde":
                raw = _horde(cfg if cfg.provider == "horde" else ImageConfig("horde"), prompt, size, seed, on_status)
            else:
                raw = _pollinations(cfg if cfg.provider == "pollinations" else ImageConfig("pollinations", "https://image.pollinations.ai", "", "flux"), prompt, size, seed)
            used = prov
            break
        except ImageError as exc:
            errors.append(str(exc))
            if prov == cfg.provider and cfg.provider == "openai":
                break  # you chose this engine on purpose: tell you why it failed instead of quietly switching
    if not used:
        raise ImageError(errors[0] if len(errors) == 1 else errors[0] + " (The backup engine also failed: " + errors[-1] + ")")
    fallback = errors[0] if errors and used != cfg.provider else ""
    png, real = _check_image(raw)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(prompt)}.png"
    n = 2
    while path.exists():
        path = out_dir / f"{path.stem.rsplit('~', 1)[0]}~{n}.png"
        n += 1
    path.write_bytes(png)
    return {"path": str(path), "name": path.name, "width": real[0], "height": real[1], "prompt": prompt, "provider": used, "watermark": used == "pollinations", "fallback_reason": fallback, "bytes": len(png)}
