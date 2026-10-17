"""Edit the video by talking to it.

The person writes (and can attach reference pictures); the AI model answers with a short reply plus a list of
edit actions. Every action is checked here before it touches the project, so a confused model can never break
the timeline. Actions that need a long job (captions, person tracking, a new AI video) come back as `tasks`
for the app to run with its normal progress bars.
"""

from __future__ import annotations

import base64
import io
import json
import re
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from . import fonts, soundfx
from .audiofx import AUDIO_FX_IDS
from .effects import EFFECTS, FILTER_PRESETS, MASKS, MOTIONS, TRANSITIONS
from .project import TEXT_ANIM_IN, TEXT_ANIM_OUT, Project

RATIOS = {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (1080, 1080), "4:3": (1024, 768), "21:9": (1260, 540), "4:5": (864, 1080), "3:4": (810, 1080)}

# Platform presets the chat can apply ("make it for Shorts", "Instagram reel", "YouTube video"): width, height, fps.
PLATFORMS: dict[str, tuple[int, int, int]] = {
    "youtube": (1920, 1080, 30), "shorts": (1080, 1920, 30), "reels": (1080, 1920, 30), "tiktok": (1080, 1920, 30),
    "instagram_feed": (1080, 1350, 30), "instagram": (1080, 1350, 30), "square": (1080, 1080, 30),
}
PLATFORM_ALIASES = {"yt": "youtube", "youtube_shorts": "shorts", "short": "shorts", "reel": "reels", "instagram_reels": "reels", "instagram_reel": "reels", "insta_reels": "reels", "feed": "instagram_feed"}

TEXT_STYLES: dict[str, dict[str, Any]] = {
    "clean": {"font": "montserrat", "bold": True, "color": "#FFFFFF", "shadow": 0.3, "box": False},
    "subtitle": {"font": "poppins", "bold": False, "color": "#FFFFFF", "box": True, "box_opacity": 0.6, "size": 5, "y": 0.88},
    "impact": {"font": "anton", "bold": False, "color": "#FFFFFF", "stroke": 8, "shadow": 0.5, "box": False, "uppercase": True, "size": 9},
    "neon": {"font": "orbitron", "bold": True, "color": "#FFFFFF", "glow": 0.9, "glow_color": "#00E5FF", "box": False, "uppercase": True},
    "gold": {"font": "playfair", "bold": True, "color": "#FFE680", "color2": "#B8860B", "stroke": 3, "stroke_color": "#3B2A00", "shadow": 0.5, "box": False},
    "fire": {"font": "bebas", "color": "#FFF176", "color2": "#E53935", "stroke": 4, "stroke_color": "#4E0000", "glow": 0.6, "glow_color": "#FF6D00", "box": False, "uppercase": True, "size": 10},
    "comic": {"font": "bangers", "color": "#FFEB3B", "stroke": 9, "shadow": 0.6, "box": False, "rotation": -4, "uppercase": True, "size": 9},
    "cinematic": {"font": "cinzel", "bold": True, "color": "#F5F5F5", "shadow": 0.4, "box": False, "uppercase": True, "letter_spacing": 0.25},
    "tamil": {"font": "notosanstamil", "bold": True, "color": "#FFFFFF", "color2": "#FFC107", "stroke": 4, "shadow": 0.4, "box": False, "size": 8},
    "hindi": {"font": "notosansdevanagari", "bold": True, "color": "#FFFFFF", "color2": "#FF9800", "stroke": 4, "shadow": 0.4, "box": False, "size": 8},
}

CLIP_FIELDS: dict[str, tuple[float, float] | tuple[str, ...] | type] = {
    "speed": (0.25, 4), "volume": (0, 2), "muted": bool, "fade_in": (0, 10), "fade_out": (0, 10), "fit": ("fit", "fill", "stretch"),
    "zoom": (1, 4), "pan_x": (-1, 1), "pan_y": (-1, 1), "rotate": (0, 90, 180, 270), "flip_h": bool, "flip_v": bool, "blur": (0, 30), "sharpen": (0, 5),
    "vignette": bool, "denoise": bool, "reverse": bool, "preset": tuple(FILTER_PRESETS), "motion": tuple(MOTIONS), "motion_strength": (0, 1),
    "audio_fx": tuple(AUDIO_FX_IDS), "pitch": (-12, 12), "bass": (-12, 12), "treble": (-12, 12), "denoise_audio": bool, "normalize_audio": bool,
    "image_duration": (0.5, 600),
}
ADJUST_FIELDS = {"brightness": (-100, 100), "contrast": (-100, 100), "saturation": (-100, 100), "gamma": (0.3, 3), "hue": (-180, 180)}
TEXT_FIELDS = {"text", "start", "duration", "x", "y", "size", "color", "color2", "bold", "italic", "uppercase", "align", "font", "stroke", "stroke_color", "shadow", "shadow_color",
               "glow", "glow_color", "box", "box_color", "box_opacity", "letter_spacing", "line_spacing", "rotation", "opacity", "anim_in", "anim_out", "fade_in", "fade_out"}


class ChatError(ValueError):
    """Message is safe to show to the user."""


# ---------------------------------------------------------------- what the model is told
def describe(project: Project, names: dict[str, str], durations: dict[str, float]) -> str:
    c = project.canvas
    lines = [f"Video: {c.width}x{c.height} at {c.fps} fps. Music ducking {'on' if project.duck_music else 'off'}."]
    for i, cl in enumerate(project.clips, 1):
        bits = [f"speed {cl.speed}" if cl.speed != 1 else "", f"look {cl.preset}" if cl.preset != "none" else "", f"motion {cl.motion}" if cl.motion != "none" else "",
                f"transition-to-next {cl.transition.type}" if cl.transition.type != "none" else "", "reversed" if cl.reverse else "", "muted" if cl.muted else "",
                "effects " + "+".join(e.type for e in cl.effects) if cl.effects else "", "person-tracking" if cl.follow else ""]
        total = durations.get(cl.asset_id, 0)
        end = cl.trim_out or total
        lines.append(f"Clip {i}: \"{names.get(cl.asset_id, '?')}\" uses {cl.trim_in:.1f}-{end:.1f}s of a {total:.1f}s file. " + ", ".join(b for b in bits if b))
    if not project.clips:
        lines.append("There are no clips yet.")
    for i, t in enumerate(project.texts, 1):
        lines.append(f"Text {i}: \"{t.text[:40]}\" at {t.start:.1f}s for {t.duration:.1f}s font {t.font or 'auto'}")
    for i, a in enumerate(project.audio, 1):
        lines.append(f"Audio {i}: \"{names.get(a.asset_id, '?')}\" starts {a.start:.1f}s volume {a.volume} {'music' if a.is_music else 'voice'}")
    for i, d in enumerate(project.drawings, 1):
        box = _drawing_box(d)
        lines.append(f"Drawing {i}: {len(d.shapes)} shape(s) at {d.start:.1f}s for {d.duration:.1f}s" + (f", covers x {box[0]:.2f}-{box[2]:.2f}, y {box[1]:.2f}-{box[3]:.2f}" if box else ""))
    for i, im in enumerate(project.images, 1):
        lines.append(f"Picture {i}: \"{names.get(im.asset_id, '?')}\" centre ({im.x:.2f},{im.y:.2f}) width {im.size:.2f} at {im.start:.1f}s for {im.duration:.1f}s" + (f", {len(im.keys)} keyframes" if im.keys else ""))
    for i, ly in enumerate(project.layers, 1):
        bits = [f"track {ly.track}", "behind the main video" if ly.behind else "on top", f"centre ({ly.x:.2f},{ly.y:.2f}) width {ly.size:.2f}", f"opacity {ly.opacity:g}" if ly.opacity != 1 else "",
                "green/blue screen removed" if ly.chroma.enabled else "", f"{len(ly.keys)} keyframes" if ly.keys else "", "muted" if ly.muted else ""]
        lines.append(f"Layer {i}: \"{names.get(ly.asset_id, '?')}\" starts {ly.start:.1f}s, " + ", ".join(b for b in bits if b))
    for i, cl in enumerate(project.clips, 1):
        if cl.chroma.enabled:
            lines.append(f"Clip {i} has its screen colour {cl.chroma.color} removed.")
    for i, t in enumerate(project.texts, 1):
        if t.keys:
            lines.append(f"Text {i} moves along {len(t.keys)} keyframes.")
    return "\n".join(lines)


