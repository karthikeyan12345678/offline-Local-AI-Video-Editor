"""Which AI should this computer use? Plain advice from the PC's memory and graphics card.

Used by both apps: the chat editor in VK Editor and the AI Assistant. It never calls the network; it only turns hardware numbers into a
recommendation: the best model to run on this PC, the best free online service, and the best paid one.
"""

from __future__ import annotations

from typing import Any

# (minimum VRAM GB, minimum RAM GB, Ollama tag, download size, what it is good for)
LOCAL_TIERS = [
    (20, 32, "qwen2.5:32b", "20 GB", "Very strong. Needs a big graphics card."),
    (10, 24, "qwen2.5:14b", "9 GB", "Strong writing and reasoning."),
    (5, 12, "qwen2.5:7b", "4.7 GB", "Good all-rounder; fits a 6 GB graphics card."),
    (0, 8, "llama3.2:3b", "2 GB", "Small and quick. Fine for edit commands and short answers."),
    (0, 0, "llama3.2:1b", "1.3 GB", "Tiny. Only for very small computers."),
]

FREE_ONLINE = [
    {"id": "groq", "name": "Groq", "model": "llama-3.3-70b-versatile", "url": "console.groq.com/keys",
     "why": "Free key, very fast, a 70B model. Best free choice for chat, editing commands and documents."},
    {"id": "gemini", "name": "Google Gemini", "model": "gemini-2.5-flash", "url": "aistudio.google.com/apikey",
     "why": "Free key. Can read pictures and long files, so it understands reference images."},
    {"id": "openrouter", "name": "OpenRouter (free models)", "model": "meta-llama/llama-3.3-70b-instruct:free", "url": "openrouter.ai/keys",
     "why": "One free key that reaches many free models. Slower when busy."},
    {"id": "pollinations", "name": "Free online AI (no key)", "model": "openai", "url": "",
     "why": "Nothing to sign up for. Slow at busy times, and what you type goes to a public service."},
]

PAID = [
    {"id": "anthropic", "name": "Claude (Anthropic)", "model": "claude-sonnet-5-5", "url": "console.anthropic.com",
     "why": "Best at following long instructions, writing, resumes and careful edits. Pay per use."},
    {"id": "openai", "name": "OpenAI", "model": "gpt-4o-mini", "url": "platform.openai.com/api-keys",
     "why": "Also reads pictures. Pay per use."},
]


def advise(ram_gb: float, vram_gb: float, gpu_name: str = "", gpu_ok: bool = True, configured: dict[str, bool] | None = None) -> dict[str, Any]:
    configured = configured or {}
    vram = vram_gb if gpu_ok else 0.0
    local = next(t for t in LOCAL_TIERS if vram >= t[0] and ram_gb >= t[1])
    local_row = {"id": "ollama", "name": "Ollama on this PC", "model": local[2], "size": local[3], "why": local[4],
                 "how": f"Install Ollama from ollama.com, then run:  ollama pull {local[2]}", "free": True, "private": True}
    free = [dict(x, free=True) for x in FREE_ONLINE]
    paid = [dict(x, free=False) for x in PAID]
    picture = ("Stable Diffusion Turbo on this PC (about 2.5 GB, works on a 4 GB card)" if vram < 8
               else "SDXL Turbo on this PC (bigger, sharper pictures)")
    # Best pick: something already connected wins; otherwise a strong PC should stay local, a weak one should use a free service.
    best = None
    for row in paid + free:
        if configured.get(row["id"]):
            best = row
            break
    if best is None:
        strong = ram_gb >= 12 and vram >= 5
        best = local_row if strong else free[0]
    pc = f"{gpu_name or 'No graphics card'}{f' · {vram_gb:g} GB' if gpu_ok and vram_gb else ''} · {ram_gb:g} GB memory"
    return {"pc": pc, "local": local_row, "free_online": free, "paid": paid, "best": best, "picture": picture,
            "tip": "Local runs offline and private but is slower. A free online key is the fastest way to get strong answers. Keys are saved only on this PC."}
