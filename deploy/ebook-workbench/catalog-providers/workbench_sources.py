"""Public edition and title catalogues used by the local workbench."""

import hashlib
import html
import io
import re
import tarfile
import threading
import time
from functools import lru_cache
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree as ET

from catalog_core import Provider, UpstreamError, get_bytes, get_json, public_url

SRU = "https://oxford.alma.exlibrisgroup.com/view/sru/44OXF_INST"
SOLO = "https://solo.bodleian.ox.ac.uk/discovery/fulldisplay?docid=alma{id}&context=L&vid=44OXF_INST:SOLO"
STANDARD = "https://standardebooks.org"
PROGRAMMING = "https://codeload.github.com/EbookFoundation/free-programming-books/tar.gz/refs/heads/main"


def canonical_isbn(value):
    match = re.match(r"[0-9Xx-]+", value.strip())
    n = match.group().replace("-", "").upper() if match else ""
    if len(n) == 10 and n[:9].isdigit() and (n[-1].isdigit() or n[-1] == "X"):
        if sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(n)) % 11:
            return ""
        n = "978" + n[:9]
        return n + str(
            -sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(n)) % 10
        )
    if (
        len(n) == 13
        and n.isdigit()
        and not sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(n)) % 10
    ):
        return n
    return ""


def solo_record(node, requested_isbn):
    def values(tag, code):
        return [
            s.text.strip()
            for s in node.findall(
                f'{{*}}datafield[@tag="{tag}"]/{{*}}subfield[@code="{code}"]'
            )
            if s.text and s.text.strip()
        ]

    def field(tag, code):
        return next(iter(values(tag, code)), "").rstrip(" /:,;")

    mms = node.findtext('{*}controlfield[@tag="001"]', "")
    title = field("245", "a")
    if not mms.isdigit() or not title:
        return None
    r = {"providerId": mms, "title": title, "url": SOLO.format(id=mms)}
    names = []
    for tag in ["100", "110", "700"]:
        for name in values(tag, "a"):
            name = name.rstrip(", ")
            if tag != "110" and name.count(",") == 1:
                family, given = name.split(",", 1)
                name = given.strip() + " " + family
            if name not in names:
                names.append(name)
    if names:
        r["authors"] = names
    for key, val in [
        ("subtitle", field("245", "b")),
        ("publisher", field("264", "b") or field("260", "b")),
    ]:
        if val:
            r[key] = val
    year = re.search(r"\b[12]\d{3}\b", field("264", "c") or field("260", "c"))
    if year:
        r["publishedYear"] = year.group()
    numbers = {n for item in values("020", "a") if (n := canonical_isbn(item))}
    preferred = canonical_isbn(requested_isbn)
    if preferred in numbers:
        r["isbn13"] = preferred
    elif len(numbers) == 1:
        r["isbn13"] = next(iter(numbers))
    return r


def solo_fetch(cql, isbn, limit):
    params = {
        "version": "1.2",
        "operation": "searchRetrieve",
        "query": cql,
        "recordSchema": "marcxml",
        "maximumRecords": min(limit, 12),
    }
    root = ET.fromstring(get_bytes(SRU, params, timeout=20, accept="application/xml"))
    if root.find(".//{*}diagnostic") is not None:
        raise UpstreamError(502)
    return [
        r
        for n in root.findall(".//{*}recordData/{*}record")
        if (r := solo_record(n, isbn))
    ]


def solo_search(query, author, isbn, limit):
    # SRU uses CQL quoted terms; keep quotes, escapes and CQL masks out of user terms.
    def term(value):
        return re.sub(r'["\\*?^\x00-\x1f]', " ", value).strip()[:220]

    number = canonical_isbn(isbn or query)
    if number:
        return solo_fetch('alma.isbn="' + number + '"', number, limit)
    clauses = []
    if title_term := term(query):
        clauses.append(f'alma.title="{title_term}"')
    if author_term := term(author):
        # MARC names are often surname-first while readers type given names first.
        clauses.append(f'alma.creator all "{author_term}"')
    return solo_fetch(" and ".join(clauses), "", limit) if clauses else []


def solo_lookup(key):
    if not re.fullmatch(r"\d{1,25}", key):
        return None
    return next(iter(solo_fetch('alma.mms_id="' + key + '"', "", 1)), None)