def _drawing_box(d) -> tuple[float, float, float, float] | None:
    pts = [pt for sh in d.shapes for pt in sh.points]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def system_prompt(summary: str, library: list[str], has_images: bool, attached: list[str] | None = None) -> str:
    return f"""You are the editing assistant inside VK Editor, a video editor. The person talks to you and you edit their video.
Reply with ONE JSON object and nothing else: {{"reply": "<1-3 friendly plain sentences>", "actions": [ ... ]}}.
Use as few actions as needed. If the request is only a question, use "actions": []. Never invent files. Every action MUST have a "do" field.

CURRENT PROJECT
{summary}
Library files you may refer to: {', '.join(library[:40]) or 'none'}
{('The person attached picture(s): ' + ', '.join('"' + n + '"' for n in (attached or [])) + '. You can see them. To put an attached picture ON the video use add_image with image="attached" (or its name).') if has_images else ''}

ACTIONS (target = "all" | "first" | "last" | clip number such as 2 | list of numbers | part of a file name)
{{"do":"set_canvas","ratio":"16:9|9:16|1:1|4:3|21:9|4:5","preset":"youtube|shorts|reels|instagram_feed|tiktok|square","fps":24}}
{{"do":"set_clip","target":T,"set":{{ speed 0.25-4, volume 0-2, muted, fade_in, fade_out, zoom 1-4, fit, rotate, flip_h, flip_v, blur 0-30, sharpen 0-5, vignette, denoise, reverse, preset (look), motion, motion_strength 0-1, audio_fx, pitch -12..12, bass, treble, adjust:{{brightness,contrast,saturation -100..100,gamma 0.3-3,hue}} }}}}
{{"do":"trim_clip","target":T,"start":seconds,"end":seconds}}   (positions inside the source file)
{{"do":"delete_clip","target":T}}   {{"do":"move_clip","target":T,"to":number}}
{{"do":"add_effect","target":T,"type":EFFECT,"amount":0-1}}   {{"do":"clear_effects","target":T}}
{{"do":"set_transition","target":T or "all","type":TRANSITION,"duration":0.1-3}}
{{"do":"add_text","text":"...","start":s,"duration":s,"style":STYLE,"x":0-1,"y":0-1,"size":2-30,"color":"#RRGGBB","anim_in":ANIM,"anim_out":ANIM}}   (any other text field from: font, color2, stroke, glow, shadow, box, uppercase, italic, align, rotation)
{{"do":"set_text","target":number,"set":{{...text fields...}}}}   {{"do":"delete_text","target":number or "all"}}
{{"do":"add_drawing","start":s,"duration":s,"shapes":[{{"type":"arrow|rect|ellipse|line|pen|highlight","points":[[x,y],[x,y]],"color":"#RRGGBB","width":0.3-3}}]}}  (x and y are 0-1 of the picture; arrow/line/rect/ellipse need 2 points)
{{"do":"add_image","image":"attached"|"<library picture name>","start":s,"duration":s,"anchor":"head"|"drawing"|null,"x":0-1,"y":0-1,"size":0.03-1,"rotation":-180..180,"opacity":0-1}}   (puts a picture such as a cap, logo or sticker ON the video. x,y = centre, size = width as a fraction of the video width. anchor "head" finds the face in the video and puts the picture on top of the head; anchor "drawing" puts it where the last drawing is. With no anchor give x, y and size yourself.)
{{"do":"set_image","target":number,"set":{{x,y,size,rotation,opacity,start,duration}}}}   {{"do":"delete_image","target":number or "all"}}
{{"do":"add_layer","video":"<library video or picture name>","start":s,"duration":s,"x":0-1,"y":0-1,"size":0.05-3,"track":1-8,"behind":true|false,"opacity":0-1,"rotation":-180..180,"remove_color":"green|blue|#RRGGBB"|null,"mute":true|false}}
   puts a SECOND video or picture on the timeline that plays AT THE SAME TIME as the main video (picture-in-picture, a logo, an overlay, a green-screen actor, a background). x,y = centre, size = width as a fraction of the video width.
   "behind":true puts it BEHIND the main video, which only shows where the main video is see-through (use it to replace a green screen background: first remove_background on the main clip, then add_layer with behind:true).
{{"do":"set_layer","target":number,"set":{{x,y,size,rotation,opacity,start,track,behind,volume,muted,speed,fade_in,fade_out,blur,preset,mask,mask_feather 0-1,mask_invert,effect,effect_amount 0-1,adjust:{{brightness,contrast,saturation,gamma,hue}}}}}}   {{"do":"delete_layer","target":number or "all"}}
   mask cuts the layer into a shape ("put the video in a circle / heart / star"): one of MASKS below. effect adds ONE effect from the effects list to the layer (up to 4).
{{"do":"add_sound","sound":"<a built-in sound: whoosh, pop, ding, impact, riser, rain, drum loop ...>","start":s,"volume":0-2,"loop":true|false}}   puts a free built-in sound effect, ambience or drum loop on the timeline at that second ("add a whoosh at 3 seconds", "add rain in the background", "add a drum loop"). Use it instead of a task for these.
{{"do":"remove_background","on":"clip"|"layer","target":number,"color":"green|blue|#RRGGBB","similarity":0.05-1,"blend":0-1}}   removes a green or blue screen (chroma key) so what is behind shows through. "off":true turns it off again.
{{"do":"keyframe","on":"layer"|"text"|"picture","target":number,"at":seconds on the timeline,"x":0-1,"y":0-1,"size":0.05-3,"rotation":degrees,"opacity":0-1,"ease":"smooth|linear|hold"}}   adds or changes ONE keyframe; leave out any value that should stay as it is. Between keyframes the item moves smoothly.
{{"do":"move_along","on":"layer"|"text"|"picture","target":number,"from":[x,y],"to":[x,y],"size_from":n,"size_to":n,"opacity_from":n,"opacity_to":n,"rotation_to":degrees}}   animates the item from the first to the last second it is shown ("text flies from left to right", "logo grows and fades in").   {{"do":"clear_keyframes","on":"layer"|"text"|"picture","target":number}}
{{"do":"set_audio","target":number or "music","set":{{volume 0-2, loop, fade_in, fade_out, fx, pitch, bass, treble, denoise, normalize, is_music}}}}
{{"do":"set_project","set":{{duck_music, duck_amount 0-1, master_volume 0-2, master_normalize}}}}
Long jobs (the app runs them with progress bars):
{{"do":"task","name":"captions","target":T,"language":"en|ta|hi|..."}}   {{"do":"task","name":"follow_person","target":T}}   {{"do":"task","name":"cut_silence","target":T}}
{{"do":"task","name":"scene_split","target":T}}   {{"do":"task","name":"auto_enhance","target":T}}   {{"do":"task","name":"beat_cut","every":1|2|4}}   {{"do":"task","name":"voiceover","text":"words to speak","persona":"auto|girl|boy|woman|man|old_woman|old_man"}}
{{"do":"task","name":"generate_video","prompt":"<a detailed English paragraph of 60-100 words: the subject with visible detail (age, clothing, fur or skin, colours), the action, the setting, the light, the camera shot and movement, the photorealistic look>","use_reference":true|false,"narration":"optional words a voice speaks over it","persona":"auto|girl|boy|woman|man|old_woman|old_man (who speaks; auto = from the picture and words)","ambience":"auto|none|waves|rain|wind|fire|city|night|space|calm","music":true|false}}
   narration / ambience / music make the NEW video come with a voice and background sound. Leave them out for a silent video; ambience "auto" picks a sound that fits the scene.
{{"do":"task","name":"soundtrack","target":T,"narration":"words to speak (optional)","ambience":"auto|none|waves|rain|wind|fire|city|night|space|calm","music":true|false}}
   adds a voice and/or background sound to existing clips ("add sound", "add a voice saying ...", "add rain sound", "add background music").
   use_reference=true makes the attached picture the first frame (picture-to-video). Without a picture write a full text-to-video prompt.
{{"do":"task","name":"ai_edit","target":T,"region":"drawing"|"head"|"face","prompt":"<what the marked place should look like AFTER the edit>","mode":"patch"|"track"}}
   CHANGES THE VIDEO PICTURE ITSELF with AI (repaints the frames). Use it for: remove / hide / delete / replace / change something that is IN the video (a hill, a person, a sign, a car),
   or put something onto a person or object (a cap, a hat, shoes, glasses, a jacket, a logo). region "drawing" = the place the person marked with a drawing (use when there is a drawing);
   "head" = the person's head/hair (caps, hats); "face" = the face. prompt = a short English picture description of the RESULT, e.g. remove a hill -> "flat green grass field and clear sky, nothing else";
   remove a person -> "empty street, same background, nobody there"; cap -> "a white baseball cap on the head"; shoes -> "pair of black sneakers on the feet".
   mode "patch" for a still camera and things that do not move (default); "track" when the person or camera moves (slower).
   NEVER use add_image for these. add_image is only for putting a picture file the person attached or named (a logo, sticker, photo) on top of the video.

VALUES
transitions: none, random, {', '.join(sorted(t for t in TRANSITIONS if t not in ('none', 'random')))}
looks: {', '.join(k for k in FILTER_PRESETS if k != 'none')}
effects: {', '.join(EFFECTS)}
motions: {', '.join(m for m in MOTIONS if m != 'none')}
voice and audio styles (set_clip audio_fx / set_audio fx): {', '.join(a for a in AUDIO_FX_IDS if a != 'none')}
built-in sounds (add_sound): {', '.join(soundfx.SOUNDS)}
masks: {', '.join(m for m in MASKS if m != 'none')}
text styles: {', '.join(TEXT_STYLES)}   text animations in: {', '.join(TEXT_ANIM_IN)}   out: {', '.join(TEXT_ANIM_OUT)}
fonts (examples): {', '.join(list(fonts.catalog())[:30])}
Times are seconds on the final timeline. Use numbers, never words, for numbers. Keep any text in the language the person wrote it in."""


