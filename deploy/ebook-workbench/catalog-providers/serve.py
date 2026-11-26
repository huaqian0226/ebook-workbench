import importlib.util
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from catalog_core import UpstreamError, authorized
from sources import PROVIDERS


if importlib.util.find_spec("workbench_sources") is not None:
    from workbench_sources import PROVIDERS as WORKBENCH_PROVIDERS

    PROVIDERS = {**PROVIDERS, **WORKBENCH_PROVIDERS}


class CatalogServer(ThreadingHTTPServer):
    def __init__(self, address, provider, token):
        super().__init__(address, CatalogHandler)
        self.provider = provider
        self.token = token
        self.source_lock = threading.Lock()
        self.next_call = 0.0

    def fetch(self, function, *args):
        if not self.source_lock.acquire(timeout=1):
            raise UpstreamError(429, "1")
        try:
            time.sleep(max(0, self.next_call - time.monotonic()))
            self.next_call = time.monotonic() + self.provider.min_interval_ms / 1000
            return function(*args)
        finally:
            self.source_lock.release()


class CatalogHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        try:
            self.route()
        except UpstreamError as exc:
            self.respond(exc.status, {"error": "catalog source unavailable"}, exc.retry_after)
            logging.warning("provider=%s status=%s", self.server.provider.key, exc.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            logging.error("provider=%s error=%s", self.server.provider.key, type(exc).__name__)
            self.respond(502, {"error": "catalog response unavailable"})

    def route(self):
        if len(self.path) > 2048:
            return self.respond(414, {"error": "request too long"})
        url = urlsplit(self.path)
        provider = self.server.provider
        if url.path == "/healthz":
            status = provider.status() if provider.status else {}
            return self.respond(200, {"provider": provider.key, **status})
        header = self.headers.get("Authorization", "")
        if not authorized(self.server.token, header):
            return self.respond(401, {"error": "authorization required"})
        if url.path == "/provider/info":
            return self.respond(200, provider.info(self.server.token))
        if url.path == "/search":
            return self.search(url.query, provider)
        if url.path.startswith("/book/") and provider.lookup:
            identifier = unquote(url.path.removeprefix("/book/"))
            if 0 < len(identifier) <= provider.id_max_length:
                result = self.server.fetch(provider.lookup, identifier)
                if result:
                    return self.respond(200, result)
        return self.respond(404, {"error": "not found"})

    def search(self, search_query, provider):
        try:
            params = parse_qs(search_query, max_num_fields=20)
        except ValueError:
            return self.respond(400, {"error": "invalid query parameters"})

        def param(name):
            return params.get(name, [""])[0].strip()[:256]

        query, author, isbn = param("query"), param("author"), param("isbn")
        try:
            limit = min(50, max(1, int(param("limit") or 10)))
        except ValueError:
            return self.respond(400, {"error": "invalid limit"})
        matches = []
        if query or author or isbn:
            matches = self.server.fetch(provider.search, query, author, isbn, limit)
        return self.respond(200, {"matches": matches[:limit]})

    def respond(self, code, payload, retry_after=None):
        response = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        if retry_after:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(response)


def main():
    key = os.environ.get("CATALOG_PROVIDER")
    if key not in PROVIDERS:
        raise SystemExit("Set CATALOG_PROVIDER to one of: " + ", ".join(PROVIDERS))
    provider = PROVIDERS[key]
    host = os.environ.get("CATALOG_HOST", "0.0.0.0")
    port = int(os.environ.get("CATALOG_PORT", "8080"))
    with CatalogServer((host, port), provider, os.environ.get("AUTH_TOKEN", "")) as server:
        if provider.warmup:
            provider.warmup()
        logging.info("provider=%s listening=%s", key, port)
        server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