def standard_list(data):
    root = ET.fromstring(data)
    editions = []
    for node in root.findall('.//{*}li[@typeof="schema:Book"]'):
        path = node.get("about", "")
        if not re.fullmatch(r"/ebooks/(?:[a-z0-9-]+/){1,4}[a-z0-9-]+", path):
            continue
        names = [
            " ".join("".join(span.itertext()).split())
            for span in node.findall('.//{*}span[@property="schema:name"]')
        ]
        if names and names[0]:
            editions.append(
                {
                    "providerId": path.removeprefix("/ebooks/"),
                    "title": names[0],
                    "authors": list(dict.fromkeys(names[1:])),
                    "publisher": "Standard Ebooks",
                    "languageCode": "en",
                    "url": STANDARD + path,
                }
            )
    return editions


def standard_search(query, author, isbn, limit):
    text = " ".join(v for v in (query, author) if v).strip()
    if not text or canonical_isbn(text):
        return []
    return standard_list(get_bytes(STANDARD + "/ebooks?" + urlencode({"query": text})))[
        :limit
    ]


def programming_records(markdown, language):
    rows = []
    for line in markdown.splitlines():
        match = re.match(
            r"^\* \[(.+?)\]\((https?://[^\s]+)\)(?:\s+-\s+([^(*]*))?", line
        )
        if not match:
            continue
        title, url, authors = match.groups()
        if not urlsplit(url).hostname or not title.strip():
            continue
        row = {
            "title": html.unescape(title)
            .replace("\\[", "[")
            .replace("\\]", "]")
            .strip(),
            "url": url,
            "languageCode": language,
        }
        # Translations of a single online book may share a website.
        row["providerId"] = hashlib.sha256(
            (language + "\n" + url + "\n" + row["title"]).encode()
        ).hexdigest()[:32]
        if authors:
            authors = re.split(r"`?trl\.?:|\s+:", authors)[0].strip(" ,*`")
            if authors:
                row["authors"] = [
                    html.unescape(a).strip(" \u200f\u200e")
                    for a in authors.split(",")
                    if a.strip()
                ]
        rows.append(row)
    return rows


_program_lock = threading.Lock()
_program_cache = {}
_program_updated = 0.0


def program_catalog():
    global _program_cache, _program_updated
    with _program_lock:
        if _program_cache and time.monotonic() - _program_updated < 86400:
            return _program_cache
        rows = {}
        try:
            raw = get_bytes(PROGRAMMING)
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                for item in archive:
                    m = re.fullmatch(
                        r"[^/]+/books/free-programming-books-([\w-]+)\.md", item.name
                    )
                    if not m or not item.isfile() or item.size > 2_000_000:
                        continue
                    language = m[1].split("-")[0]
                    if language in ("langs", "subjects"):
                        language = "en"
                    if not re.fullmatch(r"[a-z]{2,3}", language):
                        continue
                    for row in programming_records(
                        archive.extractfile(item).read().decode("utf-8-sig"), language
                    ):
                        rows[row["providerId"]] = row
            if not rows:
                raise UpstreamError(502)
        except (OSError, ValueError, tarfile.TarError, UpstreamError):
            if not _program_cache:
                raise
            return _program_cache
        _program_cache, _program_updated = rows, time.monotonic()
        return rows


def program_search(query, author, isbn, limit):
    title, writer = query.strip().casefold(), author.strip().casefold()
    if not (title or writer) or isbn:
        return []
    matches = [
        row
        for row in program_catalog().values()
        if title in row["title"].casefold()
        and writer in " ".join(row.get("authors", [])).casefold()
    ]
    matches.sort(
        key=lambda row: (
            title != row["title"].casefold(),
            len(row["title"]),
            row["languageCode"] not in ("en", "zh"),
        )
    )
    return matches[:limit]


PEPPER_ROOT = "https://www.peppercarrot.com/cn/webcomic/"


