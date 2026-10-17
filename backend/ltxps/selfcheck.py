"""`python -m ltxps.selfcheck` prints one JSON line saying whether the installed PyTorch can use this PC's GPU.
The desktop shell runs it after installing PyTorch to decide whether another build must be tried."""

from __future__ import annotations

import json


def run() -> dict:
    out: dict = {"torch": None, "cuda": False, "arch_ok": False, "gpu": None, "capability": None}
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - report, never crash: the shell reads this output
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["torch"] = torch.__version__
    try:
        if torch.cuda.is_available():
            from .system import arch_is_supported

            props = torch.cuda.get_device_properties(0)
            out.update(cuda=True, gpu=props.name, capability=[props.major, props.minor])
            from .system import kernel_runs

            listed = arch_is_supported(list(torch.cuda.get_arch_list()), (props.major, props.minor))
            out["arch_ok"] = kernel_runs(torch)  # a kernel that really runs beats any list; an unlisted but working card is fine
            out["listed"] = listed
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        out["arch_ok"] = False
    return out


if __name__ == "__main__":
    print(json.dumps(run()))
