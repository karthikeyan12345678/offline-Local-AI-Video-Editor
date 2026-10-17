"""Turns a short idea ("a dragon") into a detailed prompt a picture or video model follows well.

With a chat model connected the model writes it. With none, a fixed recipe adds the missing detail, so the button always works offline.
"""

from __future__ import annotations

import re
from typing import Callable

IMAGE_STYLE = ("highly detailed, sharp focus, intricate textures, cinematic lighting, rich colour, professional composition, "
               "8k resolution, masterpiece")
VIDEO_STYLE = "cinematic, smooth natural motion, consistent subject, soft natural lighting, shallow depth of field, high detail, 24 fps film look"

IMAGE_SYSTEM = (
    "You write prompts for AI picture generators (FLUX, Stable Diffusion, DALL·E). Rewrite the user's idea as ONE paragraph of at most 90 words. "
    "Keep every detail the user gave. Add: the subject's look and pose, setting, lighting, colour palette, camera or art style, mood. "
    "Do not add text, logos or extra people unless asked. Reply with the prompt only."
)
VIDEO_SYSTEM = (
    "You write prompts for AI video generators (LTX-Video, Kling). Rewrite the user's idea as ONE paragraph of at most 90 words in this order: "
    "subject and action, setting, camera movement (for example slow push-in, handheld, tracking shot), lighting, mood. "
    "Describe motion that fits a few seconds. Keep every detail the user gave. Reply with the prompt only."
)


def rule_based(prompt: str, kind: str = "image") -> str:
    text = re.sub(r"\s+", " ", prompt).strip().rstrip(".,; ")
    if not text:
        return text
    style = IMAGE_STYLE if kind == "image" else VIDEO_STYLE
    if style.split(",")[0] in text.lower():  # already enhanced
        return text
    return f"{text}, {style}"


STOP = {"the", "a", "an", "of", "in", "on", "at", "and", "with", "for", "to", "is", "are", "make", "create", "image", "picture", "video", "photo"}


def _keeps_idea(prompt: str, out: str) -> bool:
    """Guards against a model that answers off-topic or refuses: the new prompt must still mention something from the idea."""
    if re.match(r"(?i)\s*(i'?m sorry|i cannot|i can't|sorry|as an ai)", out):
        return False
    words = {w for w in re.findall(r"[a-z0-9]{3,}", prompt.lower()) if w not in STOP}
    return not words or any(w[:5] in out.lower() for w in words)


def enhance(prompt: str, kind: str, ask: Callable[[str, str], str] | None = None) -> tuple[str, str]:
    """Returns (better prompt, how): how is "ai", "recipe" or "none". `ask(system, user)` calls the connected chat model."""
    prompt = (prompt or "").strip()
    if len(prompt) < 3:
        return prompt, "none"
    if len(prompt) > 600:  # already long and specific: leave it alone
        return prompt, "none"
    if ask is not None:
        try:
            out = (ask(IMAGE_SYSTEM if kind == "image" else VIDEO_SYSTEM, prompt) or "").strip().strip('"').strip()
            out = re.sub(r"^(prompt|enhanced prompt)\s*:\s*", "", out, flags=re.I)
            if 12 <= len(out) <= 1200 and _keeps_idea(prompt, out):
                return out, "ai"
        except Exception:  # noqa: BLE001 - any model failure (offline, busy, bad key) falls back to the recipe
            pass
    return rule_based(prompt, kind), "recipe"
