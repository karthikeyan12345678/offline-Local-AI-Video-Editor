"""AI helpers for the editor. Everything here runs on the user's PC.

follow_person   find a person (face) in the video and return a smooth camera path
silence_cuts    find the quiet stretches so they can be cut out
scene_cuts      find the places where the picture changes shot
beat_times      tempo and beat positions of a song, for cutting to the music
auto_enhance    brightness / contrast / saturation that suit a frame
transcribe      speech to subtitles with Whisper (faster-whisper)
speak           text to speech with the voices the operating system already has
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

try:  # the AI Assistant build ships without numpy; these tools are only used by the video studio
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]


from .media import FfmpegError, probe, require_ffmpeg as ffmpeg_path

Progress = Callable[[float], None]
MODEL_DIR = Path(__file__).parent / "models"
YUNET = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AIError(ValueError):
    """Message is safe to show to the user."""


def _need_numpy() -> None:
    if np is None:
        raise AIError("This build does not include the AI video tools.")


# ---------------------------------------------------------------- raw frames / audio through ffmpeg
def _frames(path: str, start: float, dur: float, fps: float, width: int, cancel: threading.Event | None):
    """Yields (time_in_source, BGR uint8 frame) sampled at `fps`, scaled to `width` px wide."""
    vf = f"fps={fps},scale={width}:-2:flags=bilinear"
    cmd = [ffmpeg_path(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", path, "-an", "-vf", vf, "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    info = probe(Path(path))
    if not info.width or not info.height:
        raise AIError("Could not read the picture of this video.")
    w = width
    h = max(2, round(info.height * width / info.width / 2) * 2)
    size = w * h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    i = 0
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise AIError("Cancelled.")
            buf = proc.stdout.read(size) if proc.stdout else b""
            if len(buf) < size:
                break
            yield start + i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        proc.kill()
        proc.wait()


def face_at(path: str, t: float) -> dict | None:
    """The biggest face in the picture at second `t`: {'x','y','w','h'} (0..1 of the frame, x and y = top-left) or None."""
    _need_numpy()
    try:
        import cv2
    except ImportError:
        return None
    if not YUNET.exists():
        return None
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (640, 640), 0.5, 0.3, 50)
    best = None
    for _, frame in _frames(path, max(0.0, t - 0.2), 0.8, 4.0, 640, None):
        h, w = frame.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(frame)
        if faces is not None and len(faces):
            f = max(faces, key=lambda r: r[2] * r[3])
            cand = {"x": float(f[0]) / w, "y": float(f[1]) / h, "w": float(f[2]) / w, "h": float(f[3]) / h, "area": float(f[2] * f[3])}
            if best is None or cand["area"] > best["area"]:
                best = cand
    if best:
        best.pop("area")
    return best


def _audio_mono(path: str, rate: int = 22050, max_seconds: float = 600) -> np.ndarray:
    _need_numpy()
    cmd = [ffmpeg_path(), "-v", "error", "-t", f"{max_seconds:.0f}", "-i", path, "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if out.returncode != 0 or not out.stdout:
        raise AIError("This file has no sound to analyse.")
    return np.frombuffer(out.stdout, np.float32)


# ---------------------------------------------------------------- follow a person
def _smooth(v: np.ndarray, sigma: float) -> np.ndarray:
    if len(v) < 3 or sigma <= 0:
        return v
    r = int(sigma * 3) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    pad = np.pad(v, (r, r), mode="edge")
    return np.convolve(pad, k, mode="valid")


def follow_person(path: str, start: float, duration: float, on_progress: Progress | None = None, cancel: threading.Event | None = None, sample_fps: float = 5.0) -> dict:
    _need_numpy()
    """Camera path that keeps the main person in frame: {'keys': [[t, x, y], ...], 'found': 0..1}.

    Times are source seconds; x and y are 0..1 of the picture. The most prominent face
    (biggest, closest to the previous position) is followed; gaps are bridged, then the
    path is smoothed forwards and backwards so it never jerks.
    """
    try:
        import cv2
    except ImportError as exc:  # pragma: no cover
        raise AIError("Person tracking needs OpenCV, which is not installed in this build.") from exc
    if not YUNET.exists():
        raise AIError("The face-detection model file is missing from this build.")
    duration = max(0.2, duration)
    width = 480
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (width, width), 0.6, 0.3, 50)
    times: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    ws: list[float] = []
    prev = np.array([0.5, 0.5])
    total = max(1, int(duration * sample_fps))
    n = 0
    last_gray = None
    for t, frame in _frames(path, start, duration, sample_fps, width, cancel):
        h, w = frame.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(frame)
        x = y = fw = None
        if faces is not None and len(faces):
            best, best_score = None, -1e9
            for f in faces:
                cx, cy = (f[0] + f[2] / 2) / w, (f[1] + f[3] / 2) / h
                size = f[2] * f[3] / (w * h)
                score = size * 8 - float(np.hypot(cx - prev[0], cy - prev[1])) + float(f[14]) * 0.2
                if score > best_score:
                    best, best_score = (cx, cy, f[2] / w), score
            x, y, fw = best
            # aim a little below the face so head and shoulders sit in the window
            y = min(1.0, y + fw * 0.35)
            prev = np.array([x, y])
        else:  # no face: follow whatever moves most, so the camera still goes somewhere sensible
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (9, 9), 0)
            if last_gray is not None and last_gray.shape == gray.shape:
                diff = cv2.threshold(cv2.absdiff(gray, last_gray), 25, 255, cv2.THRESH_BINARY)[1]
                m = cv2.moments(diff, binaryImage=True)
                if m["m00"] > 0.004 * w * h:
                    x, y = m["m10"] / m["m00"] / w, m["m01"] / m["m00"] / h
                    fw = 0.0
            last_gray = gray
        times.append(t)
        xs.append(np.nan if x is None else x)
        ys.append(np.nan if y is None else y)
        ws.append(0.0 if fw is None else fw)
        n += 1
        if on_progress:
            on_progress(min(0.98, n / total))
    if not times:
        raise AIError("No picture could be read from this clip.")
    X, Y = np.array(xs), np.array(ys)
    ok = ~np.isnan(X)
    found = float(ok.mean())
    if ok.sum() == 0:
        raise AIError("No person or movement was found in this clip. Try a clip where someone is facing the camera.")
    T = np.array(times)
    X = np.interp(T, T[ok], X[ok])
    Y = np.interp(T, T[ok], Y[ok])
    sigma = max(1.0, sample_fps * 0.5)  # about half a second of smoothing, each direction
    fx, fy = _smooth(X, sigma), _smooth(Y, sigma)
    bx, by = _smooth(X[::-1], sigma)[::-1], _smooth(Y[::-1], sigma)[::-1]
    X, Y = (fx + bx) / 2, (fy + by) / 2
    keys = [[round(float(t), 3), round(float(x), 4), round(float(y), 4)] for t, x, y in zip(T, X, Y)]
    return {"keys": keys, "found": round(found, 3)}


# ---------------------------------------------------------------- silence / scenes
def _scan_stderr(path: str, args: list[str], duration: float, on_progress: Progress | None, cancel: threading.Event | None) -> str:
    cmd = [ffmpeg_path(), "-hide_banner", "-nostats", "-i", path, *args, "-f", "null", "-"]
    p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, errors="replace", creationflags=NO_WINDOW)
    lines: list[str] = []
    assert p.stderr is not None
    for line in p.stderr:
        lines.append(line)
        if cancel is not None and cancel.is_set():
            p.kill()
            raise AIError("Cancelled.")
    p.wait()
    if p.returncode != 0:
        raise FfmpegError("ffmpeg could not analyse this file.")
    return "".join(lines)


def silence_cuts(path: str, duration: float, noise_db: float = -35, min_silence: float = 0.6, pad: float = 0.12, on_progress: Progress | None = None, cancel: threading.Event | None = None) -> dict:
    """Stretches worth keeping: {'keep': [[start, end], ...], 'silences': [...]} in seconds."""
    out = _scan_stderr(path, ["-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}"], duration, on_progress, cancel)
    starts = [float(v) for v in re.findall(r"silence_start: (-?[\d.]+)", out)]
    ends = [float(v) for v in re.findall(r"silence_end: ([\d.]+)", out)]
    sil: list[tuple[float, float]] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        sil.append((max(0.0, s), min(duration, e)))
    keep: list[list[float]] = []
    cursor = 0.0
    for s, e in sil:
        a, b = cursor, min(duration, s + pad)
        if b - a > 0.15:
            keep.append([round(a, 3), round(b, 3)])
        cursor = max(0.0, e - pad)
    if duration - cursor > 0.15:
        keep.append([round(cursor, 3), round(duration, 3)])
    if not keep:
        keep = [[0.0, round(duration, 3)]]
    return {"keep": keep, "silences": [[round(a, 3), round(b, 3)] for a, b in sil], "removed": round(max(0.0, duration - sum(b - a for a, b in keep)), 2)}


def scene_cuts(path: str, duration: float, threshold: float = 0.35, on_progress: Progress | None = None, cancel: threading.Event | None = None) -> dict:
    out = _scan_stderr(path, ["-an", "-vf", f"select='gt(scene,{threshold})',showinfo"], duration, on_progress, cancel)
    cuts = sorted({round(float(v), 3) for v in re.findall(r"pts_time:([\d.]+)", out)})
    cuts = [c for c in cuts if 0.3 < c < duration - 0.3]
    merged: list[float] = []
    for c in cuts:  # shots shorter than 0.5 s are flashes, not scenes
        if not merged or c - merged[-1] >= 0.5:
            merged.append(c)
    return {"cuts": merged}


# ---------------------------------------------------------------- music
def beat_times(path: str, max_seconds: float = 600) -> dict:
    """Tempo (BPM) and beat positions in seconds: onset strength, tempo by autocorrelation, grid snapped to onsets."""
    _need_numpy()
    y = _audio_mono(path, 22050, max_seconds)
    sr, hop, win = 22050, 512, 1024
    if len(y) < sr * 2:
        raise AIError("The music is too short to find a beat.")
    frames = 1 + (len(y) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(y[idx] * np.hanning(win), axis=1))
    mag = np.log1p(spec * 10)
    onset = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    onset = np.concatenate([[0], onset])
    onset = (onset - onset.mean()) / (onset.std() + 1e-9)
    fps = sr / hop
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 60)  # 60..200 BPM
    ac = np.correlate(onset, onset, "full")[len(onset) - 1:]
    ac[:lo] = 0
    ac[hi + 1:] = 0
    weights = np.exp(-0.5 * (np.log2((60 * fps / np.maximum(np.arange(len(ac)), 1)) / 120)) ** 2)  # prefer ~120 BPM
    lag = int(np.argmax(ac * weights))
    if lag <= 0:
        raise AIError("No steady beat was found in this music.")
    period = float(lag)
    if 0 < lag < len(ac) - 1 and ac[lag - 1] != ac[lag + 1]:  # parabolic refinement: lags are whole frames, tempo is not
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        den = a - 2 * b + c
        if den != 0:
            period = lag + 0.5 * (a - c) / den
    best_off, best_score = 0.0, -1.0
    for off in np.arange(0, period, 0.5):
        pts = np.round(np.arange(off, len(onset) - 1, period)).astype(int)
        sc = onset[pts].sum()
        if sc > best_score:
            best_off, best_score = float(off), sc
    beats = []
    pos = best_off
    while pos < len(onset):
        lo_i, hi_i = max(0, int(round(pos)) - 2), min(len(onset), int(round(pos)) + 3)
        beats.append(float(lo_i + int(np.argmax(onset[lo_i:hi_i]))) / fps)  # snap to the nearest strong onset
        pos += period
    bpm = 60 * fps / period
    while bpm < 70:
        bpm *= 2
    while bpm > 180:
        bpm /= 2
    return {"bpm": round(bpm, 1), "beats": [round(b, 3) for b in beats]}


# ---------------------------------------------------------------- picture
def auto_enhance(path: str, at: float, duration: float) -> dict:
    """Adjust values (the editor's -100..100 scale) that stretch a flat or dark frame; modest by design."""
    _need_numpy()
    t = max(0.0, min(at, max(0.0, duration - 0.1)))
    try:
        _, frame = next(_frames(path, t, 0.5, 2, 320, None))
    except StopIteration as exc:
        raise AIError("Could not read a frame to analyse.") from exc
    f = frame.astype(np.float32) / 255.0
    luma = 0.114 * f[..., 0] + 0.587 * f[..., 1] + 0.299 * f[..., 2]
    p2, p50, p98 = np.percentile(luma, [2, 50, 98])
    mx, mn = f.max(axis=2), f.min(axis=2)
    sat = float(np.mean((mx - mn) / (mx + 1e-6)))
    spread = max(0.05, float(p98 - p2))
    contrast = float(np.clip((0.88 / spread - 1) * 55, -20, 60))
    brightness = float(np.clip((0.46 - float(p50)) * 70, -30, 40))
    gamma = float(np.clip(math.log(max(0.05, min(0.95, float(p50)))) / math.log(0.46), 1.0, 1.6)) if p50 < 0.35 else 1.0
    saturation = float(np.clip((0.38 - sat) * 120, -10, 40))
    return {"brightness": round(brightness * (0.6 if gamma != 1 else 1), 1), "contrast": round(contrast, 1), "saturation": round(saturation, 1), "gamma": round(gamma, 2), "hue": 0}


# ---------------------------------------------------------------- speech to text
WHISPER_SIZES = {"tiny": "Systran/faster-whisper-tiny", "base": "Systran/faster-whisper-base", "small": "Systran/faster-whisper-small"}


def whisper_dir(models_root: Path, size: str) -> Path:
    return models_root / f"whisper-{size}"


def whisper_ready(models_root: Path, size: str) -> bool:
    d = whisper_dir(models_root, size)
    return (d / "model.bin").exists() and (d / "config.json").exists() and not list(d.glob("*.part"))


def transcribe(path: str, model_dir: Path, language: str | None, on_progress: Progress | None = None, cancel: threading.Event | None = None, start: float = 0.0, duration: float = 0.0) -> dict:
    """Subtitle segments [{start, end, text}] in source seconds, plus the language Whisper detected."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover
        raise AIError("Captions need faster-whisper, which is not installed in this build.") from exc
    wav = model_dir.parent / f"_speech_{abs(hash(path)) % 10**8}.wav"
    cmd = [ffmpeg_path(), "-y", "-v", "error", "-ss", f"{start:.3f}", *(["-t", f"{duration:.3f}"] if duration > 0 else []), "-i", path, "-vn", "-ac", "1", "-ar", "16000", str(wav)]
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not wav.exists():
        raise AIError("This clip has no sound to turn into captions.")
    try:
        model = WhisperModel(str(model_dir), device="cpu", compute_type="int8")
        segs, info = model.transcribe(str(wav), language=language or None, vad_filter=True, beam_size=1)
        total = max(0.1, info.duration)
        out = []
        for s in segs:
            if cancel is not None and cancel.is_set():
                raise AIError("Cancelled.")
            text = s.text.strip()
            if text:
                out.append({"start": round(start + s.start, 2), "end": round(start + s.end, 2), "text": text})
            if on_progress:
                on_progress(min(0.98, s.end / total))
        return {"segments": out, "language": info.language}
    finally:
        wav.unlink(missing_ok=True)


def to_srt(segments: list[dict]) -> str:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    return "\n".join(f"{i}\n{ts(s['start'])} --> {ts(s['end'])}\n{s['text']}\n" for i, s in enumerate(segments, 1))


# ---------------------------------------------------------------- text to speech
def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def tts_voices() -> list[str]:
    try:
        if sys.platform.startswith("win"):
            ps = "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }"
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
            return [v.strip() for v in r.stdout.splitlines() if v.strip()]
        if sys.platform == "darwin":
            r = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=20)
            return [ln.split("  ")[0].strip() for ln in r.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError):
        return []
    return ["default"] if shutil.which("espeak-ng") or shutil.which("espeak") else []


def speak(text: str, dest_wav: Path, voice: str = "", rate: int = 0) -> None:
    """Speaks `text` to a WAV file with the system voice. `rate` runs from -10 (slow) to 10 (fast)."""
    text = text.strip()
    if not text:
        raise AIError("Type the words to speak.")
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform.startswith("win"):
            ps = (
                "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                + (f"try {{ $s.SelectVoice({_ps_quote(voice)}) }} catch {{}}; " if voice else "")
                + f"$s.Rate = {int(max(-10, min(10, rate)))}; $s.SetOutputToWaveFile({_ps_quote(str(dest_wav))}); $s.Speak([Console]::In.ReadToEnd()); $s.Dispose()"
            )
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], input=text, capture_output=True, text=True, encoding="utf-8", timeout=300, creationflags=NO_WINDOW)
            if r.returncode != 0:
                raise AIError("Windows could not speak this text: " + (r.stderr.strip()[:200] or "unknown error"))
        elif sys.platform == "darwin":
            aiff = dest_wav.with_suffix(".aiff")
            cmd = ["say", "-o", str(aiff), "-r", str(175 + rate * 12)] + (["-v", voice] if voice else [])
            subprocess.run(cmd, input=text, text=True, check=True, timeout=300)
            subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-i", str(aiff), str(dest_wav)], check=True)
            aiff.unlink(missing_ok=True)
        else:
            exe = shutil.which("espeak-ng") or shutil.which("espeak")
            if not exe:
                raise AIError("No text-to-speech voice is installed on this computer.")
            subprocess.run([exe, "-s", str(165 + rate * 12), "-w", str(dest_wav), text], check=True, timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AIError(f"Text to speech failed: {exc}") from exc
    if not dest_wav.exists() or dest_wav.stat().st_size < 1000:
        raise AIError("The voice produced no sound.")
