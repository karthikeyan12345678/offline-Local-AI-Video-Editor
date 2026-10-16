"""Stand-in engine for UI development and automated tests (LTXPS_ENGINE=fake).

It makes a real, playable video quickly so everything downstream (library,
editor, export) can be exercised without a GPU or model downloads.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..jobs import JobContext
from .base import GenRequest, write_video


class FakeEngine:
    def __init__(self, step_delay: float = 0.05):
        self.step_delay = step_delay

    def generate(self, req: GenRequest, out_path: Path, ctx: JobContext) -> dict:
        rng = np.random.default_rng(req.seed)
        base = rng.integers(40, 215, size=3).astype(np.float32)
        for step in range(req.steps):
            ctx.check()
            ctx.update(0.1 + 0.7 * (step + 1) / req.steps, f"Denoising step {step + 1} of {req.steps}")
            time.sleep(self.step_delay)
        ctx.update(0.85, "Decoding video")
        h, w = req.height, req.width
        ys, xs = np.mgrid[0:h, 0:w]

        def frames():
            for f in range(req.frames):
                ctx.check()
                phase = f / max(1, req.frames - 1)
                img = np.zeros((h, w, 3), dtype=np.float32)
                for c in range(3):
                    img[..., c] = base[c] * (0.5 + 0.5 * np.sin(2 * np.pi * (xs / w + phase + c / 3)))
                    img[..., c] += 60 * (ys / h)
                yield np.clip(img, 0, 255).astype(np.uint8)

        write_video(frames(), w, h, req.fps, out_path)
        return {"strategy": "fake", "end_image": bool(req.end_image_path)}

    def unload(self) -> None:
        pass
