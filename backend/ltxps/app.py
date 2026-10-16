"""FastAPI application factory and command-line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import secrets
import socket
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .api.assistant_routes import make_assistant_health_router, make_assistant_router
from .api.routes import make_router
from .assistant.service import AssistantState, build_assistant_state
from .state import AppState, build_state


def find_ui_dir(explicit: str | None = None) -> Path | None:
    candidates = [explicit, os.environ.get("LTXPS_UI_DIR")]
    here = Path(__file__).resolve()
    candidates += [str(here.parents[2] / "ui"), str(here.parents[3] / "frontend" / "dist"), str(here.parents[2] / "frontend" / "dist")]
    for c in candidates:
        if c and (Path(c) / "index.html").exists():
            return Path(c)
    return None


def find_assistant_ui_dir(explicit: str | None = None) -> Path | None:
    candidates = [explicit, os.environ.get("LTXPS_ASSISTANT_UI_DIR")]
    here = Path(__file__).resolve()
    candidates += [str(here.parents[2] / "assistant-ui"), str(here.parents[3] / "assistant-ui" / "dist"), str(here.parents[2] / "assistant-ui" / "dist")]
    for c in candidates:
        if c and (Path(c) / "index.html").exists():
            return Path(c)
    return None


def create_app(state: AppState | None, ui_dir: Path | None = None, assistant: AssistantState | None = None, assistant_ui_dir: Path | None = None) -> FastAPI:
    title = "VK Editor" if state is not None else "AI Assistant"
    app = FastAPI(title=title, version=__version__, docs_url=None, redoc_url=None, openapi_url=None)
    # Only ever reachable from this PC; also blocks DNS-rebinding attempts from web pages.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    if state is not None:
        app.include_router(make_router(state, assistant))
    if assistant is not None:
        app.include_router(make_assistant_router(assistant))
        if state is None:
            app.include_router(make_assistant_health_router(assistant.token))

    @app.exception_handler(Exception)
    async def unhandled(_request, exc: Exception):  # noqa: ANN001
        logging.getLogger("ltxps").exception("unhandled error", exc_info=exc)
        return JSONResponse({"detail": "Something went wrong inside the app. Details were saved to the log file."}, status_code=500)

    if state is not None and assistant is not None and assistant_ui_dir is not None:
        # In the video studio the assistant is a second window served from the same backend.
        app.mount("/assistant-app", StaticFiles(directory=str(assistant_ui_dir), html=True), name="assistant-ui")
    if ui_dir is not None:
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    return app


def _setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / "studio.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    root.addHandler(logging.StreamHandler(sys.stderr))


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return k32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT: still running
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _exit_with_parent(pid: int) -> None:
    """Never leave an orphaned server holding GPU memory if the window was killed."""
    import threading
    import time

    def watch() -> None:
        while _pid_alive(pid):
            time.sleep(2)
        os._exit(0)

    threading.Thread(target=watch, daemon=True, name="parent-watch").start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ltxps", description="VK Editor backend")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    parser.add_argument("--token", default=os.environ.get("LTXPS_TOKEN"), help="API token (random if omitted)")
    parser.add_argument("--ui-dir", default=None)
    parser.add_argument("--mode", choices=["studio", "assistant"], default=os.environ.get("LTXPS_MODE", "studio"),
                        help="studio = video studio (+ assistant tools); assistant = the separate AI Assistant app only")
    parser.add_argument("--assistant-ui-dir", default=None, help="built assistant UI to serve at /assistant-app (studio mode)")
    parser.add_argument("--parent-pid", type=int, default=0, help="exit when this process ends (set by the desktop shell)")
    args = parser.parse_args(argv)

    token = args.token or secrets.token_urlsafe(24)
    if args.mode == "assistant":
        from .config import resolve_data_dir

        root = resolve_data_dir("assistant")
        state = None
        assistant = build_assistant_state(root, token)
        _setup_logging(root / "logs")
    else:
        state = build_state(token)
        assistant = build_assistant_state(state.paths.root / "assistant", token)
        assistant.models_root = state.paths.models
        _setup_logging(state.paths.logs)

    import uvicorn

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)  # accept connections from the moment READY is printed, before uvicorn finishes starting
    port = sock.getsockname()[1]

    if args.parent_pid:
        _exit_with_parent(args.parent_pid)
    if args.mode == "assistant":
        ui = find_assistant_ui_dir(args.ui_dir)
        app = create_app(None, ui, assistant)
    else:
        ui = find_ui_dir(args.ui_dir)
        app = create_app(state, ui, assistant, find_assistant_ui_dir(args.assistant_ui_dir))
    # One line the desktop shell (or you) can read to find the app.
    print("LTXPS_READY " + json.dumps({"port": port, "token": token, "url": f"http://127.0.0.1:{port}/?t={token}", "ui": bool(ui), "mode": args.mode}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