# ---------------------------------------------------------------- reading the model's answer
def parse_answer(text: str) -> dict[str, Any]:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()
    for cand in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t else ""):
        if not cand:
            continue
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                acts = data.get("actions") or []
                if isinstance(acts, dict):
                    acts = [acts]
                return {"reply": str(data.get("reply", "")).strip(), "actions": [a for a in acts if isinstance(a, dict)], "ok": True}
        except ValueError:
            continue
    return {"reply": t[:600] or "I could not understand that. Please try again in other words.", "actions": [], "ok": False}


_EDIT_WORDS = re.compile(r"\b(layer|overlay|green|blue screen|chroma|keyframe|animate|background|picture-in-picture|add|put|place|make|change|set|remove|delete|cut|trim|draw|apply|insert|replace|move|speed|slow|zoom|crop|caption|subtitle|title|text|cap|hat|logo|sticker|vertical|fade|filter|blur|mute|volume|sound|whoosh|music|beat|loop|rain|mask|circle|heart|star|shape|effect|glitch|look)\b", re.I)


def looks_like_edit_request(text: str) -> bool:
    """True when the person is asking for a change (so an answer with no actions is worth asking again)."""
    return bool(_EDIT_WORDS.search(text or ""))


# ---------------------------------------------------------------- applying actions
def _targets(spec: Any, n: int, names: list[str]) -> list[int]:
    if spec in (None, "", "all", "every", "clips"):
        return list(range(n))
    if spec == "first":
        return [0] if n else []
    if spec == "last":
        return [n - 1] if n else []
    if isinstance(spec, bool):
        return []
    if isinstance(spec, (int, float)):
        return [int(spec) - 1] if 1 <= int(spec) <= n else []
    if isinstance(spec, list):
        return sorted({int(v) - 1 for v in spec if isinstance(v, (int, float)) and 1 <= int(v) <= n})
    if isinstance(spec, str):
        if spec.isdigit():
            return _targets(int(spec), n, names)
        s = spec.lower()
        return [i for i, nm in enumerate(names) if s in nm.lower()]
    return []


def _check(key: str, value: Any, rule: Any) -> Any:
    if rule is bool:
        return bool(value)
    if isinstance(rule, tuple) and rule and isinstance(rule[0], str):
        if value not in rule:
            raise ValueError(f"{key} must be one of {', '.join(rule[:8])}…")
        return value
    if isinstance(rule, tuple) and len(rule) > 2:  # a list of allowed numbers (rotate)
        if value not in rule:
            raise ValueError(f"{key} must be one of {rule}")
        return value
    lo, hi = rule
    v = float(value)
    return max(lo, min(hi, v))


