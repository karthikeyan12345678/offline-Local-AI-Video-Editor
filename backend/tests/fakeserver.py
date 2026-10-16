"""A tiny stand-in for an OpenAI-compatible and Anthropic-style model server, used only by tests."""

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image


def png_bytes(color=(200, 30, 30)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(b, "PNG")
    return b.getvalue()


class Fake:
    def __init__(self):
        self.reply = "Hello from the fake model."
        self.fail = None  # status code to return
        self.requests: list[tuple[str, dict, dict]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.requests.append((self.path, dict(self.headers), {}))
                if self.path.endswith("/models"):
                    return self._json(200, {"data": [{"id": "m-one"}, {"id": "m-two"}]})
                self._json(404, {})

            def do_POST(self):
                n = int(self.headers.get("content-length", 0))
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.requests.append((self.path, dict(self.headers), body))
                if outer.fail:
                    return self._json(outer.fail, {"error": {"message": "nope"}})
                if self.path.endswith("/images/generations"):
                    return self._json(200, {"data": [{"b64_json": base64.b64encode(png_bytes()).decode()}]})
                anth = self.path.endswith("/messages")
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                words = outer.reply.split(" ")
                for i, w in enumerate(words):
                    t = w + (" " if i < len(words) - 1 else "")
                    ev = {"type": "content_block_delta", "delta": {"type": "text_delta", "text": t}} if anth else {"choices": [{"delta": {"content": t}}]}
                    if anth:
                        self.wfile.write(b"event: content_block_delta\n")
                    self.wfile.write(b"data: " + json.dumps(ev).encode() + b"\n\n")
                self.wfile.write(b"data: [DONE]\n\n")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def close(self):
        self.httpd.shutdown()
