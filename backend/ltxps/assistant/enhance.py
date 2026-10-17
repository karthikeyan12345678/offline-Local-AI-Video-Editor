"""Turns a short idea ("a dragon") into a detailed prompt a picture or video model follows well.

With a chat model connected the model writes it. With none, a fixed recipe adds the missing detail, so the button always works offline.
"""

from __future__ import annotations

import re
from typing import Callable

IMAGE_STYLE = ("ultra detailed, sharp focus, intricate textures, natural skin and material detail, professional photography, cinematic lighting, "
               "rich colour, high dynamic range, 8k resolution, masterpiece")
VIDEO_STYLE = ("shot on a 35mm cinema camera, photorealistic, sharp focus, fine natural texture, soft natural light, shallow depth of field, "
               "smooth natural motion, rich natural colour, high dynamic range, 4k film footage")
NEGATIVE_IMAGE = "blurry, out of focus, low resolution, lowres, jpeg artifacts, deformed, bad anatomy, extra fingers, extra limbs, disfigured, watermark, text, logo, oversaturated"
NEGATIVE_VIDEO = "worst quality, inconsistent motion, blurry, jittery, distorted, deformed, watermark, text, subtitles"

IMAGE_SYSTEM = (
    "You write prompts for AI picture generators (FLUX, Stable Diffusion, DALL·E). Rewrite the user's idea as ONE paragraph of 80 to 120 words. "
    "Keep every detail the user gave. Describe, in this order: the subject with specific visible detail (age, build, clothing, fur, skin or material, colours, expression, pose), "
    "the setting with foreground and background, the lighting and time of day, the camera (shot size, angle, lens) or art medium, the textures, the colour palette and the mood. "
    "Be concrete and visual; never write vague words like 'nice' or 'beautiful' alone. Do not add text, logos or extra people unless asked. Reply with the prompt only."
)
VIDEO_SYSTEM = (
    "You write prompts for AI video generators (LTX-Video). Rewrite the user's idea as ONE flowing paragraph of 90 to 130 words in the present tense, in this order: "
    "(1) the main subject with specific visible detail (age, build, clothing, fur, skin or material, colours), (2) the action as a clear sequence of movements, "
    "(3) the setting with foreground and background objects, (4) lighting and time of day, (5) the camera: shot size, angle, lens and movement (for example slow push-in, handheld, tracking), "
    "(6) the look: photorealistic cinematic footage, sharp focus, natural colour. Speech or singing is shown only as natural mouth movement. "
    "Keep every detail the user gave. No lists, no headings. Reply with the prompt only."
)

# words that tell what kind of subject the idea is about -> extra concrete detail a small model needs to draw it well
_DETAIL: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(lion|tiger|leopard|cheetah|cat|dog|wolf|fox|bear|horse|elephant|deer|monkey|animal|rabbit|cow|buffalo)\b", re.I),
     "highly detailed fur with individual strands catching the light, expressive eyes with sharp reflections, visible muscle moving naturally under the skin",
     "natural, lifelike animal movement, fur reacting to the breeze"),
    (re.compile(r"\b(bird|eagle|parrot|peacock|owl|butterfly|bee|insect)\b", re.I),
     "finely detailed feathers or wings with every barb visible, bright sharp eyes", "natural, lifelike wing and body movement"),
    (re.compile(r"\b(man|woman|girl|boy|child|kid|person|lady|people|actor|actress|farmer|dancer|soldier|king|queen|baby|old|elderly)\b", re.I),
     "natural skin texture with fine pores, detailed lifelike face and eyes, realistic fabric folds on the clothing, individual strands of hair",
     "natural blinking, breathing and subtle body movement"),
    (re.compile(r"\b(car|bike|motorcycle|truck|train|bus|ship|boat|plane|aeroplane|airplane|rocket|robot|machine)\b", re.I),
     "crisp metal and glass reflections, fine surface detail, realistic scratches and dust", "smooth, physically believable motion"),
    (re.compile(r"\b(mountain|valley|river|waterfall|forest|beach|ocean|sea|lake|desert|sky|cloud|sunset|sunrise|field|landscape|city|street|temple|village|garden)\b", re.I),
     "layered depth from foreground to horizon, fine detail in rock, foliage, water and sky", "gentle natural movement of water, wind and light"),
]


def _detail_for(text: str) -> tuple[str, str]:
    for rx, still, motion in _DETAIL:
        if rx.search(text):
            return still, motion
    return "fine, crisp detail in every surface", "smooth natural movement"


def rule_based(prompt: str, kind: str = "image") -> str:
    """A fuller prompt without any AI: the idea, then concrete detail for the kind of subject, then camera and look."""
    text = re.sub(r"\s+", " ", prompt).strip().rstrip(".,; ")
    if not text:
        return text
    if "photorealistic" in text.lower() or "ultra detailed" in text.lower():  # already enhanced
        return text
    still, motion = _detail_for(text)
    if kind == "image":
        return f"{text}, {still}, {IMAGE_STYLE}"
    return f"{text}. {still[0].upper() + still[1:]}; {motion}. Slow, smooth camera movement at eye level, {VIDEO_STYLE}."


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
