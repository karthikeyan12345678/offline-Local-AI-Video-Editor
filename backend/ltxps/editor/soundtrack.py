"""Sound and voice for a video: a narration (the computer's own voice), an ambient sound that fits the scene, and a soft music bed.

Everything here is made on this PC with numpy and the voices Windows already has, so it works offline and costs nothing.
The ambience is synthesised (filtered noise and tones), not recorded or AI-generated: it is meant as a believable background
(sea, rain, wind, city, fire, night, space, calm music), not as a finished sound design.
"""

from __future__ import annotations

import math
import re
import wave
from pathlib import Path
from typing import Any, Callable

from . import voicecast
from .ai import AIError, np, speak, tts_voices
from .media import FfmpegError, probe, run_ffmpeg

RATE = 44100

# keyword -> ambience id (first match wins, in this order)
KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("rain", ("rain", "storm", "drizzle", "monsoon", "thunder")),
    ("waves", ("ocean", "sea ", "beach", "wave", "shore", "lighthouse", "harbor", "harbour", "coast", "cliff", "boat")),
    ("fire", ("fire", "campfire", "flame", "burning", "bonfire", "candle")),
    ("wind", ("wind", "desert", "mountain", "snow", "field", "meadow", "forest", "hill", "valley", "grass")),
    ("city", ("city", "street", "traffic", "market", "crowd", "downtown", "road", "car ", "bus ", "town")),
    ("night", ("night", "moon", "stars", "dark", "midnight", "evening")),
    ("space", ("space", "galaxy", "planet", "nebula", "alien", "star ship", "spaceship", "cosmic")),
]
AMBIENCES = ["waves", "rain", "wind", "fire", "city", "night", "space", "calm"]
LABELS = {"waves": "Sea waves", "rain": "Rain", "wind": "Wind", "fire": "Fire crackle", "city": "City hum", "night": "Night crickets", "space": "Deep space", "calm": "Calm music", "none": "No background sound"}


