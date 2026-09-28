#!/usr/bin/env python3
"""Dependency-free local MVP server."""

from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.auth import AuthError, require_authenticated
from app.analysis_jobs import get_analysis_job, submit_analysis
from app.saved_results import default_results_root, delete_result, list_results, load_result, save_result, update_result


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "apps" / "web"


class Handler(BaseHTTPRequestHandler):
    server_version = "RfRepeaterMvp/0.1"

    def do_OPTIONS(self) -> None:  # noqa: N802
        request_path = urlparse(self.path).path
        if not request_path.startswith("/api/"):
            self.send_error(404)
            return
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization, X-Site-Finder-Proxy-Secret, X-Auth-Request-Email",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        request_path = urlparse(self.path).path
        if request_path == "/api/health":
            self._send_json({"status": "ok"})
            return
        if request_path == "/api/whoami":
            try:
                user = require_authenticated(self.headers)
            except AuthError as error:
                self._send_json({"error": str(error)}, status=401)
                return
            self._send_json({"email": str(user.get("email", "")).strip() if user else ""})
            return
        if request_path.startswith("/api/jobs/"):
            if not self._require_auth():
                return
            job_id = unquote(request_path.removeprefix("/api/jobs/")).strip("/")
            if not job_id or "/" in job_id:
                self.send_error(404)
                return
            job = get_analysis_job(job_id)
            if job is None:
                self._send_json({"error": "Analysis job not found."}, status=404)
            else:
                self._send_json(job)
            return
        if request_path == "/api/saved-results":
            if not self._require_auth():
                return
            self._send_json(list_results(_results_root()))
            return
        if request_path.startswith("/api/saved-results/"):
            if not self._require_auth():
                return
            parts = [unquote(part) for part in request_path.removeprefix("/api/saved-results/").split("/") if part]
            if len(parts) != 2:
                self.send_error(404)
                return
            try:
                self._send_json(load_result(_results_root(), parts[0], parts[1]))
            except FileNotFoundError:
                self.send_error(404)
            except ValueError as error:
                self._send_json({"error": str(error)}, status=400)
            return

        path = "/" if request_path == "/" else request_path
        static_path = WEB_ROOT / unquote(path.lstrip("/"))
        if path == "/":
            static_path = WEB_ROOT / "index.html"

        if not static_path.resolve().is_relative_to(WEB_ROOT.resolve()) or not static_path.exists():
            self.send_error(404)
            return

        content_type, _ = mimetypes.guess_type(static_path)
        payload = static_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        request_path = urlparse(self.path).path
        if request_path == "/api/saved-results":
            if not self._require_auth():
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                request = json.loads(raw.decode("utf-8"))
                manifest = save_result(_results_root(), request)
            except ValueError as error:
                self._send_json({"error": str(error)}, status=400)
                return
            except Exception as error:  # pragma: no cover - defensive server boundary
                self._send_json({"error": str(error)}, status=500)
                return
            self._send_json({"manifest": manifest}, status=201)
            return

        if request_path != "/api/run-analysis":
            self.send_error(404)
            return

        if not self._require_auth():
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("Analysis request must be a JSON object.")
            job = submit_analysis(request)
        except json.JSONDecodeError as error:
            self._send_json({"error": f"Invalid JSON: {error}"}, status=400)
            return
        except ValueError as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except Exception as error:  # pragma: no cover - defensive server boundary
            self._send_json({"error": str(error)}, status=500)
            return
        self._send_json(job, status=202)

    def do_PATCH(self) -> None:  # noqa: N802
        request_path = urlparse(self.path).path
        if not request_path.startswith("/api/saved-results/"):
            self.send_error(404)
            return
        if not self._require_auth():
            return
        parts = [unquote(part) for part in request_path.removeprefix("/api/saved-results/").split("/") if part]
        if len(parts) != 2:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw.decode("utf-8"))
            manifest = update_result(_results_root(), parts[0], parts[1], request)
        except FileNotFoundError:
            self.send_error(404)
            return
        except ValueError as error:
            self._send_json({"error": str(error)}, status=400)
            return
        except Exception as error:  # pragma: no cover - defensive server boundary
            self._send_json({"error": str(error)}, status=500)
            return
        self._send_json({"manifest": manifest})

    def do_DELETE(self) -> None:  # noqa: N802
        request_path = urlparse(self.path).path
        if not request_path.startswith("/api/saved-results/"):
            self.send_error(404)
            return
        if not self._require_auth():
            return
        parts = [unquote(part) for part in request_path.removeprefix("/api/saved-results/").split("/") if part]
        if len(parts) != 2:
            self.send_error(404)
            return
        try:
            self._send_json(delete_result(_results_root(), parts[0], parts[1]))
        except FileNotFoundError:
            self.send_error(404)
        except ValueError as error:
            self._send_json({"error": str(error)}, status=400)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self) -> bool:
        try:
            require_authenticated(self.headers)
        except AuthError as error:
            self._send_json({"error": str(error)}, status=401)
            return False
        return True

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        allowed = _cors_origins()
        if not origin or not allowed:
            return
        if "*" in allowed:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin in allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")


def _cors_origins() -> set[str]:
    raw = os.environ.get("MVP_CORS_ORIGINS", "")
    return {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}


def _results_root() -> Path:
    configured = os.environ.get("MVP_RESULTS_ROOT", "").strip()
    return Path(configured).expanduser() if configured else default_results_root(ROOT)


def main() -> None:
    host = os.environ.get("MVP_HOST", "127.0.0.1")
    port = int(os.environ.get("MVP_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"MVP server running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
