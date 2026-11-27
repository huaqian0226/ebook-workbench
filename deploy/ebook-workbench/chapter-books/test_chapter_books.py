import hashlib
import io
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from json import load
from pathlib import Path

from serve import make_server
from wikibook import Book, Revision

OPF = "{http://www.idpf.org/2007/opf}"
XHTML = "{http://www.w3.org/1999/xhtml}"
DC = "{http://purl.org/dc/elements/1.1/}"

PAGES = {
    1: "*[[/自敘|自敘]]\n*[[/第01回|第一回]]　開篇\n*[[/第02回|第二回]]　終篇",
    2: """<div class=text>{{Textquality|50%}}
{{novel|示例書|自敘||第01回|}}
== 自敘 ==

作者自述。

{{novel-f||第01回|}}
</div>
__NOEDITSECTION__""",
    3: """<div class=text>{{Textquality|50%}}
{{novel|示例書|第一回　開篇||第02回|}}第一回有完整正文，以及 & 和書名。

::;第一行詩
::;第二行詩

{{novel-f||第02回|}}
</div>
__NOEDITSECTION__""",
    4: """<div class=text>{{Textquality|50%}}
{{novel|示例書|第二回　終篇|第01回||}}
第二回有完整正文，故事結束了。

{{novel-f|第01回||}}
</div>
__NOEDITSECTION__""",
}


def revision(page, number):
    digest = hashlib.sha256(PAGES[number].encode()).hexdigest()
    return Revision(page, number, digest)


BOOK = Book("example", "示例書", "示例作者", ("示例书",), "2025-01-02T00:00:00Z", 2,
            revision("示例書", 1),
            tuple(revision("示例書/" + page, number) for page, number in (("自敘", 2), ("第01回", 3), ("第02回", 4))))


class ChapterBooksTest(unittest.TestCase):
    def start(self, pages=PAGES, extra_publications=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        server = make_server(("127.0.0.1", 0), Path(tmp.name), BOOK, lambda revisions: pages,
                             extra_publications=extra_publications)
        background = threading.Thread(target=server.serve_forever, daemon=True)
        background.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def test_complete_edition_is_searchable_and_downloads_ordered_epub(self):
        base = self.start()
        with urllib.request.urlopen(base + "/healthz") as response:
            self.assertEqual(load(response)["status"], "ready")
        with urllib.request.urlopen(base + "/search?q=%E7%A4%BA%E4%BE%8B%E4%B9%A6") as response:
            [release] = load(response)["books"]
        self.assertEqual(release["slug"], "example")
        self.assertEqual(release["chapterCount"], 2)
        with urllib.request.urlopen(base + "/books/example/v2-1-4.epub") as response:
            self.assertEqual(response.headers["Content-Type"], "application/epub+zip")
            payload = response.read()
        with urllib.request.urlopen(urllib.request.Request(base + "/books/example/v2-1-4.epub", method="HEAD")) as response:
            self.assertEqual(int(response.headers["Content-Length"]), len(payload))
            self.assertEqual(response.read(), b"")
        with zipfile.ZipFile(io.BytesIO(payload)) as epub:
            first = epub.infolist()[0]
            self.assertEqual((first.filename, first.compress_type), ("mimetype", zipfile.ZIP_STORED))
            self.assertEqual(epub.read(first), b"application/epub+zip")
            self.assertIsNone(epub.testzip())
            manifest = ET.fromstring(epub.read("EPUB/package.opf"))
            spine = manifest.find(OPF + "spine")
            self.assertEqual([item.get("idref") for item in spine], ["section-00", "section-01", "section-02", "credits"])
            self.assertEqual(manifest.findtext(f"{OPF}metadata/{DC}title"), "示例書")
            nav = ET.fromstring(epub.read("EPUB/nav.xhtml"))
            self.assertEqual([link.get("href") for link in nav.iter(XHTML + "a")],
                             ["section-00.xhtml", "section-01.xhtml", "section-02.xhtml", "credits.xhtml"])
            self.assertIn("作者自述", epub.read("EPUB/section-00.xhtml").decode())
            self.assertIn("第一回有完整正文，以及 &amp;", epub.read("EPUB/section-01.xhtml").decode())
            self.assertIn("故事結束了", epub.read("EPUB/section-02.xhtml").decode())
            credits = epub.read("EPUB/credits.xhtml").decode()
            for item in ("CC BY-SA 4.0", "示例作者", "oldid=1", "oldid=2", "oldid=3", "oldid=4"):
                self.assertIn(item, credits)

    def test_missing_or_changed_revision_never_becomes_downloadable(self):
        for broken in ({number: body for number, body in PAGES.items() if number != 4},
                       {**PAGES, 4: PAGES[4].replace("故事結束了。", "")}):
            with self.subTest(revisions=list(broken)):
                base = self.start(broken)
                for endpoint in ("/healthz", "/search?q=%E7%A4%BA%E4%BE%8B%E4%B9%A6", "/books/example/v2-1-4.epub"):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(base + endpoint)
                    self.assertEqual(error.exception.code, 503)

    def test_an_unavailable_source_leaves_other_prepared_books_searchable(self):
        unavailable = {**BOOK.release(), "slug": "pending", "title": "新書", "aliases": []}

        def build_unavailable(path):
            raise TimeoutError("Example origin did not respond")

        base = self.start(extra_publications=((unavailable, build_unavailable),))
        with urllib.request.urlopen(base + "/healthz") as response:
            self.assertEqual(load(response), {"status": "ready", "books": 1})
        with urllib.request.urlopen(base + "/search?q=%E7%A4%BA%E4%BE%8B%E4%B9%A6") as response:
            self.assertEqual(load(response)["books"][0]["slug"], "example")
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + "/books/pending/v2-1-4.epub")
        self.assertEqual(error.exception.code, 503)
