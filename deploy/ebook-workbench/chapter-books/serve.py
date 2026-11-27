"""Serve vetted, complete chapter EPUBs on the BookOrbit container network."""

import io
import json
import os
import posixpath
import re
import signal
import sys
import tempfile
import threading
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from wikibook import EPUB_TYPE, LAO_CAN, compile_epub, fetch_pinned_revisions

CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
OPF = "{http://www.idpf.org/2007/opf}"
XHTML = "{http://www.w3.org/1999/xhtml}"
EPUB = "{http://www.idpf.org/2007/ops}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_EPUB_BYTES = 64 * 1024 * 1024
BOOK_PATH = re.compile(r"/books/([a-z0-9-]+)/([a-z0-9-]+)\.epub")


@dataclass
class Publication:
    release: dict
    build: Callable[[Path], object]
    content: bytes | None = None

    def prepare(self, cache):
        slug = self.release["slug"]
        start = f"[chapter_books.prepare] slug={slug}"
        try:
            cache.mkdir(parents=True, exist_ok=True)
            target = cache / f'{slug}-{self.release["editionId"]}.epub'
            if target.is_file():
                try:
                    self.content = read_epub(target, self.release)
                    print(f"{start} - restored complete EPUB from cache", file=sys.stderr)
                    return
                except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError):
                    pass
            with tempfile.TemporaryDirectory(dir=cache) as temp:
                staging = Path(temp) / "book.epub"
                self.build(staging)
                content = read_epub(staging, self.release)
                staging.chmod(0o444)
                staging.replace(target)
                self.content = content
                print(f"{start} - prepared complete EPUB ({len(content)} bytes)", file=sys.stderr)
        except Exception as error:
            print(f"{start} - EPUB unavailable: {type(error).__name__} {error}", file=sys.stderr)


def read_epub(path, release):
    with path.open("rb") as file:
        data = file.read(MAX_EPUB_BYTES + 1)
    if len(data) > MAX_EPUB_BYTES:
        raise ValueError("EPUB exceeded the size limit")
    with zipfile.ZipFile(io.BytesIO(data)) as epub:
        entries = epub.infolist()
        if (not entries or entries[0].filename != "mimetype" or entries[0].compress_type != zipfile.ZIP_STORED
                or epub.read("mimetype") != EPUB_TYPE.encode()
                or len(set(epub.namelist())) != len(entries)
                or sum(entry.file_size for entry in entries) > MAX_EPUB_BYTES * 4
                or epub.testzip() is not None):
            raise ValueError("Invalid EPUB container")
        container = ET.fromstring(epub.read("META-INF/container.xml"))
        rootfile = container.find(f"{CONTAINER}rootfiles/{CONTAINER}rootfile")
        if rootfile is None or not (package_path := rootfile.get("full-path")):
            raise ValueError("Missing EPUB package document")
        package = ET.fromstring(epub.read(package_path))
        if package.findtext(f"{OPF}metadata/{DC}title") != release["title"]:
            raise ValueError("EPUB package title does not match the approved edition")
        items = {item.get("id"): item for item in package.findall(f"{OPF}manifest/{OPF}item")}
        spine = package.findall(f"{OPF}spine/{OPF}itemref")
        reading_items = {item.get("idref") for item in spine}
        if len(spine) != len(reading_items) or len(spine) < release["chapterCount"]:
            raise ValueError("Invalid or incomplete EPUB reading order")
        for key in reading_items:
            _read_xhtml(epub, package_path, items[key])
        navigation = [item for item in items.values() if "nav" in item.get("properties", "").split()]
        if len(navigation) != 1:
            raise ValueError("Missing EPUB navigation document")
        nav = _read_xhtml(epub, package_path, navigation[0])
        toc = next((entry for entry in nav.iter(f"{XHTML}nav") if entry.get(f"{EPUB}type") == "toc"), None)
        if toc is None or {link.get("href") for link in toc.iter(f"{XHTML}a")} != {items[key].get("href") for key in reading_items}:
            raise ValueError("Invalid or incomplete EPUB table of contents")
    return data


def _read_xhtml(epub, package, item):
    href = urllib.parse.unquote(item.get("href", ""))
    if not href or item.get("media-type") != "application/xhtml+xml":
        raise ValueError("Invalid EPUB reading entry")
    root = ET.fromstring(epub.read(posixpath.join(posixpath.dirname(package), href)))
    body = root.find(f"{XHTML}body")
    if body is None or not ("".join(body.itertext()).strip() or list(body.iter(f"{XHTML}img"))):
        raise ValueError(f"Empty EPUB section {href}")
    return root


def normalized(text):
    return "".join(char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum())


def searchable(previously_prepared, criteria):
    for publication in previously_prepared:
        release = publication.release
        if criteria and not any(criteria in normalized(name) for name in (release["title"], *release["aliases"])):
            continue
        if publication.content is not None and criteria:
            yield {**release, "sizeBytes": len(publication.content)}


def make_server(address, cache, book=LAO_CAN, fetch_pages=fetch_pinned_revisions, *,
                extra_publications=(), background=False):
    library = (
        Publication(book.release(), lambda path: path.write_bytes(compile_epub(book, fetch_pages))),
        *(Publication(release, build) for release, build in extra_publications),
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_HEAD(self):
            self.respond()

        def respond(self):
            path = urllib.parse.urlsplit(self.path)
            ready = [publication for publication in library if publication.content is not None]
            if path.path == "/healthz":
                status = 200 if ready else 503
                return self.json_response(status, {"status": "ready" if ready else "unavailable", "books": len(ready)})
            if path.path == "/search":
                if not ready:
                    return self.json_response(503, {"error": "No complete chapter EPUB is currently available"})
                query = urllib.parse.parse_qs(path.query).get("q", [""])[0][:240]
                return self.json_response(200, {"books": list(searchable(ready, normalized(query)))})
            match = BOOK_PATH.fullmatch(path.path)
            if match:
                for publication in library:
                    current = publication.release
                    if (current["slug"], current["editionId"]) != match.groups():
                        continue
                    content = publication.content
                    if content is None:
                        return self.json_response(503, {"error": "This chapter EPUB is currently unavailable"})
                    filename = urllib.parse.quote(publication.release["title"] + ".epub", safe="")
                    return self.send(200, EPUB_TYPE, content,
                                     f"attachment; filename=\"{match[1]}.epub\"; filename*=UTF-8''{filename}")
            return self.json_response(404, {"error": "No such chapter EPUB"})

        def json_response(self, status, body):
            content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            return self.send(status, "application/json; charset=utf-8", content)

        def send(self, status, content_type, content, disposition=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            if disposition is not None:
                self.send_header("Content-Disposition", disposition)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)

        def log_message(self, *args):
            pass  # Search strings can reveal a reader's interests.

    server = ThreadingHTTPServer(address, Handler)
    for publication in library:
        if background:
            threading.Thread(target=publication.prepare, args=(cache,), daemon=True).start()
        else:
            publication.prepare(cache)
    return server


def main():
    from snowmoon import RELEASE, build

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    port = int(os.environ.get("CHAPTER_PORT", "8080"))
    cache = Path(os.environ.get("CHAPTER_CACHE", "/chapter-cache"))
    with make_server(("0.0.0.0", port), cache, extra_publications=((RELEASE, build),), background=True) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
