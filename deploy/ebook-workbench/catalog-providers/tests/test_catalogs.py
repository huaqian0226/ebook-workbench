import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from unittest.mock import patch

from catalog_core import Provider, UpstreamError
from serve import CatalogServer
from snapshots import LocalCatalog, _doab_record
from sources import _librivox_record, _openstax_book, _otl_book, _wiki_book, librivox_lookup, librivox_search, openstax_search


class MapperTests(unittest.TestCase):
    def test_public_audiobook_has_audio_identity(self):
        book = _librivox_record({
            "id": "253", "title": "Pride and Prejudice",
            "description": "<em>Pride and Prejudice</em><br>(Summary from Wikipedia)",
            "authors": [{"first_name": "Jane", "last_name": "Austen"}],
            "language": "English", "totaltimesecs": 47204, "copyright_year": "1813",
            "url_librivox": "https://librivox.org/pride-and-prejudice-by-jane-austen/",
        })
        self.assertEqual(book["authors"], ["Jane Austen"])
        self.assertEqual(book["mediaType"], "audiobook")
        self.assertEqual(book["duration"], 47204)
        self.assertEqual(book["description"], "Pride and Prejudice\n\n(Summary from Wikipedia)")
        self.assertNotIn("publishedYear", book)

    def test_librivox_uses_the_catalogue_title_prefix(self):
        match = {"providerId": "397", "title": "Raven", "url": "https://librivox.org/the-raven-by-edgar-allan-poe/"}
        with patch("sources._librivox_query", return_value=[match]) as search:
            self.assertEqual(librivox_search("The Raven", "Edgar Allan Poe", "", 3), [match])
        search.assert_called_once_with(title="^Raven", limit=10)

    def test_librivox_missing_id(self):
        with patch("sources.get_json", return_value=None):
            self.assertIsNone(librivox_lookup("9999999"))

    def test_wikisource_excludes_chapter_and_disambiguation(self):
        root = {
            "pageid": 92337, "title": "红楼梦", "ns": 0,
            "canonicalurl": "https://zh.wikisource.org/wiki/%E7%BA%A2%E6%A5%BC%E6%A2%A6",
        }
        self.assertEqual(_wiki_book(root)["providerId"], "92337")
        self.assertIsNone(_wiki_book({**root, "title": "紅樓夢/第001回"}))
        self.assertIsNone(_wiki_book({**root, "pageprops": {"disambiguation": ""}}))

    def test_openstax_returns_requested_print_isbn(self):
        item = {
            "id": 576, "title": "Astronomy 2e", "digital_isbn_13": "978-1-951693-50-3",
            "print_isbn_13": "978-1-711470-57-3", "book_state": "live",
            "meta": {"type": "books.Book", "locale": "en"},
        }
        with patch("sources._openstax_books", return_value=[item]):
            result = openstax_search("", "", "9781711470573", 1)
        self.assertEqual(result[0]["isbn13"], "9781711470573")

    def test_identifiers_and_edition_are_preserved(self):
        otl = _otl_book({
            "id": 390, "title": "Astronomy", "edition_statement": "2e", "copyright_year": 2022,
            "isbn13": "9781951693503", "language": "eng",
            "contributors": [{"contribution": "Author", "first_name": "Andrew", "last_name": "Fraknoi"}],
            "url": "https://open.umn.edu/opentextbooks/textbooks/astronomy",
        })
        openstax = _openstax_book({
            "id": 576, "title": "Astronomy 2e", "digital_isbn_13": "978-1-951693-50-3",
            "publish_date": "2022-03-09", "meta": {
                "type": "books.Book", "locale": "en",
                "html_url": "https://openstax.org/details/books/astronomy-2e",
            },
        })
        self.assertEqual(otl["title"], openstax["title"])
        self.assertEqual(otl["isbn13"], openstax["isbn13"])
        self.assertNotEqual(otl["providerId"], openstax["providerId"])


