"""Loopback-only development host for the Viso sandbox UI and JSON API."""

import argparse
import json
import mimetypes
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .recognition import FaceEngine
from .service import ApiError, SandboxService
from .storage import ProfileStore

ROOT = Path(__file__).resolve().parents[2]
BROWSER_DIST = ROOT / "experiments" / "browser" / "dist"
MAX_BODY = 16_000_000


class SandboxServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service: SandboxService, dist: Path):
        self.service = service
        self.dist = dist.resolve()
        super().__init__(address, Handler)
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        self.origins = {f"http://{host}" for host in self.hosts} | {"http://127.0.0.1:5173", "http://localhost:5173"}


class Handler(BaseHTTPRequestHandler):
    server: SandboxServer

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # HTTP paths/status only; no image payloads or face vectors in logs.
        sys.stderr.write(f"[Viso] {format % args}\n")

    def send_content(self, status: int, body: bytes, mime: str):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def json(self, status: int, data: dict):
        self.send_content(status, json.dumps(data, allow_nan=False).encode(), "application/json; charset=utf-8")

    def dispatch(self, method: str):
        try:
            if self.headers.get("Host") not in self.server.hosts:
                raise ApiError("Use the local Viso address printed in the terminal.", 403)
            origin = self.headers.get("Origin")
            if origin and origin not in self.server.origins:
                raise ApiError("Cross-origin requests are not accepted.", 403)
            if self.headers.get("Sec-Fetch-Site") == "cross-site" and origin not in self.server.origins:
                raise ApiError("Cross-site requests are not accepted.", 403)
            path = urlsplit(self.path).path
            if not path.startswith("/api/"):
                if method != "GET":
                    raise ApiError("Endpoint not found.", 404)
                return self.static(path)
            data = None
            if method != "GET":
                if not secrets.compare_digest(self.headers.get("X-Viso-Token", ""), self.server.service.token):
                    raise ApiError("Session changed. Refresh Viso and try again.", 403)
                if method == "POST":
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise ApiError("Expected JSON request data.", 415)
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= MAX_BODY:
                        raise ApiError("Request is empty or too large.", 413)
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ApiError("Expected a JSON object.")
            self.json(200, self.server.service.dispatch(method, path, data))
        except ApiError as error:
            self.json(error.status, {"error": error.message})
        except (ValueError, UnicodeError):
            self.json(400, {"error": "Invalid request data."})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as error:
            print(f"[Viso] Request failed: {type(error).__name__}: {error}", file=sys.stderr)
            self.json(500, {"error": "The local service could not complete this request. See the terminal for details."})

    def static(self, path: str):
        path = unquote(path)
        target = (self.server.dist / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(self.server.dist):
            raise ApiError("File not found.", 404)
        if not target.is_file():
            if path == "/":
                return self.send_content(503, b"Build the historical browser bench with npm --prefix experiments/browser run build, or open its Vite development server. The native desktop app does not use this host.", "text/plain")
            raise ApiError("File not found.", 404)
        mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(target.suffix) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_content(200, target.read_bytes(), mime)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_DELETE(self):
        self.dispatch("DELETE")


def main():
    parser = argparse.ArgumentParser(description="Viso local recognition sandbox")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".viso")
    parser.add_argument("--ephemeral", action="store_true", help="Keep enrollment in memory for this process only")
    parser.add_argument("--open", action="store_true", help="Open the test bench in your browser")
    args = parser.parse_args()
    engine, engine_error = None, None
    try:
        engine = FaceEngine(ROOT / "models")
    except Exception as error:
        engine_error = str(error)
        print(f"[Viso] {engine_error}", flush=True)
    service = SandboxService(engine, ProfileStore(args.data_dir, args.ephemeral), engine_error)
    try:
        server = SandboxServer(("127.0.0.1", args.port), service, BROWSER_DIST)
    except OSError as error:
        parser.exit(1, f"Could not start Viso on port {args.port}: {error}\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"\nViso test bench: {url}\nProfile storage: {service.store.label}\nMode: simulated unlock / blink + open-eye verification\nPress Ctrl+C to stop.\n", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if engine is not None:
            engine.close()


if __name__ == "__main__":
    main()