class Applier:
    def __init__(self, project: Project, names: dict[str, str], library: dict[str, str], ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}  # attached: [asset ids]; assets: {id: Asset}; face: callable(path, t)
        self.p = project.model_dump()
        self.names = names  # asset id -> name
        self.library = library  # lower-case name -> asset id
        self.applied: list[str] = []
        self.skipped: list[str] = []
        self.tasks: list[dict[str, Any]] = []

    # --- helpers
    def clip_names(self) -> list[str]:
        return [self.names.get(c["asset_id"], "") for c in self.p["clips"]]

    def pick(self, a: dict[str, Any]) -> list[int]:
        idx = _targets(a.get("target", "all"), len(self.p["clips"]), self.clip_names())
        if not idx:
            raise ValueError("no clip matched " + str(a.get("target")))
        return idx

    def validated(self, mutate) -> None:
        backup = json.loads(json.dumps(self.p))
        try:
            mutate()
            Project.model_validate(self.p)
        except Exception:
            self.p = backup
            raise

    # --- actions
    def run(self, a: dict[str, Any]) -> None:
        do = str(a.get("do") or a.get("action") or a.get("type") or "").strip()
        do = ALIASES.get(do, do)
        if not do:
            raise ValueError("an instruction without a clear action was ignored")
        fn = getattr(self, "a_" + do, None)
        if fn is None:
            raise ValueError(f"unknown action '{do}'")
        fn(a)

    def a_set_canvas(self, a):
        preset = str(a.get("preset") or "").strip().lower().replace(" ", "_").replace("-", "_")
        preset = PLATFORM_ALIASES.get(preset, preset)

        def m():
            if preset:
                if preset not in PLATFORMS:
                    raise ValueError("unknown preset " + str(a.get("preset")))
                w, h, f = PLATFORMS[preset]
                self.p["canvas"].update(width=w, height=h, fps=f)
            elif a.get("ratio") in RATIOS:
                w, h = RATIOS[a["ratio"]]
                self.p["canvas"].update(width=w, height=h)
            elif "ratio" in a:
                raise ValueError("unknown ratio " + str(a["ratio"]))
            if "fps" in a:
                self.p["canvas"]["fps"] = int(max(1, min(60, float(a["fps"]))))
        self.validated(m)
        self.applied.append("Changed the video size" + (f" for {preset}" if preset else f" to {a['ratio']}" if a.get("ratio") else ""))

    def a_set_clip(self, a):
        idx = self.pick(a)
        patch = a.get("set") or {}
        if not isinstance(patch, dict) or not patch:
            raise ValueError("nothing to set")

        def m():
            for i in idx:
                c = self.p["clips"][i]
                for k, v in patch.items():
                    if k == "adjust" and isinstance(v, dict):
                        for ak, av in v.items():
                            if ak in ADJUST_FIELDS:
                                c["adjust"][ak] = _check(ak, av, ADJUST_FIELDS[ak])
                    elif k == "transition" and isinstance(v, dict):
                        c["transition"] = {"type": str(v.get("type", c["transition"]["type"])), "duration": float(v.get("duration", c["transition"]["duration"]))}
                    elif k in CLIP_FIELDS:
                        c[k] = _check(k, v, CLIP_FIELDS[k])
                        if k == "rotate":
                            c[k] = int(c[k])
                    else:
                        raise ValueError(f"cannot set '{k}'")
        self.validated(m)
        self.applied.append(f"Updated {len(idx)} clip{'s' if len(idx) > 1 else ''}: " + ", ".join(patch))

    def a_trim_clip(self, a):
        idx = self.pick(a)

        def m():
            for i in idx:
                c = self.p["clips"][i]
                if "start" in a:
                    c["trim_in"] = max(0.0, float(a["start"]))
                if "end" in a:
                    c["trim_out"] = max(0.0, float(a["end"]))
                if c["trim_out"] and c["trim_out"] <= c["trim_in"] + 0.05:
                    raise ValueError("the end must be after the start")
        self.validated(m)
        self.applied.append("Trimmed the clip")

    def a_delete_clip(self, a):
        idx = self.pick(a)
        self.p["clips"] = [c for i, c in enumerate(self.p["clips"]) if i not in idx]
        self.applied.append(f"Removed {len(idx)} clip{'s' if len(idx) > 1 else ''}")

    def a_move_clip(self, a):
        (i,) = self.pick(a)[:1]
        to = int(a.get("to", 1)) - 1
        clips = self.p["clips"]
        c = clips.pop(i)
        clips.insert(max(0, min(len(clips), to)), c)
        self.applied.append("Moved a clip")

    def a_add_effect(self, a):
        idx = self.pick(a)

        def m():
            for i in idx:
                effs = self.p["clips"][i]["effects"]
                effs.append({"type": str(a.get("type")), "amount": max(0.0, min(1.0, float(a.get("amount", 0.5))))})
                del effs[:-6]
        self.validated(m)
        self.applied.append(f"Added the {a.get('type')} effect")

    def a_clear_effects(self, a):
        for i in self.pick(a):
            self.p["clips"][i]["effects"] = []
        self.applied.append("Removed effects")

    def a_set_transition(self, a):
        n = len(self.p["clips"])
        idx = list(range(max(0, n - 1))) if a.get("target", "all") == "all" else [i for i in self.pick(a) if i < n - 1]

        def m():
            for i in idx:
                self.p["clips"][i]["transition"] = {"type": str(a.get("type", "fade")), "duration": max(0.1, min(3.0, float(a.get("duration", 0.6))))}
        if not idx:
            raise ValueError("there is no cut to put a transition on")
        self.validated(m)
        self.applied.append(f"Added {a.get('type')} transition{'s' if len(idx) > 1 else ''}")

    def a_add_text(self, a):
        style = dict(TEXT_STYLES.get(str(a.get("style", "")), {}))
        base = {"id": uuid.uuid4().hex[:8], "text": str(a.get("text", ""))[:500], "start": 0.0, "duration": 3.0}
        extra = {k: v for k, v in a.items() if k in TEXT_FIELDS and k != "text"}
        if not base["text"].strip():
            raise ValueError("the text is empty")

        def m():
            t = {**base, **style, **extra}
            self.p["texts"].append(t)
            if len(self.p["texts"]) > 200:
                raise ValueError("too many texts")
        self.validated(m)
        self.applied.append(f"Added the text “{base['text'][:30]}”")

    def a_set_text(self, a):
        i = int(a.get("target", 0)) - 1
        if not 0 <= i < len(self.p["texts"]):
            raise ValueError("no such text")
        patch = {k: v for k, v in (a.get("set") or {}).items() if k in TEXT_FIELDS}
        st = TEXT_STYLES.get(str((a.get("set") or {}).get("style", "")))
        self.validated(lambda: self.p["texts"][i].update({**(st or {}), **patch}))
        self.applied.append("Changed a text")

    def a_delete_text(self, a):
        if a.get("target") == "all":
            self.p["texts"] = []
        else:
            i = int(a.get("target", 0)) - 1
            if not 0 <= i < len(self.p["texts"]):
                raise ValueError("no such text")
            self.p["texts"].pop(i)
        self.applied.append("Removed text")

    def a_add_drawing(self, a):
        shapes = []
        for s in a.get("shapes") or []:
            pts = [(float(x), float(y)) for x, y in s.get("points", [])]
            shapes.append({"type": s.get("type", "arrow"), "points": pts, "color": s.get("color", "#FF3B30"), "width": max(0.1, min(10, float(s.get("width", 0.8))))})
        if not shapes:
            raise ValueError("no shapes")
        d = {"id": uuid.uuid4().hex[:8], "start": max(0.0, float(a.get("start", 0))), "duration": max(0.3, float(a.get("duration", 3))), "shapes": shapes}
        self.validated(lambda: self.p["drawings"].append(d))
        self.applied.append(f"Drew {len(shapes)} shape{'s' if len(shapes) > 1 else ''} on the picture")

    # --- pictures on the video
    def _pick_image(self, a) -> tuple[str, str]:
        want = str(a.get("image") or a.get("asset") or "attached").strip().lower()
        attached = list(self.ctx.get("attached") or [])
        if want in ("attached", "the attached picture", "reference", "picture", "image", "") or want.startswith("attached"):
            m = re.search(r"(\d+)", want)
            k = int(m.group(1)) - 1 if m else 0
            if not attached:
                raise ValueError("no picture is attached — attach the picture first")
            aid = attached[min(max(k, 0), len(attached) - 1)]
            return aid, self.names.get(aid, "picture")
        for nm, aid in self.library.items():
            if want in nm:
                return aid, self.names.get(aid, nm)
        if attached:
            return attached[0], self.names.get(attached[0], "picture")
        raise ValueError(f"no picture called '{a.get('image')}' in the library")

    def _face_on_canvas(self, t: float) -> tuple[float, float, float] | None:
        """Face (centre x, top y, width) as 0..1 of the video at timeline second t, or None."""
        fn, assets = self.ctx.get("face"), self.ctx.get("assets") or {}
        if fn is None:
            return None
        cw, ch = self.p["canvas"]["width"], self.p["canvas"]["height"]
        pos = 0.0
        for c in self.p["clips"]:
            a = assets.get(c["asset_id"])
            if a is None:
                continue
            span = self._clip_span(c)
            if pos <= t < pos + span or c is self.p["clips"][-1]:
                src_t = c["trim_in"] + max(0.0, t - pos) * c["speed"]
                try:
                    box = fn(a.path, src_t)
                except Exception:  # noqa: BLE001 - no OpenCV / model / bad frame: place by hand instead
                    box = None
                if not box or not a.width or not a.height:
                    return None
                if c["fit"] == "fill":
                    sc = max(cw / a.width, ch / a.height)
                    sx = sy = sc
                elif c["fit"] == "stretch":
                    sx, sy = cw / a.width, ch / a.height
                else:
                    sx = sy = min(cw / a.width, ch / a.height)
                dw, dh = a.width * sx, a.height * sy
                ox, oy = (cw - dw) / 2, (ch - dh) / 2
                return (ox + (box["x"] + box["w"] / 2) * dw) / cw, (oy + box["y"] * dh) / ch, box["w"] * dw / cw
            pos += span
        return None

    def _clip_span(self, c: dict[str, Any]) -> float:
        a = (self.ctx.get("assets") or {}).get(c["asset_id"])
        if a is None:
            return 0.0
        if a.kind == "image":
            return float(c["image_duration"])
        return max(0.1, ((c["trim_out"] or a.duration) - c["trim_in"]) / max(0.01, c["speed"]))

    def a_add_image(self, a):
        aid, nm = self._pick_image(a)
        cw, ch = self.p["canvas"]["width"], self.p["canvas"]["height"]
        asset = (self.ctx.get("assets") or {}).get(aid)
        ratio = (asset.height / asset.width) if asset is not None and asset.width else 1.0  # picture height / width
        start = max(0.0, float(a.get("start") or 0))
        length = sum(self._clip_span(c) for c in self.p["clips"])
        dur = float(a["duration"]) if a.get("duration") else (max(1.0, length - start) if length else 3.0)
        x, y, size = a.get("x"), a.get("y"), a.get("size")
        note = ""
        anchor = str(a.get("anchor") or "").lower()
        if anchor in ("head", "face", "hair", "top_of_head"):
            f = self._face_on_canvas(start + 0.3)
            if f:
                fx, ftop, fw = f
                size = float(size) if size else max(0.05, min(0.9, fw * 1.5))
                img_h = size * cw / ch * ratio  # picture height as a fraction of the video height
                face_h = fw * cw / ch * 1.25
                x, y = fx, ftop + 0.12 * face_h - img_h / 2  # bottom edge just over the forehead
                note = " on the head"
            else:
                note = " (I could not find a face — drag it to the right place)"
        elif anchor in ("drawing", "marked", "mark"):
            boxes = [b for b in (_drawing_box_dict(d) for d in self.p["drawings"]) if b]
            if boxes:
                b = boxes[-1]
                x, y = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                size = float(size) if size else max(0.05, min(1.0, (b[2] - b[0]) * 1.2))
                note = " where you marked"
        if x is None or y is None:
            x, y = 0.5, 0.35
        op = a.get("opacity")
        ov = {"id": uuid.uuid4().hex[:8], "asset_id": aid, "start": start, "duration": max(0.3, dur), "x": float(x), "y": float(y), "size": max(0.03, min(1.5, float(size or 0.25))),
              "rotation": float(a.get("rotation") or 0), "opacity": 1.0 if op is None else max(0.0, min(1.0, float(op)))}
        self.validated(lambda: self.p["images"].append(ov))
        self.applied.append(f"Put the picture “{nm[:30]}” on the video{note}")

    def a_set_image(self, a):
        i = int(a.get("target", 0)) - 1
        if not 0 <= i < len(self.p["images"]):
            raise ValueError("no such picture on the video")
        ok = {"x", "y", "size", "rotation", "opacity", "start", "duration"}
        self.validated(lambda: self.p["images"][i].update({k: float(v) for k, v in (a.get("set") or {}).items() if k in ok}))
        self.applied.append("Changed a picture on the video")

    def a_delete_image(self, a):
        if a.get("target") == "all":
            self.p["images"] = []
        else:
            i = int(a.get("target", 0)) - 1
            if not 0 <= i < len(self.p["images"]):
                raise ValueError("no such picture on the video")
            self.p["images"].pop(i)
        self.applied.append("Removed a picture from the video")

    # --- layers (a second video or picture at the same time), screen removal and keyframes
    def _asset(self, aid: str):
        return (self.ctx.get("assets") or {}).get(aid)

    def _pick_media(self, a) -> tuple[str, str]:
        want = str(a.get("video") or a.get("image") or a.get("asset") or a.get("file") or "").strip().lower()
        attached = list(self.ctx.get("attached") or [])
        if not want or want.startswith("attached"):
            if attached:
                return attached[0], self.names.get(attached[0], "picture")
            raise ValueError("say which library video or picture to use")
        for nm, aid in self.library.items():
            if want in nm:
                asset = self._asset(aid)
                if asset is None or asset.kind in ("video", "image"):
                    return aid, self.names.get(aid, nm)
        raise ValueError(f"no video or picture called '{a.get('video') or a.get('image')}' in the library")

    @staticmethod
    def _screen(color: Any) -> str:
        c = str(color or "green").strip().lower()
        if re.fullmatch(r"#?[0-9a-f]{6}", c):
            return "#" + c.lstrip("#").upper()
        return {"blue": "#0047BB", "bluescreen": "#0047BB", "blue screen": "#0047BB", "green": "#00B140", "greenscreen": "#00B140", "green screen": "#00B140", "white": "#FFFFFF", "black": "#000000"}.get(c, "#00B140")

    def _layer_index(self, a) -> int:
        t = a.get("target")
        n = len(self.p["layers"])
        if t in (None, "", "last") and n:
            return n - 1
        if t == "first" and n:
            return 0
        try:
            i = int(t) - 1
        except (TypeError, ValueError):
            raise ValueError("which layer? use its number")
        if not 0 <= i < n:
            raise ValueError("no such layer")
        return i

    def a_add_layer(self, a):
        aid, nm = self._pick_media(a)
        asset = self._asset(aid)
        keyed = a.get("remove_color") or a.get("chroma")
        full = bool(keyed) or bool(a.get("behind"))
        x, y = a.get("x"), a.get("y")
        size = a.get("size")
        ly: dict[str, Any] = {"id": uuid.uuid4().hex[:8], "asset_id": aid, "start": max(0.0, float(a.get("start") or 0)), "behind": bool(a.get("behind")),
                              "x": 0.5 if x is None else float(x), "y": 0.5 if y is None else float(y), "size": max(0.05, min(3.0, float(size))) if size else (1.0 if full else 0.35)}
        if x is None and y is None and not full:
            ly["x"], ly["y"] = 0.8, 0.8
        if a.get("track"):
            ly["track"] = int(max(1, min(8, float(a["track"]))))
        else:
            ly["track"] = min(8, 1 + sum(1 for q in self.p["layers"] if bool(q.get("behind")) == ly["behind"]))
        if a.get("opacity") is not None:
            ly["opacity"] = max(0.0, min(1.0, float(a["opacity"])))
        if a.get("rotation"):
            ly["rotation"] = max(-720.0, min(720.0, float(a["rotation"])))
        if a.get("mute") or a.get("muted"):
            ly["muted"] = True
        if a.get("duration"):
            d = max(0.2, float(a["duration"]))
            if asset is not None and asset.kind == "image":
                ly["image_duration"] = d
            else:
                ly["trim_out"] = d * float(a.get("speed") or 1) + float(a.get("trim_in") or 0)
        if keyed:
            ly["chroma"] = {"enabled": True, "color": self._screen(keyed)}
        self.validated(lambda: self.p["layers"].append(ly))
        self.applied.append(f"Added “{nm[:30]}” as a layer" + (" behind the video" if ly["behind"] else "") + (" with the screen colour removed" if keyed else ""))

    def a_set_layer(self, a):
        i = self._layer_index(a)
        ok = {"x", "y", "size", "rotation", "opacity", "start", "track", "behind", "volume", "muted", "speed", "fade_in", "fade_out", "blur", "preset", "trim_in", "trim_out", "image_duration", "mask", "mask_feather", "mask_invert"}
        sets = a.get("set") or {}
        patch = {k: v for k, v in sets.items() if k in ok}
        adj = sets.get("adjust")
        fx = str(sets.get("effect") or "").strip()
        if fx and fx not in EFFECTS:
            raise ValueError(f"unknown effect '{fx}'")
        if "mask" in patch:
            patch["mask"] = "none" if str(patch["mask"]).lower() in ("", "off", "none", "false") else str(patch["mask"]).lower()
            if patch["mask"] not in MASKS:
                raise ValueError(f"unknown mask '{patch['mask']}'")

        def m():
            ly = self.p["layers"][i]
            for k, v in patch.items():
                ly[k] = int(v) if k == "track" else (bool(v) if k in ("behind", "muted", "mask_invert") else (str(v) if k in ("preset", "mask") else float(v)))
            if fx:
                ly.setdefault("effects", []).append({"type": fx, "amount": max(0.0, min(1.0, float(sets.get("effect_amount", 0.6))))})
            if isinstance(adj, dict):
                for ak, av in adj.items():
                    if ak in ADJUST_FIELDS:
                        ly["adjust"][ak] = _check(ak, av, ADJUST_FIELDS[ak])
        if not patch and not fx and not isinstance(adj, dict):
            raise ValueError("nothing to set")
        self.validated(m)
        self.applied.append(f"Changed layer {i + 1}: " + ", ".join(list(patch) + (["effect"] if fx else []) + (["adjust"] if adj else [])))

    def a_add_sound(self, a):
        q = str(a.get("sound") or a.get("name") or a.get("effect") or "")
        sid = soundfx.find(q)
        if not sid:
            raise ValueError(f"I have no built-in sound called '{q}'. Try: whoosh, pop, ding, impact, riser, rain, wind, drum loop")
        make = self.ctx.get("sound")
        if make is None:
            raise ValueError("built-in sounds are not available here")
        asset = make(sid)
        self.names[asset.id] = asset.name
        label, group, dur, _ = soundfx.SOUNDS[sid]
        ambient = group in ("Ambience", "Music and loops")
        loop = bool(a.get("loop")) or (ambient and a.get("loop") is None)
        ac = {"id": uuid.uuid4().hex[:8], "asset_id": asset.id, "start": max(0.0, float(a.get("start") if a.get("start") is not None else (a.get("at") or 0))),
              "volume": max(0.0, min(2.0, float(a.get("volume") if a.get("volume") is not None else (0.5 if ambient else 1.0)))), "loop": loop, "is_music": ambient,
              "fade_in": 0.5 if ambient else 0.0, "fade_out": 1.0 if ambient else 0.0}
        self.validated(lambda: self.p["audio"].append(ac))
        self.applied.append(f"Added the sound “{label}” at {ac['start']:.1f} s" + (" (repeats to the end)" if loop else ""))

    def a_delete_layer(self, a):
        if a.get("target") == "all":
            self.p["layers"] = []
        else:
            self.p["layers"].pop(self._layer_index(a))
        self.applied.append("Removed a layer")

    def a_remove_background(self, a):
        on = str(a.get("on") or ("layer" if self.p["layers"] and not a.get("clip") else "clip")).lower()
        off = bool(a.get("off"))
        patch = {"enabled": not off}
        if not off:
            patch["color"] = self._screen(a.get("color"))
            if a.get("similarity") is not None:
                patch["similarity"] = max(0.01, min(1.0, float(a["similarity"])))
            if a.get("blend") is not None:
                patch["blend"] = max(0.0, min(1.0, float(a["blend"])))

        def m():
            if on == "layer":
                self.p["layers"][self._layer_index(a)]["chroma"].update(patch)
            else:
                for i in self.pick(a):
                    self.p["clips"][i]["chroma"].update(patch)
        self.validated(m)
        self.applied.append("Turned the screen removal off" if off else "Removed the green/blue screen so what is behind shows through")

    def _keyed(self, a) -> tuple[dict[str, Any], str]:
        on = str(a.get("on") or "layer").lower().replace("image", "picture")
        key = {"layer": "layers", "text": "texts", "picture": "images"}.get(on)
        if key is None:
            raise ValueError("keyframes work on a layer, a text or a picture")
        try:
            i = int(a.get("target") if a.get("target") is not None else len(self.p[key])) - 1
        except (TypeError, ValueError):
            raise ValueError("which one? use its number")
        if not 0 <= i < len(self.p[key]):
            raise ValueError(f"no such {on}")
        return self.p[key][i], on

    @staticmethod
    def _rest(item: dict[str, Any], on: str) -> dict[str, float]:
        base = {"x": item.get("x", 0.5), "y": item.get("y", 0.5), "size": item.get("size", 0.5) if on != "text" else 0.5, "rotation": item.get("rotation", 0) if on != "text" else 0, "opacity": item.get("opacity", 1)}
        return {k: float(v) for k, v in base.items()}

    def _value_at(self, item: dict[str, Any], on: str, rel: float) -> dict[str, float]:
        """What the item looks like `rel` seconds after it starts (so a new keyframe starts from the current look)."""
        keys = sorted(item.get("keys") or [], key=lambda k: k["t"])
        rest = self._rest(item, on)
        if not keys:
            return rest
        if rel <= keys[0]["t"]:
            return {f: float(keys[0][f]) for f in rest}
        if rel >= keys[-1]["t"]:
            return {f: float(keys[-1][f]) for f in rest}
        for k0, k1 in zip(keys, keys[1:]):
            if k0["t"] <= rel <= k1["t"]:
                span = max(1e-6, k1["t"] - k0["t"])
                p = (rel - k0["t"]) / span
                if k0.get("ease", "smooth") == "smooth":
                    p = p * p * (3 - 2 * p)
                elif k0.get("ease") == "hold":
                    p = 0.0
                return {f: float(k0[f]) + (float(k1[f]) - float(k0[f])) * p for f in rest}
        return rest

    def _length(self, item: dict[str, Any], on: str) -> float:
        if on != "layer":
            return float(item.get("duration", 3))
        asset = self._asset(item["asset_id"])
        if asset is None:
            return 4.0
        if asset.kind == "image":
            return float(item.get("image_duration", 4))
        end = item.get("trim_out") or asset.duration
        return max(0.1, (min(end, asset.duration) - item.get("trim_in", 0)) / max(0.01, item.get("speed", 1)))

    def a_keyframe(self, a):
        item, on = self._keyed(a)
        rel = max(0.0, float(a.get("at") or 0) - float(item.get("start", 0)))
        vals = self._value_at(item, on, rel)
        for f in vals:
            if a.get(f) is not None:
                vals[f] = float(a[f])
        ease = str(a.get("ease") or "smooth")
        if ease not in ("smooth", "linear", "hold"):
            ease = "smooth"

        def m():
            keys = [k for k in (item.get("keys") or []) if abs(k["t"] - rel) > 0.02]
            keys.append({"t": round(rel, 3), **vals, "ease": ease})
            item["keys"] = sorted(keys, key=lambda k: k["t"])[:200]
        self.validated(m)
        self.applied.append(f"Added a keyframe at {a.get('at') or 0}s")

    def a_move_along(self, a):
        item, on = self._keyed(a)
        rest = self._rest(item, on)
        end = max(0.2, self._length(item, on))
        fr, to = a.get("from"), a.get("to")

        def pt(v, fallback):
            try:
                return float(v[0]), float(v[1])
            except (TypeError, ValueError, IndexError, KeyError):
                return fallback
        x0, y0 = pt(fr, (rest["x"], rest["y"]))
        x1, y1 = pt(to, (x0, y0))
        k0 = {"t": 0.0, "x": x0, "y": y0, "size": float(a.get("size_from", rest["size"])), "rotation": float(a.get("rotation_from", rest["rotation"])), "opacity": float(a.get("opacity_from", rest["opacity"])), "ease": "smooth"}
        k1 = {"t": round(end, 3), "x": x1, "y": y1, "size": float(a.get("size_to", k0["size"])), "rotation": float(a.get("rotation_to", k0["rotation"])), "opacity": float(a.get("opacity_to", k0["opacity"])), "ease": "smooth"}
        self.validated(lambda: item.update(keys=[k0, k1]))
        self.applied.append("Animated it from the start to the end of its time")

    def a_clear_keyframes(self, a):
        item, _ = self._keyed(a)
        item["keys"] = []
        self.applied.append("Removed the keyframes")

    def a_set_audio(self, a):
        tgt = a.get("target", "music")
        audio = self.p["audio"]
        idx = [i for i, x in enumerate(audio) if x.get("is_music")] if tgt == "music" else _targets(tgt, len(audio), [self.names.get(x["asset_id"], "") for x in audio])
        if not idx:
            raise ValueError("no audio block matched")
        ok = {"volume", "loop", "fade_in", "fade_out", "fx", "pitch", "bass", "treble", "denoise", "normalize", "is_music"}

        def m():
            for i in idx:
                audio[i].update({k: v for k, v in (a.get("set") or {}).items() if k in ok})
        self.validated(m)
        self.applied.append("Changed the audio")

    def a_set_project(self, a):
        ok = {"duck_music", "duck_amount", "master_volume", "master_normalize"}
        self.validated(lambda: self.p.update({k: v for k, v in (a.get("set") or {}).items() if k in ok}))
        self.applied.append("Changed the sound settings")

    def _canvas_to_source(self, c: dict[str, Any], pts: list[list[float]]) -> list[list[float]]:
        """Drawings are 0-1 of the video canvas; the repaint works on the source frame, which may be letter-boxed or cropped on the canvas."""
        asset = (self.ctx.get("assets") or {}).get(c["asset_id"])
        cw, ch = self.p["canvas"]["width"], self.p["canvas"]["height"]
        if asset is None or not asset.width or not asset.height:
            return pts
        if c["fit"] == "fill":
            sc = max(cw / asset.width, ch / asset.height)
            sx = sy = sc
        elif c["fit"] == "stretch":
            sx, sy = cw / asset.width, ch / asset.height
        else:
            sx = sy = min(cw / asset.width, ch / asset.height)
        dw, dh = asset.width * sx, asset.height * sy
        ox, oy = (cw - dw) / 2, (ch - dh) / 2
        return [[min(1.0, max(0.0, (p[0] * cw - ox) / dw)), min(1.0, max(0.0, (p[1] * ch - oy) / dh))] for p in pts]

    def _ai_edit_task(self, a: dict[str, Any]) -> dict[str, Any]:
        prompt = str(a.get("prompt") or "").strip()[:400]
        if len(prompt) < 3:
            raise ValueError("I need a short description of what should be there after the change")
        region = str(a.get("region") or "").lower()
        region = {"hair": "head", "cap": "head", "hat": "head", "marked": "drawing", "mark": "drawing", "box": "drawing"}.get(region, region)
        drawings = [d for d in self.p["drawings"] if d.get("shapes")]
        if region not in ("drawing", "head", "face"):
            region = "drawing" if drawings else "head"
        if region == "drawing" and not drawings:
            raise ValueError("draw a box or circle on the video where the change should happen (use the Draw tool), then ask again")
        clips = self.p["clips"]
        if not clips:
            raise ValueError("there is no clip to edit")
        idx = None
        if a.get("target") not in (None, "", "all"):
            got = _targets(a.get("target"), len(clips), [self.names.get(c["asset_id"], "") for c in clips])
            idx = got[0] if got else None
        d = drawings[-1] if region == "drawing" else None
        if idx is None:  # the clip that is playing when the person drew
            at = float(d["start"]) if d else float(a.get("start") or 0)
            pos = 0.0
            idx = len(clips) - 1
            for i, c in enumerate(clips):
                span = self._clip_span(c)
                if pos <= at < pos + span:
                    idx = i
                    break
                pos += span
        c = clips[idx]
        asset = (self.ctx.get("assets") or {}).get(c["asset_id"])
        if asset is None or asset.kind not in ("video", "image"):
            raise ValueError("this works on video or picture clips")
        out: dict[str, Any] = {"clips": [c["id"]], "prompt": prompt, "part": region if region in ("head", "face") else "", "mode": "track" if str(a.get("mode")) == "track" or region != "drawing" else "patch", "shapes": []}
        if d:
            out["shapes"] = [{**sh, "points": self._canvas_to_source(c, sh.get("points", []))} for sh in d["shapes"]]
            out["drawing_ids"] = [d["id"]]
        return out

    def a_ai_edit(self, a):
        self.a_task({**a, "name": "ai_edit"})

    def a_task(self, a):
        name = str(a.get("name", ""))
        if name in ("remove_object", "erase", "inpaint"):
            name = "ai_edit"
        allowed = {"captions", "follow_person", "cut_silence", "scene_split", "auto_enhance", "beat_cut", "voiceover", "generate_video", "ai_edit", "soundtrack"}
        if name not in allowed:
            raise ValueError(f"unknown task '{name}'")
        task: dict[str, Any] = {"name": name}
        if name in ("captions", "follow_person", "cut_silence", "scene_split", "auto_enhance", "soundtrack"):
            idx = self.pick(a)
            task["clips"] = [self.p["clips"][i]["id"] for i in idx]
        if name == "captions":
            task["language"] = str(a.get("language", ""))[:5]
        if name == "beat_cut":
            task["every"] = int(a.get("every", 2)) if int(a.get("every", 2)) in (1, 2, 4, 8) else 2
        if name in ("voiceover", "generate_video", "soundtrack"):
            from .voicecast import PERSONAS
            pers = str(a.get("persona") or "auto").strip().lower().replace(" ", "_")
            task["persona"] = pers if pers in PERSONAS else "auto"
        if name == "voiceover":
            task["text"] = str(a.get("text", ""))[:2000]
            if not task["text"].strip():
                raise ValueError("nothing to say")
        if name in ("generate_video", "soundtrack"):
            from .soundtrack import AMBIENCES
            amb = str(a.get("ambience") or ("auto" if name == "soundtrack" else "none")).strip().lower()
            task["narration"] = str(a.get("narration") or "")[:2000]
            task["ambience"] = amb if amb in (*AMBIENCES, "auto", "none") else "auto"
            task["music"] = bool(a.get("music"))
            if name == "soundtrack" and not (task["narration"].strip() or task["ambience"] != "none" or task["music"]):
                raise ValueError("nothing to add: say what voice or sound you want")
        if name == "generate_video":
            task["prompt"] = str(a.get("prompt", ""))[:1500]
            task["use_reference"] = bool(a.get("use_reference"))
            if not task["prompt"].strip():
                raise ValueError("the video description is empty")
        if name == "ai_edit":
            task.update(self._ai_edit_task(a))
        self.tasks.append(task)
        self.applied.append({"ai_edit": "Will repaint the video with AI (" + str(task.get("prompt", ""))[:40] + ")", "captions": "Will add captions", "follow_person": "Will track the person", "cut_silence": "Will cut the silences", "scene_split": "Will split at scene changes",
                             "auto_enhance": "Will improve the colours", "beat_cut": "Will cut to the beat", "voiceover": "Will create the voice-over", "generate_video": "Will generate a new AI video" + (" with sound" if (task.get("narration") or task.get("ambience") not in (None, "none") or task.get("music")) else ""), "soundtrack": "Will add sound and voice"}[name])