class SnapshotTests(unittest.TestCase):
    def test_literal_quotes_and_failed_refresh_preserve_catalog(self):
        columns = (
            "title_id", "publication_title", "publication_type", "online_identifier",
            "print_identifier", "first_author", "publisher_name", "date_monograph_published_print",
            "date_monograph_published_online", "title_url", "doi_identifier",
        )
        records = [
            ("20.500.12854/186838", '"Exploring Digital Legal Landscapes', "monograph",
             "9783832559625", "9783832560065", "", "Logos Verlag Berlin", "2025", "2026-11-25",
             "https://www.logos-verlag.de/ebooks/OA/978-3-8325-5962-5.pdf", "10.30819/5962"),
            ("20.500.12854/186776", "Oskar Becker on Modalities", "monograph",
             "", "9783832550318", "Minari, Pierluigi", "Logos Verlag Berlin", "2025", "2026-11-25", "", ""),
        ]
        data = "\n".join("\t".join(row) for row in (columns, *records)).encode()

        @contextlib.contextmanager
        def feed(*args, **kwargs):
            response = io.BytesIO(data)
            response.headers = {"Last-Modified": "Wed, 25 Nov 2026 00:00:00 GMT"}
            yield response

        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"CATALOG_CACHE_DIR": folder}):
            store = LocalCatalog("doab", "unused", _doab_record, delimiter="\t", minimum=2)
            with self.assertRaises(UpstreamError) as absent:
                store.search("Exploring Digital Legal Landscapes", "", "", 3)
            self.assertEqual(absent.exception.status, 503)
            with patch("snapshots.open_source", feed):
                store._refresh()
            self.assertEqual(store.status()["records"], 2)
            with patch("snapshots.open_source", side_effect=UpstreamError()):
                with self.assertRaises(UpstreamError):
                    store._refresh()
            restarted = LocalCatalog("doab", "unused", _doab_record, delimiter="\t", minimum=2)
            matches = restarted.search("", "", "9783832559625", 1)
            self.assertEqual(matches[0]["providerId"], "20.500.12854/186838")
            self.assertEqual(matches[0]["url"], "https://www.logos-verlag.de/ebooks/OA/978-3-8325-5962-5.pdf")
            self.assertEqual(restarted.lookup("20.500.12854/186776")["title"], "Oskar Becker on Modalities")
            self.assertEqual(restarted.search("", "", "9783832560065", 1)[0]["isbn13"], "9783832560065")
            self.assertEqual(restarted.search("https://doi.org/10.30819/5962", "", "", 1)[0]["providerId"], "20.500.12854/186838")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "providerId": "20.500.12854/186838",
            "title": "Exploring Digital Legal Landscapes",
        }
        provider = Provider(
            "test-catalog", "Test Catalog", lambda *args: [self.item, self.item],
            lambda identifier: self.item if identifier == self.item["providerId"] else None,
            min_interval_ms=0,
        )
        self.server = CatalogServer(("127.0.0.1", 0), provider, "sample-token")
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, token="sample-token"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with urlopen(Request(self.base + path, headers=headers), timeout=3) as response:
            return json.load(response)

    def test_contract_and_encoded_identifier(self):
        self.assertEqual(self.get("/healthz", token="")["provider"], "test-catalog")
        self.assertTrue(self.get("/provider/info")["authenticationRequired"])
        self.assertEqual(self.get("/search?query=exploring&limit=1"), {"matches": [self.item]})
        self.assertEqual(self.get("/book/" + quote(self.item["providerId"], safe="")), self.item)
        for path, token, status in (
            ("/provider/info", "", 401),
            ("/book/absent", "sample-token", 404),
            ("/search?query=sample&limit=bad", "sample-token", 400),
        ):
            with self.assertRaises(HTTPError) as error:
                self.get(path, token=token)
            self.assertEqual(error.exception.code, status)


if __name__ == "__main__":
    unittest.main()