@lru_cache(maxsize=2)
def pepper_episodes(day):
    page = get_bytes("https://www.peppercarrot.com/cn/webcomics/index.html").decode(
        "utf-8"
    )
    result = {}
    for figure in re.finditer(
        r'<figure\b[^>]*class="([^"]+)"[^>]*>(.*?)</figure>', page, re.DOTALL
    ):
        if "translated" not in figure[1].split():
            continue
        caption = re.search(
            r'<figcaption>\s*<a href="([^"]+)">([^<]+)</a>.*?(\d{4}-\d{2}-\d{2})',
            figure[2],
            re.DOTALL,
        )
        if not caption:
            continue
        episode = re.fullmatch(
            re.escape(PEPPER_ROOT) + r"ep(\d+)_([a-zA-Z0-9_-]+)\.html", caption[1]
        )
        if not episode:
            continue
        key = episode[1]
        result[key] = {
            "providerId": key,
            "title": html.unescape(caption[2]).strip(),
            "authors": ["David Revoy"],
            "series": [{"series": "小辣椒与萝卜头", "sequence": key}],
            "mediaType": "comic",
            "languageCode": "zh",
            "publishedDate": caption[3],
            "publishedYear": caption[3][:4],
            "url": caption[1],
        }
    if not result:
        raise UpstreamError(502)
    return result


def pepper_search(query, author, isbn, limit):
    if isbn or (author and author.casefold() not in "david revoy"):
        return []
    q = query.casefold().strip()
    rows = pepper_episodes(int(time.time() // 86400)).values()
    series = ["pepper&carrot", "pepper and carrot", "pepper & carrot", "小辣椒与萝卜头"]
    for name in series:
        if name in q:
            q = q.replace(name, "").strip()
    if not q and not query and not author:
        return []
    return [
        r
        for r in rows
        if q in r["title"].casefold()
        or q in r["url"].split("/")[-1].replace("-", " ").casefold()
    ][:limit]


def apple_uk_record(row):
    if row.get("kind") != "ebook" or not row.get("trackName") or not row.get("trackId"):
        return None
    url = public_url(row.get("trackViewUrl"))
    if (
        not url
        or urlsplit(url).hostname != "books.apple.com"
        or not urlsplit(url).path.startswith("/gb/")
    ):
        return None
    result = {"providerId": str(row["trackId"]), "title": row["trackName"], "url": url}
    if row.get("artistName"):
        result["authors"] = [row["artistName"]]
    if row.get("releaseDate"):
        result["publishedDate"] = row["releaseDate"][:10]
        result["publishedYear"] = row["releaseDate"][:4]
    return result


def apple_uk_search(query, author, isbn, limit):
    term = " ".join(v for v in (query, author) if v)
    if not term or isbn:
        return []
    data = get_json(
        "https://itunes.apple.com/search",
        {
            "country": "gb",
            "media": "ebook",
            "entity": "ebook",
            "term": term,
            "limit": min(limit, 25),
        },
    )
    return [r for item in data.get("results", []) if (r := apple_uk_record(item))]


def apple_uk_lookup(key):
    if not key.isdigit():
        return None
    data = get_json(
        "https://itunes.apple.com/lookup",
        {"country": "gb", "id": key, "entity": "ebook"},
    )
    return next(
        (r for item in data.get("results", []) if (r := apple_uk_record(item))), None
    )


PROVIDERS = {
    p.key: p
    for p in (
        Provider(
            "apple-books-gb",
            "Apple Books · 英国",
            apple_uk_search,
            apple_uk_lookup,
            fields=("title", "authors", "publishedYear"),
            min_interval_ms=3100,
        ),
        Provider(
            "oxford-solo",
            "Oxford SOLO",
            solo_search,
            solo_lookup,
            fields=(
                "title",
                "subtitle",
                "authors",
                "publisher",
                "publishedYear",
                "isbn",
            ),
            isbn_search=True,
            url_template=SOLO,
        ),
        Provider(
            "standard-ebooks",
            "Standard Ebooks",
            standard_search,
            fields=("title", "authors", "publisher", "language"),
            id_max_length=450,
        ),
        Provider(
            "pepper-carrot-zh",
            "Pepper&Carrot · 简体中文",
            pepper_search,
            lambda key: pepper_episodes(int(time.time() // 86400)).get(key),
            fields=(
                "title",
                "authors",
                "language",
                "seriesName",
                "seriesIndex",
                "publishedYear",
            ),
            # Requests offers ebook and audiobook; ebook requests may include comics.
            media_types=("book", "comic"),
        ),
        Provider(
            "free-programming-books",
            "Free Programming Books",
            program_search,
            lambda key: program_catalog().get(key),
            fields=("title", "authors", "language"),
        ),
    )
}