ALIASES = {"add_overlay_video": "add_layer", "add_video_layer": "add_layer", "pip": "add_layer", "picture_in_picture": "add_layer", "add_track": "add_layer", "chroma_key": "remove_background", "green_screen": "remove_background",
           "remove_green_screen": "remove_background", "remove_bg": "remove_background", "key_color": "remove_background", "add_keyframe": "keyframe", "animate": "move_along", "remove_layer": "delete_layer", "add_sfx": "add_sound", "sound_effect": "add_sound", "add_sound_effect": "add_sound", "add_music": "add_sound", "play_sound": "add_sound", "set_mask": "set_layer", "update_layer": "set_layer", "remove_object": "ai_edit", "erase": "ai_edit", "inpaint": "ai_edit", "remove": "ai_edit", "add_picture": "add_image", "add_sticker": "add_image", "overlay_image": "add_image", "add_overlay": "add_image", "place_image": "add_image", "add_drawings": "add_drawing",
           "draw": "add_drawing", "set_clips": "set_clip", "add_title": "add_text", "text": "add_text", "remove_clip": "delete_clip", "cut": "trim_clip", "trim": "trim_clip"}


def _drawing_box_dict(d: dict[str, Any]) -> tuple[float, float, float, float] | None:
    pts = [pt for sh in d.get("shapes", []) for pt in sh.get("points", [])]
    if not pts:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _starts(p: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in ("texts", "drawings", "images", "layers"):
        for it in p.get(key, []):
            out[f"{key}:{it['id']}"] = float(it.get("start", 0))
    return out


def apply_actions(project: Project, actions: list[dict[str, Any]], names: dict[str, str], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    ap = Applier(project, names, {v.lower(): k for k, v in names.items()}, ctx)
    before = _starts(project.model_dump())
    for a in actions[:25]:
        try:
            ap.run(a)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            ap.skipped.append(f"{a.get('do') or 'an action'}: {str(exc)[:120]}")
    after = _starts(ap.p)
    new = [t for k, t in after.items() if k not in before]
    return {"project": Project.model_validate(ap.p), "applied": ap.applied, "skipped": ap.skipped, "tasks": ap.tasks, "focus": min(new) if new else None}


# ---------------------------------------------------------------- pictures for vision models
def encode_image(path: Path, max_side: int = 1024) -> dict[str, str]:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return {"media_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}
