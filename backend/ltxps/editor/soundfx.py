"""A built-in library of free sound effects, ambience and loops.

Nothing here is a recording and nothing needs a download or a licence: every sound is made by ffmpeg from a short recipe
(oscillators, noise and filters) the first time it is used, then kept on disk. They are simple, clean "editor" sounds -
whooshes, pops, dings, impacts, risers, room ambience, drum loops - to give a video polish. For real recorded sounds the
user can still add their own files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .media import NO_WINDOW, require_ffmpeg

SR = 48000


def _e(expr: str, d: float) -> str:
    return f"aevalsrc='{expr}':d={d}:s={SR}"


def _noise(d: float, color: str = "pink", a: float = 0.8) -> str:
    return f"anoisesrc=d={d}:c={color}:a={a}:r={SR}"


_BEAT = 60 / 90
_EDM = 60 / 124


def _hiphop() -> str:
    b = f"{_BEAT:.5f}"
    ph = f"mod(t,{b})"
    idx = f"mod(floor(t/{b}),4)"
    kick = f"eq(mod({idx},2),0)*sin(2*PI*(50+120*exp(-{ph}*30))*{ph})*exp(-{ph}*9)"
    snare = f"eq(mod({idx},2),1)*(random(0)*2-1)*exp(-{ph}*20)*0.55"
    hat = f"(random(1)*2-1)*exp(-mod(t,{_BEAT / 2:.5f})*70)*0.22"
    return f"{_e(f'0.8*({kick})+{snare}+{hat}', 8.0)},highpass=f=35[m]"


def _edm() -> str:
    b = f"{_EDM:.5f}"
    ph = f"mod(t,{b})"
    idx = f"mod(floor(t/{b}),4)"
    kick = f"sin(2*PI*(46+140*exp(-{ph}*38))*{ph})*exp(-{ph}*8)"
    clap = f"eq(mod({idx},2),1)*(random(0)*2-1)*exp(-{ph}*26)*0.5"
    off = f"mod(t+{_EDM / 2:.5f},{b})"
    hat = f"(random(1)*2-1)*exp(-{off}*55)*0.25*gt({ph},{_EDM / 2:.5f})"
    return f"{_e(f'0.85*({kick})+{clap}+{hat}', round(_EDM * 16, 3))},highpass=f=35[m]"


# id -> (label, group, seconds, recipe ending in [m])
SOUNDS: dict[str, tuple[str, str, float, str]] = {
    # --- transitions
    "whoosh": ("Whoosh", "Transitions", 1.0, f"{_noise(1.0, 'pink', 0.9)},highpass=f=250,lowpass=f=2600,afade=t=in:d=0.45,afade=t=out:st=0.45:d=0.55,volume=1.7[m]"),
    "whoosh_fast": ("Whoosh (fast)", "Transitions", 0.5, f"{_noise(0.5, 'pink', 0.9)},highpass=f=400,lowpass=f=4200,afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.3,volume=1.7[m]"),
    "swipe": ("Swipe", "Transitions", 0.35, f"{_noise(0.35, 'white', 0.7)},highpass=f=1500,lowpass=f=7000,afade=t=in:d=0.12,afade=t=out:st=0.12:d=0.23,volume=1.4[m]"),
    "riser": ("Riser (builds up)", "Transitions", 4.0, f"{_noise(4.0, 'white', 0.5)},lowpass=f=7000,highpass=f=300,afade=t=in:d=4:curve=exp[n];{_e('0.28*sin(2*PI*(140+90*t+30*t*t)*t)*pow(t/4,2)', 4.0)}[tn];[n][tn]amix=inputs=2:normalize=0[m]"),
    "downer": ("Downer (falls away)", "Transitions", 2.5, f"{_e('0.45*sin(2*PI*(700*exp(-t*1.3)+60)*t)*exp(-t*1.1)', 2.5)}[m]"),
    "sparkle": ("Sparkle", "Transitions", 1.2, f"{_e('0.22*sin(2*PI*(2400+1800*sin(floor(t*16)*2.7))*t)*exp(-mod(t,0.0625)*38)*exp(-t*1.6)', 1.2)}[m]"),
    # --- impacts
    "impact": ("Impact", "Impacts", 2.2, f"{_e('0.9*sin(2*PI*(38+110*exp(-t*9))*t)*exp(-t*2.2)', 2.2)}[k];{_noise(2.2, 'brown', 0.7)},lowpass=f=900,afade=t=out:st=0:d=1.2[n];[k][n]amix=inputs=2:normalize=0[m]"),
    "boom": ("Deep boom", "Impacts", 3.2, f"{_e('0.9*sin(2*PI*(30+80*exp(-t*5))*t)*exp(-t*1.4)', 3.2)}[k];{_noise(3.2, 'brown', 0.6)},lowpass=f=500,afade=t=out:st=0:d=2.4[n];[k][n]amix=inputs=2:normalize=0,aecho=0.8:0.7:120|260:0.3|0.2[m]"),
    "hit": ("Hit / punch", "Impacts", 0.5, f"{_e('0.9*sin(2*PI*(60+260*exp(-t*28))*t)*exp(-t*11)', 0.5)}[k];{_noise(0.5, 'white', 0.5)},lowpass=f=2500,afade=t=out:st=0:d=0.15[n];[k][n]amix=inputs=2:normalize=0[m]"),
    "bass_drop": ("Bass drop", "Impacts", 3.0, f"{_e('0.9*sin(2*PI*(160*exp(-t*2.2)+38)*t)*exp(-t*0.7)', 3.0)},asoftclip=type=tanh[m]"),
    "camera_flash": ("Camera flash", "Impacts", 0.8, f"{_e('0.4*sin(2*PI*(4200-3200*t)*t)*exp(-t*7)', 0.8)}[m]"),
    "shutter": ("Camera shutter", "Impacts", 0.35, f"{_e('(random(0)*2-1)*(exp(-t*90)+0.8*exp(-(t-0.11)*90)*gte(t,0.11))', 0.35)},highpass=f=900,lowpass=f=7000[m]"),
    # --- interface
    "pop": ("Pop", "Interface", 0.25, f"{_e('0.8*sin(2*PI*(420+2200*exp(-t*38))*t)*exp(-t*28)', 0.25)}[m]"),
    "click": ("Click", "Interface", 0.08, f"{_e('(random(0)*2-1)*exp(-t*140)', 0.08)},highpass=f=1500[m]"),
    "tick": ("Clock tick", "Interface", 2.0, f"{_e('(random(0)*2-1)*exp(-mod(t,0.5)*210)*(0.7+0.3*eq(mod(floor(t*2),2),0))', 2.0)},highpass=f=1100,lowpass=f=6000[m]"),
    "typing": ("Typing on a keyboard", "Interface", 2.0, f"{_e('(random(0)*2-1)*exp(-mod(t,0.13)*190)*(0.4+0.6*random(1))', 2.0)},highpass=f=1200,lowpass=f=6500[m]"),
    "ding": ("Ding (bell)", "Interface", 1.6, f"{_e('0.5*(sin(2*PI*1318.5*t)+0.35*sin(2*PI*2637*t)+0.15*sin(2*PI*3951*t))*exp(-t*4.5)', 1.6)}[m]"),
    "notification": ("Notification", "Interface", 0.9, f"{_e('0.5*sin(2*PI*if(lt(t,0.18),880,1318.5)*t)*exp(-(t-0.18*gte(t,0.18))*7)', 0.9)}[m]"),
    "success": ("Success chime", "Interface", 1.4, f"{_e('0.45*sin(2*PI*if(lt(t,0.12),523.25,if(lt(t,0.24),659.25,if(lt(t,0.36),783.99,1046.5)))*t)*if(lt(t,0.48),exp(-mod(t,0.12)*9),exp(-(t-0.48)*3.5))', 1.4)}[m]"),
    "error": ("Error buzz", "Interface", 0.5, f"{_e('0.3*sgn(sin(2*PI*if(lt(t,0.2),220,170)*t))', 0.5)},lowpass=f=1800,afade=t=out:st=0.35:d=0.15[m]"),
    "coin": ("Coin", "Interface", 0.7, f"{_e('0.45*sin(2*PI*if(lt(t,0.08),988,1319)*t)*exp(-(t-0.08*gte(t,0.08))*9)', 0.7)}[m]"),
    # --- sci-fi and games
    "laser": ("Laser", "Sci-fi and game", 0.5, f"{_e('0.5*sin(2*PI*(300+3200*exp(-t*14))*t)*exp(-t*5)', 0.5)}[m]"),
    "power_up": ("Power up", "Sci-fi and game", 1.0, f"{_e('0.4*sin(2*PI*(200+900*t)*t)*min(1,t*8)*exp(-pow(t,4)*2)', 1.0)}[m]"),
    "power_down": ("Power down", "Sci-fi and game", 1.2, f"{_e('0.4*sin(2*PI*(1100-900*t)*t)*exp(-t*2)', 1.2)}[m]"),
    "glitch_burst": ("Glitch burst", "Sci-fi and game", 0.6, f"{_e('(random(0)*2-1)*gt(sin(2*PI*17*t)*sin(2*PI*5*t),0.2)*0.8', 0.6)},acrusher=bits=6:mode=lin:mix=0.8[m]"),
    "tv_static": ("TV static", "Sci-fi and game", 1.5, f"{_noise(1.5, 'white', 0.45)},lowpass=f=8000[m]"),
    "record_scratch": ("Record scratch", "Sci-fi and game", 0.7, f"{_e('0.4*(2*mod(t*(900-1100*t),1)-1)*exp(-t*3)', 0.7)},highpass=f=300,lowpass=f=5000[m]"),
    "heartbeat": ("Heartbeat", "Sci-fi and game", 2.4, f"{_e('0.9*sin(2*PI*55*t)*(exp(-mod(t,0.8)*30)+0.7*exp(-(mod(t,0.8)-0.22)*30)*gte(mod(t,0.8),0.22))', 2.4)},lowpass=f=300[m]"),
    # --- ambience (loop-friendly)
    "rain": ("Rain", "Ambience", 8.0, f"{_noise(8.0, 'pink', 0.55)},highpass=f=900,lowpass=f=9000,volume=1.3[m]"),
    "wind": ("Wind", "Ambience", 8.0, f"{_noise(8.0, 'brown', 0.8)},lowpass=f=650,tremolo=f=0.25:d=0.5,volume=1.6[m]"),
    "waves": ("Sea waves", "Ambience", 10.0, f"{_noise(10.0, 'brown', 0.8)},lowpass=f=1000,tremolo=f=0.12:d=0.8,volume=1.8[m]"),
    "fire": ("Campfire", "Ambience", 8.0, f"{_noise(8.0, 'brown', 0.35)},lowpass=f=450[b];{_e('(random(0)*2-1)*gt(random(1),0.9985)*0.9', 8.0)},aecho=0.8:0.5:3|7:0.5|0.3,highpass=f=600[c];[b][c]amix=inputs=2:normalize=0[m]"),
    "crickets": ("Night crickets", "Ambience", 8.0, f"{_e('0.16*sin(2*PI*4300*t)*gt(sin(2*PI*28*t),0.2)*gt(sin(2*PI*2.2*t),-0.1)', 8.0)}[m]"),
    "room_tone": ("Quiet room tone", "Ambience", 8.0, f"{_noise(8.0, 'brown', 0.25)},lowpass=f=220[m]"),
    # --- music and rhythm
    "beat_hiphop": ("Drum loop - hip hop 90 BPM", "Music and loops", 8.0, _hiphop()),
    "beat_edm": ("Drum loop - dance 124 BPM", "Music and loops", round(_EDM * 16, 3), _edm()),
    "pad_calm": ("Calm pad", "Music and loops", 10.0, f"{_e('0.16*(sin(2*PI*220*t)+sin(2*PI*261.63*t)+sin(2*PI*329.63*t)+0.5*sin(2*PI*110*t))*(0.75+0.25*sin(2*PI*0.2*t))', 10.0)},chorus=0.6:0.9:50|60:0.4|0.3:0.25|0.4:2|2.3,afade=t=in:d=2,afade=t=out:st=8:d=2[m]"),
    "pad_tension": ("Tense drone", "Music and loops", 10.0, f"{_e('0.2*(sin(2*PI*55*t)+0.8*sin(2*PI*58.27*t)+0.4*sin(2*PI*110*t))*(0.7+0.3*sin(2*PI*0.3*t))', 10.0)},aecho=0.8:0.8:400:0.3,afade=t=in:d=2,afade=t=out:st=8:d=2[m]"),
}

GROUP_ORDER = ["Transitions", "Impacts", "Interface", "Sci-fi and game", "Ambience", "Music and loops"]


def catalog() -> list[dict]:
    return [{"id": k, "label": v[0], "group": v[1], "duration": v[2]} for k, v in SOUNDS.items()]


def graph(sound_id: str) -> str:
    recipe = SOUNDS[sound_id][3]
    return f"{recipe.rsplit('[m]', 1)[0]}[m];[m]aformat=sample_fmts=fltp:channel_layouts=stereo,aresample={SR},alimiter=limit=0.92[out]"


def ensure(sound_id: str, folder: Path) -> Path:
    """The .wav of a sound, made on first use and reused afterwards."""
    if sound_id not in SOUNDS:
        raise KeyError(sound_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{sound_id}.wav"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    tmp = folder / f".{sound_id}.part.wav"
    cmd = [require_ffmpeg(), "-v", "error", "-y", "-filter_complex", graph(sound_id), "-map", "[out]", "-t", str(SOUNDS[sound_id][2]), "-c:a", "pcm_s16le", str(tmp)]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Could not make the sound '{sound_id}': {r.stderr.strip()[-200:]}")
    tmp.replace(dest)
    return dest


def find(query: str) -> str | None:
    """Pick a sound from a person's words ("whoosh", "a camera click", "rain")."""
    q = query.lower().strip().replace("-", " ").replace("_", " ")
    if not q:
        return None
    for k, v in SOUNDS.items():
        if q == k.replace("_", " ") or q == v[0].lower():
            return k
    words = [w for w in q.split() if len(w) > 2]
    best, score = None, 0
    extra = {"swoosh": "whoosh", "swish": "swipe", "bang": "impact", "explosion": "boom", "punch": "hit", "bell": "ding", "beep": "notification", "camera": "shutter",
             "keyboard": "typing", "rainfall": "rain", "ocean": "waves", "sea": "waves", "fireplace": "fire", "campfire": "fire", "cricket": "crickets", "drums": "beat hiphop",
             "drum": "beat hiphop", "beat": "beat hiphop", "bass": "bass drop", "scratch": "record scratch", "heart": "heartbeat", "tension": "pad tension", "calm": "pad calm",
             "glitch": "glitch burst", "static": "tv static", "laser": "laser", "zap": "laser", "sparkles": "sparkle", "twinkle": "sparkle", "shutter": "shutter", "clock": "tick"}
    for w in words:
        w = extra.get(w, w)
        for k, v in SOUNDS.items():
            hay = f"{k.replace('_', ' ')} {v[0].lower()}"
            if w in hay.split() or (len(w) > 4 and w in hay):
                sc = 2 if w == k.replace("_", " ") else 1
                if sc > score:
                    best, score = k, sc
        if w in SOUNDS:
            return w
    return best
