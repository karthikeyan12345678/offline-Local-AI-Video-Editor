"""Motion Control: a character picture is made to move exactly like the person in a reference video (Kling 2.6 Motion Control).

This model is far too big to run on a laptop graphics card, so the studio sends the two files to Kling through fal.ai (the person's own
key and credits) and brings the finished video back into the Library. Nothing is sent anywhere until the person presses the button.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .ai import AIError

QUEUE = "https://queue.fal.run"
MODELS = {"std": "fal-ai/kling-video/v2.6/standard/motion-control", "pro": "fal-ai/kling-video/v2.6/pro/motion-control"}
MAX_UPLOAD = 70 * 1024 * 1024
WAIT_SECONDS = 20 * 60
Progress = Callable[[float, str], None]


class MotionError(AIError):
    """Message is safe to show to the user."""


KEY_SHAPE = re.compile(r"^[^\s\"'{}<>\[\]]+$")  # no spaces, quotes or brackets: those can never be part of a key (and would break the request header)


def clean_key(raw: str) -> str:
    """Accept what people really paste: the bare key, `Key abc:def`, quoted text, or a whole JSON line like {"fal_key": "abc:def"}."""
    text = (raw or "").strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                text = str(data.get("fal_key") or data.get("key") or data.get("FAL_KEY") or "")
        except ValueError:
            m = re.search(r'"?(?:fal_key|key|FAL_KEY)"?\s*[:=]\s*"([^"]+)"', text)
            text = m.group(1) if m else text
    text = re.sub(r"^(?:FAL_KEY\s*=\s*|Key\s+)", "", text.strip(), flags=re.I)
    text = text.strip().strip("\"'`{}[]() \t\r\n")
    return text


PLACEHOLDER = re.compile(r"(paste|your[_\-]?key|example|insert|here|xxxx)", re.I)


def key_problem(key: str) -> str | None:
    if not key:
        return "Paste your fal.ai key first."
    if PLACEHOLDER.search(key):
        return "That is the example text from the instructions, not a real key. Open fal.ai → Dashboard → Keys, create a key, and paste the whole key here."
    if not KEY_SHAPE.match(key) or len(key) < 6:
        return "That does not look like a fal.ai key. It looks like abc123:secretvalue, with no spaces or quotes. Copy it again from fal.ai → Dashboard → Keys."
    return None


class MotionSettings:
    """The fal.ai key lives in one small file in the data folder; it is never sent anywhere except to fal.ai."""

    def __init__(self, path: Path):
        self.path = path

    def get(self) -> dict[str, Any]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}
        if d.get("fal_key"):
            d["fal_key"] = clean_key(str(d["fal_key"]))  # repairs a key that was saved with JSON pasted around it
            if PLACEHOLDER.search(d["fal_key"]):
                d["fal_key"] = ""  # example text like PASTE_YOUR_KEY_HERE was saved by mistake: treat as "no key yet" so the box asks again
        return d

    def public(self) -> dict[str, Any]:
        d = self.get()
        k = str(d.get("fal_key", ""))
        return {"has_key": bool(k), "key_hint": ("•" * 6 + k[-4:]) if len(k) >= 8 else ("•" * len(k)), "mode": d.get("mode", "std")}

    def update(self, key: str | None, mode: str | None, verify: Callable[[str], str | None] | None = None) -> None:
        d = self.get()
        if key is not None and not key.startswith("•"):
            fixed = clean_key(key)
            if fixed:
                bad = key_problem(fixed) or (verify(fixed) if verify else None)
                if bad:
                    raise MotionError(bad)
            d["fal_key"] = fixed
        if mode in ("std", "pro"):
            d["mode"] = mode
        self.path.write_text(json.dumps(d), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass


def _shrunk(path: Path, limit: int = 12 * 1024 * 1024) -> Path | None:
    """A phone video can be 50 MB. The service does not need that much, so squeeze it (same length) before the upload. None = leave as is."""
    try:
        if path.stat().st_size <= limit:
            return None
        from ..system import ffmpeg_path

        ff = ffmpeg_path()
        if not ff:
            return None
        out = Path(tempfile.mkdtemp(prefix="vk-motion-")) / "small.mp4"
        cmd = [ff, "-y", "-i", str(path), "-vf", "scale='if(gt(iw,ih),-2,min(720,iw))':'if(gt(iw,ih),min(720,ih),-2)'", "-c:v", "libx264", "-crf", "27",
               "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, capture_output=True, timeout=300, check=True)
        return out if out.exists() and 0 < out.stat().st_size < path.stat().st_size else None
    except (OSError, subprocess.SubprocessError):
        return None


def _data_uri(path: Path, fallback: str) -> str:
    size = path.stat().st_size
    if size > MAX_UPLOAD:
        raise MotionError(f"“{path.name}” is {size / 1e6:.0f} MB. Keep each file under {MAX_UPLOAD // 1024 // 1024} MB (trim the video in the editor first).")
    mime = mimetypes.guess_type(path.name)[0] or fallback
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json()
        det = d.get("detail", d)
        if isinstance(det, list):
            det = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in det)
        return str(det)[:240]
    except (ValueError, AttributeError):
        return r.text[:240]


def run(key: str, image: Path, video: Path, dest: Path, *, orientation: str = "video", mode: str = "std", prompt: str = "", keep_sound: bool = True,
        video_seconds: float = 0.0, on_progress: Progress | None = None, cancel: threading.Event | None = None, client: httpx.Client | None = None,
        poll: float = 4.0) -> dict[str, Any]:
    say = on_progress or (lambda p, m: None)
    if not key:
        raise MotionError("Add your fal.ai key first (Motion Control page → Connect). It is used only to send these two files to the cloud service.")
    if orientation not in ("image", "video"):
        orientation = "video"
    limit = 10.0 if orientation == "image" else 30.0
    if video_seconds and video_seconds > limit + 0.05:
        raise MotionError(f"The motion video is {video_seconds:.0f} s. With “keep the picture's own pose/camera” it must be {limit:.0f} s or shorter; with “follow the video” {30:.0f} s. Trim it in the editor first.")
    if video_seconds and video_seconds < 2.9:
        raise MotionError("The motion video must be at least 3 seconds long.")
    c = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0, write=900.0, pool=30.0))
    key = clean_key(key)
    if PLACEHOLDER.search(key):
        raise MotionError(key_problem(key) or "That is not a real key.")
    if not KEY_SHAPE.match(key):  # only characters that can never be in a key (they would also break the request header)
        raise MotionError(key_problem(key) or "That does not look like a fal.ai key.")
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    body: dict[str, Any] = {"image_url": _data_uri(image, "image/png"), "video_url": _data_uri(_shrunk(video) or video, "video/mp4"), "character_orientation": orientation,
                            "keep_original_sound": bool(keep_sound)}
    if prompt.strip():
        body["prompt"] = prompt.strip()[:500]
    size = queue_run(c, headers, MODELS.get(mode, MODELS["std"]), body, dest, say, cancel, poll, "Sending the two files", "Animating your picture")
    return {"mode": mode, "orientation": orientation, "bytes": size}


def queue_run(c: httpx.Client, headers: dict[str, str], model: str, body: dict[str, Any], dest: Path, say: Progress, cancel: threading.Event | None, poll: float,
              sending: str = "Sending your files", working: str = "Working on it") -> int:
    """Submit to the fal.ai queue, wait, download the video to `dest`. Returns the size in bytes."""
    say(0.05, sending)
    try:
        r = c.post(f"{QUEUE}/{model}", headers=headers, content=json.dumps(body))
        if r.status_code in (401, 403):
            raise MotionError("fal.ai did not accept the key, or the account has no credit left. Check the key and your balance on fal.ai.")
        if r.status_code == 422:
            raise MotionError("The service refused the files: " + _detail(r))
        if r.status_code >= 400:
            raise MotionError(f"fal.ai answered with an error ({r.status_code}): {_detail(r)}")
        sub = r.json()
        status_url, result_url = sub["status_url"], sub["response_url"]
    except MotionError:
        raise
    except httpx.ConnectError as exc:
        raise MotionError("Cannot connect to fal.ai. Check your internet, VPN or firewall, and that queue.fal.run is not blocked.") from exc
    except (httpx.WriteTimeout, httpx.ReadTimeout, httpx.WriteError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
        raise MotionError(f"The upload did not finish ({type(exc).__name__}). The upload is large for your connection: try smaller files.") from exc
    except httpx.HTTPError as exc:
        raise MotionError(f"Could not talk to fal.ai ({type(exc).__name__}: {str(exc)[:120]}).") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise MotionError("fal.ai sent an answer this app does not understand.") from exc
    started = time.time()
    try:
        while True:
            if cancel is not None and cancel.is_set():
                try:
                    c.put(sub.get("cancel_url", ""), headers=headers)
                except httpx.HTTPError:
                    pass
                raise MotionError("Cancelled.")
            st = c.get(status_url, headers=headers)
            if st.status_code >= 400:
                raise MotionError(f"fal.ai could not report progress ({st.status_code}): {_detail(st)}")
            info = st.json()
            state = str(info.get("status", ""))
            if state == "COMPLETED":
                break
            if state in ("FAILED", "ERROR"):
                raise MotionError("The service could not make this video: " + str(info.get("error") or info.get("detail") or "unknown reason")[:200])
            pos = info.get("queue_position")
            say(min(0.9, 0.1 + (time.time() - started) / 400), "Waiting in line" + (f" (position {pos})" if pos is not None else "") if state == "IN_QUEUE" else working)
            if time.time() - started > WAIT_SECONDS:
                raise MotionError("It is taking too long (over 20 minutes). Try again later.")
            time.sleep(poll)
        res = c.get(result_url, headers=headers)
        if res.status_code >= 400:
            raise MotionError(f"The video was made but fal.ai would not hand it over ({res.status_code}): {_detail(res)}")
        url = res.json()["video"]["url"]
        say(0.93, "Downloading the finished video")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with c.stream("GET", url, follow_redirects=True) as dl:
            if dl.status_code >= 400:
                raise MotionError("The finished video could not be downloaded.")
            with open(dest, "wb") as f:
                for chunk in dl.iter_bytes():
                    f.write(chunk)
    except MotionError:
        raise
    except httpx.HTTPError as exc:
        raise MotionError("The connection to fal.ai broke while waiting. Try again.") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise MotionError("fal.ai sent an answer this app does not understand.") from exc
    return dest.stat().st_size


# ---- Sharp cloud video: LTX-2.3 (22B parameters, 1080p and up, with sound) on fal.ai. Far too large for a laptop card, so it runs in the cloud.
VIDEO_MODELS = {"text": "fal-ai/ltx-2.3/text-to-video", "image": "fal-ai/ltx-2.3/image-to-video"}
PRICE_PER_SECOND = {"1080p": 0.08, "1440p": 0.16, "2160p": 0.32}


def video_cost(seconds: int, resolution: str) -> float:
    return round(seconds * PRICE_PER_SECOND.get(resolution, 0.08), 2)


def run_video(key: str, prompt: str, dest: Path, *, image: Path | None = None, end_image: Path | None = None, duration: int = 6, resolution: str = "1080p",
              aspect_ratio: str = "16:9", audio: bool = True, on_progress: Progress | None = None, cancel: threading.Event | None = None,
              client: httpx.Client | None = None, poll: float = 4.0) -> dict[str, Any]:
    say = on_progress or (lambda p, m: None)
    key = clean_key(key)
    if not key:
        raise MotionError("Add your fal.ai key first (Motion control page → Connect). The same key works for sharp cloud video.")
    bad = key_problem(key)
    if bad:
        raise MotionError(bad)
    if not prompt.strip():
        raise MotionError("Describe the video first.")
    if duration not in (6, 8, 10):
        raise MotionError("Choose 6, 8 or 10 seconds.")
    if resolution not in PRICE_PER_SECOND:
        raise MotionError("Choose 1080p, 1440p or 2160p.")
    if end_image is not None and image is None:
        raise MotionError("An end picture needs a start picture too.")
    body: dict[str, Any] = {"prompt": prompt.strip()[:2000], "duration": duration, "resolution": resolution, "generate_audio": bool(audio)}
    if image is not None:
        body["image_url"] = _data_uri(image, "image/png")
        body["aspect_ratio"] = aspect_ratio if aspect_ratio in ("16:9", "9:16") else "auto"
        if end_image is not None:
            body["end_image_url"] = _data_uri(end_image, "image/png")
        model = VIDEO_MODELS["image"]
    else:
        body["aspect_ratio"] = aspect_ratio if aspect_ratio in ("16:9", "9:16") else "16:9"
        model = VIDEO_MODELS["text"]
    c = client or httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0, write=900.0, pool=30.0))
    headers = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    size = queue_run(c, headers, model, body, dest, say, cancel, poll, "Sending your request", "Making your video in the cloud")
    return {"model": model, "bytes": size, "cost_usd": video_cost(duration, resolution)}


def _check_key(key: str, client: httpx.Client | None = None) -> str | None:
    """Asks fal.ai whether the key is accepted (GET /v1/models?limit=1). Returns a plain message when it is refused, None when fine or when the check cannot be made."""
    try:
        c = client or httpx.Client(timeout=httpx.Timeout(10.0, connect=6.0))
        r = c.get("https://api.fal.ai/v1/models", params={"limit": 1}, headers={"Authorization": f"Key {key}"})
    except httpx.HTTPError:
        return None  # offline: save the key anyway
    if r.status_code in (401, 403):
        return "fal.ai says this key is not valid (it was refused). Create a new key on fal.ai → Dashboard → Keys with the “API” preset and paste the whole key."
    return None


check_key = _check_key  # the tests replace this name so they never reach fal.ai