def pick_ambience(prompt: str) -> str:
    """Chooses a background sound from the words of the prompt; calm music when nothing matches."""
    low = " " + re.sub(r"\s+", " ", prompt.lower()) + " "
    for amb, words in KEYWORDS:
        if any(w in low for w in words):
            return amb
    return "calm"


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    """Two-pole low-pass done in the frequency domain (numpy only, no scipy)."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    spec *= 1.0 / (1.0 + 1j * f / cutoff) ** 2
    return np.fft.irfft(spec, len(x))


def _highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - _lowpass(x, cutoff)


def _lfo(n: int, hz: float, phase: float = 0.0) -> np.ndarray:
    return 0.5 + 0.5 * np.sin(2 * np.pi * hz * np.arange(n) / RATE + phase)


def _pad(n: int, notes: tuple[float, ...], gain: float) -> np.ndarray:
    t = np.arange(n) / RATE
    out = np.zeros(n)
    for i, f in enumerate(notes):
        out += np.sin(2 * np.pi * f * t) * (0.6 + 0.4 * np.sin(2 * np.pi * (0.07 + 0.03 * i) * t + i))
        out += 0.3 * np.sin(2 * np.pi * f * 2 * t) * _lfo(n, 0.05 + 0.02 * i, i)
    return out / max(1, len(notes)) * gain


def synth(kind: str, seconds: float, seed: int = 7) -> np.ndarray:
    """Mono float signal in -1..1 for the chosen ambience."""
    if np is None:
        raise AIError("This build does not include the AI video tools.")
    n = max(1, int(seconds * RATE))
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n)
    if kind == "waves":
        swell = 0.25 + 0.75 * _lfo(n, 0.11) ** 2
        sig = _lowpass(noise, 900) * swell * 2.2 + _highpass(_lowpass(noise, 6000), 1500) * swell ** 3 * 0.5
    elif kind == "rain":
        sig = _highpass(_lowpass(noise, 9000), 900) * 1.2 + _lowpass(noise, 250) * 0.3
    elif kind == "wind":
        sig = _lowpass(noise, 500) * (0.3 + 0.7 * _lfo(n, 0.07)) * 2.5 + _lowpass(noise, 1800) * (0.2 + 0.8 * _lfo(n, 0.13, 2)) * 0.4
    elif kind == "fire":
        base = _lowpass(noise, 600) * 0.7
        clicks = np.zeros(n)
        idx = rng.integers(0, n, size=max(1, int(seconds * 14)))
        clicks[idx] = rng.uniform(0.4, 1.0, size=len(idx))
        sig = base + _highpass(_lowpass(clicks, 5000), 800) * 6
    elif kind == "city":
        sig = _lowpass(noise, 250) * 1.8 * (0.6 + 0.4 * _lfo(n, 0.05)) + _lowpass(noise, 1200) * 0.25 + _pad(n, (110.0, 164.8), 0.15)
    elif kind == "night":
        t = np.arange(n) / RATE
        chirp = np.sin(2 * np.pi * 4300 * t) * (np.sin(2 * np.pi * 7 * t) > 0.6) * _lfo(n, 0.2)
        sig = _lowpass(noise, 300) * 0.35 + chirp * 0.12 + _pad(n, (110.0, 130.8), 0.12)
    elif kind == "space":
        sig = _pad(n, (55.0, 82.4, 110.0, 164.8), 0.9) + _lowpass(noise, 120) * 0.5
    else:  # calm music: a slow major-7th pad with a soft bell every few seconds
        sig = _pad(n, (130.8, 164.8, 196.0, 246.9), 1.0)
        t = np.arange(n) / RATE
        for k, at in enumerate(np.arange(1.0, seconds, 3.2)):
            f = (523.3, 659.3, 784.0, 987.8)[k % 4]
            s = int(at * RATE)
            m = min(n - s, int(2.5 * RATE))
            if m > 0:
                env = np.exp(-np.arange(m) / (0.6 * RATE))
                sig[s:s + m] += 0.18 * np.sin(2 * np.pi * f * t[:m]) * env
    peak = float(np.max(np.abs(sig))) or 1.0
    sig = sig / peak * 0.9
    fade = min(n // 2, int(0.8 * RATE))
    if fade > 1:
        ramp = np.linspace(0, 1, fade)
        sig[:fade] *= ramp
        sig[-fade:] *= ramp[::-1]
    return sig


def write_wav(path: Path, sig: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(sig, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def speak_as(text: str, raw: Path, persona: str = "", voice: str = "", rate: int = 0, voices: list[str] | None = None) -> dict[str, Any] | None:
    """Speaks `text` into the WAV file `raw`. With a persona (girl, boy, woman, man, old_woman, old_man) the voice is picked and shaped to fit that person.
    Returns the voice plan that was used (None without a persona)."""
    if persona not in voicecast.PERSONAS:
        speak(text, raw, voice, rate)
        return None
    cast = voicecast.plan(persona, tts_voices() if voices is None else voices, voice)
    speak(text, raw, cast["voice"] or voice, max(-10, min(10, rate + cast["rate"])))
    try:
        with wave.open(str(raw), "rb") as w:
            sr = w.getframerate()
    except (OSError, wave.Error):
        sr = 22050
    filt = voicecast.audio_filter(cast, sr)
    if filt:
        shaped = raw.with_name(raw.stem + "_shaped.wav")
        try:
            run_ffmpeg(["-i", str(raw), "-af", filt, "-ar", str(sr), str(shaped)], 0)
            shaped.replace(raw)
        except FfmpegError:
            shaped.unlink(missing_ok=True)  # keep the plain voice rather than lose the narration
    return cast


def build(video: Path, dest: Path, *, prompt: str = "", narration: str = "", voice: str = "", rate: int = 0, ambience: str = "auto",
          music: bool = False, level: float = 0.5, keep_original: bool = True, work: Path | None = None, on_status: Callable[[str], None] | None = None,
          persona: str = "", voices: list[str] | None = None) -> dict[str, Any]:
    """Mixes voice, ambience and music into `video` and writes `dest` (video stream copied, new sound track).

    Returns what was added, plus warnings (for example a narration longer than the video, which is sped up or cut)."""
    if np is None:
        raise AIError("This build does not include the AI video tools.")
    say = on_status or (lambda _m: None)
    info = probe(video)
    if info.kind != "video" or info.duration <= 0:
        raise AIError("Sound can only be added to a video.")
    work = work or dest.parent
    work.mkdir(parents=True, exist_ok=True)
    seconds = info.duration
    level = float(min(1.0, max(0.0, level)))
    warnings: list[str] = []
    inputs: list[Path] = []
    chain: list[str] = []
    used: list[str] = []

    amb = pick_ambience(prompt) if ambience in ("", "auto") else ambience
    if amb != "none" and amb not in AMBIENCES:
        raise AIError("Unknown background sound: " + amb)
    if amb != "none":
        say("Making the background sound")
        p = work / f"_amb_{dest.stem}.wav"
        write_wav(p, synth(amb, seconds))
        inputs.append(p)
        chain.append(f"[{len(inputs)}:a]volume={0.55 * level + 0.05:.3f}[amb]")
        used.append("amb")
    if music and amb != "calm":
        p = work / f"_mus_{dest.stem}.wav"
        write_wav(p, synth("calm", seconds, seed=11))
        inputs.append(p)
        chain.append(f"[{len(inputs)}:a]volume={0.35 * level + 0.03:.3f}[mus]")
        used.append("mus")
    cast = None
    if narration.strip():
        say("Recording the voice")
        raw = work / f"_voice_{dest.stem}.wav"
        cast = speak_as(narration, raw, persona, voice, rate, voices)
        if cast and cast["note"]:
            warnings.append(cast["note"])
        vsec = wav_seconds(raw) if raw.suffix == ".wav" else seconds
        inputs.append(raw)
        tempo = ""
        if vsec > seconds * 0.98:
            f = min(1.4, vsec / (seconds * 0.98))
            tempo = f"atempo={f:.3f},"
            if vsec / f > seconds + 0.1:
                warnings.append(f"The narration is {vsec:.0f} s but the video is only {seconds:.0f} s, so the end of it was cut. Shorten the words or make a longer video.")
            else:
                warnings.append(f"The narration ({vsec:.0f} s) was sped up a little to fit the {seconds:.0f} s video.")
        chain.append(f"[{len(inputs)}:a]{tempo}apad,atrim=0:{seconds:.3f},volume=1.6[voc]")
        used.append("voc")
    if keep_original and info.has_audio:
        chain.append("[0:a]volume=1.0[org]")
        used.append("org")
    if not used or used == ["org"]:
        raise AIError("Choose a voice-over, a background sound or music to add.")

    args = ["-i", str(video)]
    for p in inputs:
        args += ["-i", str(p)]
    mix = "".join(f"[{u}]" for u in used)
    graph = ";".join(chain) + (f";{mix}amix=inputs={len(used)}:normalize=0:duration=longest,atrim=0:{seconds:.3f},alimiter=limit=0.95[a]" if len(used) > 1 else f";[{used[0]}]alimiter=limit=0.95[a]")
    say("Adding the sound to your video")
    try:
        run_ffmpeg([*args, "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{seconds:.3f}", "-movflags", "+faststart", str(dest)], seconds)
    except FfmpegError as exc:
        raise AIError(f"Could not add the sound: {exc}") from exc
    finally:
        for p in inputs:
            p.unlink(missing_ok=True)
    return {"ambience": amb if "amb" in used else "none", "voice": "voc" in used, "music": "mus" in used or amb == "calm", "warnings": warnings,
            "persona": cast["persona"] if cast else ""}
