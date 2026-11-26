import csv
import gzip
import io
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from catalog_core import Provider, UpstreamError, book, isbn_digits, norm, open_source, public_url, publication_year


DOAB_TSV = "https://memo.doabooks.org/file/oapen/DOAB_KBART_books.tsv"
GUTENBERG_GZ = "https://gutenberg.pglaf.org/cache/epub/feeds/pg_catalog.csv.gz"
GUTENBERG_MIRROR = "https://gutenberg.pglaf.org/cache/epub/{id}/"
REFRESH_INTERVAL = 7 * 86400
FAILURE_INTERVAL = 8 * 3600
MAX_MISS_AGE = 30 * 86400


def _split(value, delimiter=";"):
    return [part.strip() for part in (value or "").split(delimiter) if part.strip()]


def _doi(value):
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", (value or "").strip(), flags=re.IGNORECASE)
    return value.casefold() if re.fullmatch(r"10\.\d{4,9}/[^\s]+", value, re.IGNORECASE) else None


def _doab_record(row):
    identifier, title = row["title_id"], row["publication_title"]
    if (not title or row["publication_type"].casefold() != "monograph"
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+/[0-9]+", identifier)):
        return None
    isbns = list(filter(None, (
        isbn_digits(value)
        for value in (row["online_identifier"], row["print_identifier"], *_split(row.get("other_ISBNs")))
    )))
    result = book(
        identifier, " ".join(title.split()), mediaType="book",
        authors=[row["first_author"]] if row["first_author"] else [],
        publisher=row["publisher_name"],
        publishedYear=publication_year(
            row["date_monograph_published_print"] or row["date_monograph_published_online"]
        ),
        isbn13=next((isbn for isbn in isbns if len(isbn) == 13), None),
        isbn10=next((isbn for isbn in isbns if len(isbn) == 10), None),
        url=public_url(row.get("title_url")) or f"https://directory.doabooks.org/handle/{identifier}",
    )
    identifiers = set(isbns)
    identifiers.update(filter(None, (_doi(value) for value in _split(row.get("doi_identifier")))))
    return result, identifiers


def _gutenberg_record(row):
    identifier, title = row["Text#"], row["Title"]
    if not title or row["Type"] != "Text" or not re.fullmatch(r"[1-9][0-9]{0,8}", identifier):
        return None
    authors = [
        re.sub(r",\s*(?:[?0-9]+-?[?0-9]*|approximately.*)$", "", author).strip()
        for author in _split(row["Authors"])
    ]
    languages = _split(row["Language"])
    result = book(
        identifier, " ".join(title.split()), mediaType="book",
        authors=authors,
        languageCode=languages[0] if len(languages) == 1 else None,
        genres=_split(row["Subjects"])[:10],
        url=GUTENBERG_MIRROR.format(id=identifier),
    )
    return result, set()


def _read_feed(response, map_record, delimiter, compressed):
    payload = gzip.GzipFile(fileobj=response) if compressed else response
    with io.TextIOWrapper(payload, encoding="utf-8-sig", newline="") as stream:
        # KBART is a raw tab-separated export and can contain literal double quotes.
        quoting = csv.QUOTE_NONE if delimiter == "\t" else csv.QUOTE_MINIMAL
        source = csv.DictReader(stream, delimiter=delimiter, quoting=quoting)
        deadline = time.monotonic() + 240
        for row_number, row in enumerate(source):
            if row_number > 500000 or time.monotonic() > deadline:
                raise UpstreamError()
            if None not in row and None not in row.values():
                result = map_record(row)
                if result is not None:
                    yield result


class LocalCatalog:
    def __init__(self, key, url, map_record, *, delimiter=",", compressed=False, minimum=10000, version=1):
        self.key = key
        self.url = url
        self.map_record = map_record
        self.delimiter = delimiter
        self.compressed = compressed
        self.minimum = minimum
        self.version = version
        self.state = "warming"

    @property
    def path(self):
        root = Path(os.environ.get("CATALOG_CACHE_DIR", "/tmp/ebook-catalogs")).expanduser().resolve()
        return root / f"{self.key}-v{self.version}.sqlite3"

    def _open(self):
        return sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)

    def _refresh(self):
        destination = self.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staging = tempfile.mkstemp(prefix=f".{self.key}-", dir=destination.parent)
        os.close(descriptor)
        try:
            count = 0
            with closing(sqlite3.connect(staging)) as database, database:
                database.execute(
                    "CREATE TABLE books (id TEXT PRIMARY KEY, title TEXT NOT NULL, "
                    "authors TEXT NOT NULL, payload TEXT NOT NULL)"
                )
                database.execute(
                    "CREATE TABLE identifiers (value TEXT, book_id TEXT, PRIMARY KEY (value, book_id))"
                )
                database.execute("CREATE TABLE snapshot (retrieved_at REAL, source_date TEXT, count INTEGER)")
                with open_source(self.url, timeout=30, accept="*/*") as response:
                    source_date = response.headers.get("Last-Modified")
                    for result, identifiers in _read_feed(
                        response, self.map_record, self.delimiter, self.compressed
                    ):
                        title = norm(result["title"])
                        if not title:
                            continue
                        insert = database.execute(
                            "INSERT OR IGNORE INTO books VALUES (?, ?, ?, ?)",
                            (
                                result["providerId"], title, norm(" ".join(result.get("authors", ()))),
                                json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                            ),
                        )
                        count += insert.rowcount
                        database.executemany(
                            "INSERT OR IGNORE INTO identifiers VALUES (?, ?)",
                            ((identifier, result["providerId"]) for identifier in identifiers),
                        )
                if count < self.minimum:
                    raise UpstreamError()
                database.execute("INSERT INTO snapshot VALUES (?, ?, ?)", (time.time(), source_date, count))
            os.replace(staging, destination)
            logging.info("provider=%s snapshotRecords=%s", self.key, count)
        finally:
            Path(staging).unlink(missing_ok=True)

    def _refresh_loop(self):
        while True:
            snapshot = self._snapshot()
            remaining = REFRESH_INTERVAL - (time.time() - snapshot[0]) if snapshot else 0
            if remaining > 0:
                time.sleep(remaining)
            try:
                self._refresh()
            except (UpstreamError, OSError, ValueError, EOFError, KeyError, csv.Error, sqlite3.Error) as exc:
                logging.warning("provider=%s snapshotError=%s", self.key, type(exc).__name__)
                self.state = "unavailable"
                time.sleep(FAILURE_INTERVAL)

    def warmup(self):
        threading.Thread(target=self._refresh_loop, daemon=True, name=f"{self.key}-snapshot").start()

    def _snapshot(self):
        try:
            with closing(self._open()) as database:
                return database.execute("SELECT retrieved_at, source_date, count FROM snapshot").fetchone()
        except sqlite3.Error:
            return None

    def status(self):
        snapshot = self._snapshot()
        if not snapshot:
            return {"status": self.state}
        timestamp, source_date, records = snapshot
        return {
            "status": "ready",
            "snapshot": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
            "sourceLastModified": source_date,
            "records": records,
            "stale": time.time() - timestamp > REFRESH_INTERVAL,
        }

    def _query(self, sql, params):
        try:
            with closing(self._open()) as database:
                results = [json.loads(row[0]) for row in database.execute(sql, params)]
                if not results:
                    timestamp, = database.execute("SELECT retrieved_at FROM snapshot").fetchone()
                    if time.time() - timestamp > MAX_MISS_AGE:
                        raise UpstreamError(503, "3600")
                return results
        except sqlite3.Error:
            raise UpstreamError(503, "60") from None

    def search(self, query, author, isbn, limit):
        if self.key == "doab" and (wanted := isbn_digits(isbn or query) or _doi(query)):
            results = self._query(
                "SELECT b.payload FROM identifiers i JOIN books b ON i.book_id=b.id "
                "WHERE i.value=? ORDER BY b.title, b.id LIMIT ?",
                (wanted, limit),
            )
            if isbn_digits(wanted):
                for result in results:
                    result.pop("isbn10", None)
                    result.pop("isbn13", None)
                    result[f"isbn{len(wanted)}"] = wanted
            return results

        title, author_name = norm(query), norm(author)
        terms = (title or author_name).split()[:12]
        if not terms:
            return []
        clause = " AND ".join("instr(title || ' ' || authors, ?) > 0" for _ in terms)
        return self._query(
            "SELECT payload FROM books WHERE " + clause + " "
            "ORDER BY (title = ?) DESC, (instr(title, ? || ' ') = 1) DESC, "
            "(instr(authors, ?) > 0) DESC, length(title), title, CAST(id AS INTEGER), id LIMIT ?",
            (*terms, title, title, author_name, limit),
        )

    def lookup(self, identifier):
        return next(iter(self._query("SELECT payload FROM books WHERE id = ?", (identifier,))), None)


doab = LocalCatalog("doab", DOAB_TSV, _doab_record, delimiter="\t", version=2)
gutenberg = LocalCatalog("gutenberg", GUTENBERG_GZ, _gutenberg_record, compressed=True)

DOAB = Provider(
    doab.key, "DOAB", doab.search, doab.lookup,
    fields=("title", "authors", "isbn", "publisher", "publishedYear"),
    isbn_search=True, color="#163455", warmup=doab.warmup, status=doab.status,
)
GUTENBERG = Provider(
    gutenberg.key, "Project Gutenberg", gutenberg.search, gutenberg.lookup,
    fields=("title", "authors", "genres", "language"),
    id_max_length=9, color="#a04f37", warmup=gutenberg.warmup, status=gutenberg.status,
)
