"""Sound effects for video clips and music: EQ, reverb, voice tools, pitch, noise reduction."""

from __future__ import annotations

SAMPLE_RATE = 48000

# id -> (label, group, filter chain). Chains only use filters present in every ffmpeg 5+ build.
AUDIO_FX: dict[str, tuple[str, str, str]] = {
    "voice_clean": ("Clean voice", "Voice", "highpass=f=90,afftdn=nf=-28,acompressor=threshold=0.1:ratio=3:attack=5:release=80:makeup=2,equalizer=f=3000:t=q:w=1:g=2"),
    "podcast": ("Podcast voice", "Voice", "highpass=f=80,acompressor=threshold=0.12:ratio=3.5:attack=10:release=120:makeup=3,equalizer=f=120:t=q:w=1:g=2,equalizer=f=5000:t=q:w=1:g=2,alimiter=limit=0.95"),
    "megaphone": ("Megaphone", "Voice", "highpass=f=500,lowpass=f=3500,acompressor=ratio=6:threshold=0.1,volume=1.5"),
    "telephone": ("Telephone", "Voice", "highpass=f=450,lowpass=f=3200,acompressor=threshold=0.15:ratio=4"),
    "radio": ("Old radio", "Voice", "highpass=f=300,lowpass=f=5200,equalizer=f=1800:t=q:w=1:g=4,acrusher=bits=12:mode=log:aa=1:mix=0.25"),
    "robot": ("Robot", "Voice", "afftfilt=real='hypot(re,im)*cos(0)':imag='hypot(re,im)*sin(0)':win_size=512:overlap=0.75"),
    "chipmunk": ("Chipmunk (higher)", "Voice", "asetrate=67200,aresample=48000,atempo=0.7143"),
    "deep_voice": ("Deep voice (lower)", "Voice", "asetrate=34286,aresample=48000,atempo=1.4"),
    "bass_boost": ("Bass boost", "Music", "bass=g=9:f=100:w=0.6"),
    "treble_boost": ("Treble boost", "Music", "treble=g=7:f=5000"),
    "warm": ("Warm", "Music", "equalizer=f=180:t=q:w=1:g=3,treble=g=-3:f=6000"),
    "bright": ("Bright", "Music", "equalizer=f=3500:t=q:w=1.2:g=3,treble=g=3:f=7000"),
    "club": ("Club punch", "Music", "bass=g=6:f=90,treble=g=3:f=6000,acompressor=ratio=2.5:threshold=0.2"),
    "lofi": ("Lo-fi", "Music", "highpass=f=120,lowpass=f=4200,acrusher=bits=9:mode=log:aa=1:mix=0.4"),
    "muffled": ("Muffled (behind a wall)", "Music", "lowpass=f=700"),
    "underwater": ("Underwater", "Music", "lowpass=f=500,chorus=0.7:0.9:55:0.4:0.25:2"),
    "reverb_room": ("Reverb: small room", "Space", "aecho=0.8:0.88:35|55:0.35|0.25"),
    "reverb_hall": ("Reverb: concert hall", "Space", "aecho=0.8:0.9:60|110|220:0.45|0.35|0.25"),
    "reverb_cave": ("Reverb: cave", "Space", "aecho=0.8:0.9:400|800|1200:0.4|0.3|0.2"),
    "echo": ("Echo", "Space", "aecho=0.8:0.8:320:0.5"),
    "chorus": ("Chorus", "Modulation", "chorus=0.7:0.9:55|65:0.4|0.32:0.25|0.4:2|2.3"),
    "flanger": ("Flanger", "Modulation", "flanger=delay=5:depth=4:speed=0.5"),
    "phaser": ("Phaser", "Modulation", "aphaser=in_gain=0.6:out_gain=0.8:delay=3:decay=0.4:speed=0.6"),
    "tremolo": ("Tremolo", "Modulation", "tremolo=f=6:d=0.6"),
    "vibrato": ("Vibrato", "Modulation", "vibrato=f=6:d=0.4"),
    # --- added in 1.2.14
    "helium": ("Helium (very high)", "Voice", "asetrate=62400,aresample=48000,atempo=0.7692"),
    "monster": ("Monster", "Voice", "asetrate=30000,aresample=48000,atempo=1.6,aecho=0.8:0.8:60:0.4,lowpass=f=3500"),
    "alien": ("Alien", "Voice", "tremolo=f=28:d=0.7,vibrato=f=9:d=0.6,aecho=0.8:0.85:25:0.5"),
    "walkie": ("Walkie-talkie", "Voice", "highpass=f=600,lowpass=f=3000,acrusher=bits=8:mode=lin:mix=0.45,volume=1.4"),
    "ghost": ("Ghost", "Voice", "aecho=0.8:0.9:180|350:0.5|0.35,vibrato=f=5:d=0.5,lowpass=f=3800"),
    "distorted": ("Distorted", "Voice", "volume=9,asoftclip=type=tanh,volume=0.35"),
    "low_battery": ("Low battery (slowing down)", "Voice", "asetrate=36000,aresample=48000,atempo=1.3333,vibrato=f=3:d=0.3"),
    "stadium": ("Stadium / big hall", "Space", "aecho=0.8:0.9:90|250|600|1100:0.5|0.4|0.3|0.2"),
    "bathroom": ("Bathroom", "Space", "aecho=0.8:0.88:18|30|45:0.5|0.4|0.3,highpass=f=150"),
    "cinema_wide": ("Cinema wide stereo", "Music", "extrastereo=m=1.8,bass=g=3:f=90"),
    "vinyl": ("Vinyl record", "Music", "highpass=f=60,lowpass=f=9000,acrusher=bits=11:mode=log:aa=1:mix=0.3,tremolo=f=0.55:d=0.04"),
    "radio_fm": ("FM radio", "Music", "highpass=f=100,lowpass=f=6500,acompressor=ratio=4:threshold=0.15:makeup=2,treble=g=2:f=4000"),
    "sub_bass": ("Sub bass boost", "Music", "bass=g=14:f=60:w=0.5,alimiter=limit=0.9"),
    "night_club_wall": ("Next room (muffled club)", "Music", "lowpass=f=450,bass=g=6:f=80,volume=1.3"),
}
AUDIO_FX_IDS = ("none", *AUDIO_FX)
AUDIO_FX_INFO = [("none", "None", "Basic"), *[(k, v[0], v[1]) for k, v in AUDIO_FX.items()]]


def _f(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


def fx_filters(fx: str, pitch: float = 0.0, bass: float = 0.0, treble: float = 0.0, denoise: bool = False, normalize: bool = False) -> list[str]:
    """Filter list for one clip's sound, already at 48 kHz stereo float."""
    out: list[str] = []
    if denoise:
        out.append("highpass=f=70,afftdn=nf=-30")
    if abs(bass) > 0.05:
        out.append(f"bass=g={_f(bass)}:f=110:w=0.6")
    if abs(treble) > 0.05:
        out.append(f"treble=g={_f(treble)}:f=5000")
    if fx != "none" and fx in AUDIO_FX:
        out.append(AUDIO_FX[fx][2])
    if abs(pitch) > 0.05:
        r = 2 ** (pitch / 12.0)
        out += [f"asetrate={_f(SAMPLE_RATE * r)}", f"aresample={SAMPLE_RATE}", f"atempo={_f(1 / r)}"]
    if normalize:
        out.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        out.append(f"aresample={SAMPLE_RATE}")  # loudnorm upsamples internally
    return out
