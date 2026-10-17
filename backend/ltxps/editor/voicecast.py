"""Picks and shapes a voice to fit WHO is speaking: a girl, a woman, an old woman, a boy, a man or an old man.

The person is found from the words (a prompt such as "an old woman walks...") or, when an AI that can see pictures is connected, from the picture.
The computer only has a few voices (usually one man and one woman), so the pitch and speed of the voice are shaped to suit the age:
a child is higher and quicker, an old person lower, slower and slightly shaky.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

PERSONAS = ("girl", "boy", "woman", "man", "old_woman", "old_man")
LABELS = {"girl": "Girl (child)", "boy": "Boy (child)", "woman": "Woman (middle age)", "man": "Man (middle age)", "old_woman": "Old woman", "old_man": "Old man"}

# pitch factor (1 = the voice as it is), tempo factor, tremolo depth (0 = none), SAPI rate offset (-10..10)
SHAPE = {"girl": (1.30, 1.06, 0.0, 1), "boy": (1.42, 1.06, 0.0, 1), "woman": (1.0, 1.0, 0.0, 0), "man": (1.0, 1.0, 0.0, 0),
         "old_woman": (0.92, 0.88, 0.22, -2), "old_man": (0.86, 0.86, 0.22, -2)}

FEMALE_NAMES = ("zira", "hazel", "heera", "eva", "susan", "aria", "jenny", "female", "samantha", "karen", "moira", "tessa", "veena", "kalpana", "pallavi", "valluvar_f")
MALE_NAMES = ("david", "mark", "ravi", "george", "james", "guy", "male", "daniel", "alex", "fred", "rishi", "hemant", "valluvar")

_CHILD = re.compile(r"\b(child|kid|toddler|baby|little (girl|boy)|schoolgirl|schoolboy|young (girl|boy)|daughter|son)\b", re.I)
_OLD = re.compile(r"\b(old|elderly|aged|grand(mother|father|ma|pa|mom|dad)|granny|grandpa|senior|wrinkled|white[- ]haired|grey[- ]haired|gray[- ]haired)\b", re.I)
_FEMALE = re.compile(r"\b(woman|women|lady|girl|female|she|her|mother|mom|mum|wife|actress|queen|aunt|sister|daughter|grandmother|granny|grandma)\b", re.I)
_MALE = re.compile(r"\b(man|men|boy|male|he|his|him|father|dad|husband|actor|king|uncle|brother|son|grandfather|grandpa|gentleman)\b", re.I)


def persona_from_text(text: str) -> str | None:
    """A best guess from words alone, or None when the words do not say (a lion, a landscape...)."""
    t = text or ""
    female, male = bool(_FEMALE.search(t)), bool(_MALE.search(t))
    if not female and not male:
        return None
    is_female = female and (not male or len(_FEMALE.findall(t)) >= len(_MALE.findall(t)))
    if _CHILD.search(t):
        return "girl" if is_female else "boy"
    if _OLD.search(t):
        return "old_woman" if is_female else "old_man"
    return "woman" if is_female else "man"


VISION_QUESTION = ('Look at the main person in this picture. Reply with ONLY JSON like {"gender":"female","age":"adult"}. '
                   'gender is "female" or "male". age is "child" (under 13), "adult" (13 to 59) or "old" (60 and over). If there is no person reply {"gender":"none","age":"adult"}.')


def persona_from_vision(ask: Callable[[str], str] | None) -> str | None:
    """`ask(question)` shows the picture to a vision-capable AI and returns its reply. Any failure gives None (the caller falls back)."""
    if ask is None:
        return None
    try:
        reply = ask(VISION_QUESTION)
        m = re.search(r"\{.*?\}", reply or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001 - a model that cannot see pictures, a timeout, bad JSON: all mean "unknown"
        return None
    gender, age = str(data.get("gender", "")).lower(), str(data.get("age", "adult")).lower()
    if gender not in ("female", "male"):
        return None
    female = gender == "female"
    if age.startswith("child"):
        return "girl" if female else "boy"
    if age.startswith("old") or age.startswith("elder"):
        return "old_woman" if female else "old_man"
    return "woman" if female else "man"


def choose(persona: str, text: str = "", vision: str | None = None) -> str:
    """The persona to use: the one asked for, else the picture, else the words, else a man."""
    if persona in PERSONAS:
        return persona
    return vision or persona_from_text(text) or "man"


def _gender(persona: str) -> str:
    return "female" if persona in ("girl", "woman", "old_woman") else "male"


def pick_voice(persona: str, voices: list[str]) -> str:
    """The installed voice whose name suggests the right gender; '' (system default) when nothing fits."""
    want = FEMALE_NAMES if _gender(persona) == "female" else MALE_NAMES
    other = MALE_NAMES if _gender(persona) == "female" else FEMALE_NAMES
    for v in voices:
        low = v.lower()
        if any(n in low for n in want) and not any(n in low for n in other if n not in want):
            return v
    return ""


def plan(persona: str, voices: list[str], chosen_voice: str = "") -> dict[str, Any]:
    """Everything needed to speak as this persona: which voice, the speed, and how to shape the sound afterwards."""
    persona = persona if persona in PERSONAS else "man"
    pitch, tempo, tremolo, rate = SHAPE[persona]
    voice = chosen_voice or pick_voice(persona, voices)
    note = ""
    if not chosen_voice and voices and not voice:
        # only a voice of the other gender is installed: move its pitch towards the wanted gender
        pitch *= 1.22 if _gender(persona) == "female" else 0.82
        note = "This PC has no " + _gender(persona) + " voice, so the pitch was shifted. Install another voice in Windows Settings > Time & language > Speech for a better result."
    return {"persona": persona, "voice": voice, "rate": rate, "pitch": round(pitch, 3), "tempo": round(tempo, 3), "tremolo": tremolo, "note": note}


def audio_filter(p: dict[str, Any], sample_rate: int = 22050) -> str:
    """ffmpeg filter that changes the pitch (keeping the length) and, for old voices, adds a slight tremble. Empty when nothing changes."""
    parts = []
    pitch, tempo = float(p.get("pitch", 1.0)), float(p.get("tempo", 1.0))
    if abs(pitch - 1.0) > 0.01:
        parts.append(f"asetrate={int(sample_rate * pitch)},aresample={sample_rate},atempo={1.0 / pitch:.4f}")
    if abs(tempo - 1.0) > 0.01:
        parts.append(f"atempo={tempo:.4f}")
    if float(p.get("tremolo", 0)) > 0:
        parts.append(f"tremolo=f=5.5:d={float(p['tremolo']):.2f}")
    return ",".join(parts)
