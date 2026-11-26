import re
import time
from urllib.parse import quote

from catalog_core import (
    Provider,
    UpstreamError,
    book,
    get_json,
    isbn_digits,
    norm,
    person_name,
    plain_text,
    public_url,
    publication_year,
    ranked,
)
from snapshots import DOAB, GUTENBERG


LIBRIVOX_API = "https://librivox.org/api/feed/audiobooks/"
WIKISOURCE_API = "https://zh.wikisource.org/w/api.php"
OTL_API = "https://open.umn.edu/opentextbooks/textbooks"
OPENSTAX_API = "https://openstax.org/apps/cms/api/v2/pages/"
OPENSTAX_FIELDS = (
    "authors,digital_isbn_13,print_isbn_13,print_softcover_isbn_13,"
    "book_state,description,cover_url,publish_date,book_categories"
)

LANGUAGES = {
    "Arabic": "ar", "Bulgarian": "bg", "Catalan": "ca", "Chinese": "zh",
    "Czech": "cs", "Danish": "da", "Dutch": "nl", "English": "en",
    "French": "fr", "German": "de", "Greek": "el", "Hebrew": "he",
    "Hindi": "hi", "Hungarian": "hu", "Italian": "it", "Japanese": "ja",
    "Latin": "la", "Norwegian": "no", "Polish": "pl", "Portuguese": "pt",
    "Romanian": "ro", "Russian": "ru", "Spanish": "es", "Swedish": "sv",
    "Ukrainian": "uk",
}


def _records(payload, key):
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise UpstreamError()
    return payload[key]


def _number_id(value):
    return re.fullmatch(r"[1-9][0-9]{0,11}", str(value or "")) is not None


def _valid_item(item):
    return _number_id(item.get("id")) and isinstance(item.get("title"), str) and item["title"].strip()


def _librivox_record(item):
    authors = list(filter(None, (person_name(author) for author in item.get("authors", ()))))
    duration = str(item.get("totaltimesecs", ""))
    return book(
        item["id"],
        item["title"],
        mediaType="audiobook",
        authors=authors,
        description=plain_text(item.get("description")),
        languageCode=LANGUAGES.get(item.get("language")),
        duration=int(duration) if duration.isdecimal() else None,
        cover=public_url(item.get("coverart_jpg")),
        url=public_url(item.get("url_librivox")),
    )


def _librivox_query(**params):
    payload = get_json(
        LIBRIVOX_API,
        {**params, "format": "json", "coverart": 1},
        not_found=True,
    )
    if payload is None:
        return []
    records = _records(payload, "books")
    return [_librivox_record(item) for item in records if _valid_item(item)]


def _title_without_librivox_article(title):
    first, _, remainder = title.partition(" ")
    articles = {"the", "a", "an", "le", "la", "les", "der", "die", "das"}
    return remainder if remainder and first.casefold() in articles else title


def librivox_search(query, author, isbn, limit):
    if query:
        base = " ".join(re.sub(r"[([{][^)\]}]*[)\]}]", " ", query).split()) or query
        unadorned = _title_without_librivox_article(base)
        shortened = _title_without_librivox_article(re.split(r"[:;,]\s|\s-\s", base, maxsplit=1)[0])
        fallback = base if unadorned != base else shortened
        titles = list(dict.fromkeys((unadorned, fallback)))
        for index, title in enumerate(titles):
            if index:
                time.sleep(0.5)
            results = _librivox_query(title=f"^{title}", limit=min(20, max(10, limit)))
            matches = [result for result in results if result.get("url")]
            if matches:
                return ranked(matches, title, author)[:limit]
        return []
    if author:
        results = _librivox_query(author=author, limit=min(20, limit))
        return [result for result in results if result.get("url")]
    return []


def librivox_lookup(identifier):
    if _number_id(identifier):
        return next(iter(_librivox_query(id=identifier, limit=1)), None)
    return None


def _wiki_items(params):
    payload = get_json(
        WIKISOURCE_API,
        {
            "action": "query", "prop": "info|pageprops", "inprop": "url",
            "ppprop": "disambiguation", "format": "json", "formatversion": 2,
            "maxlag": 5, **params,
        },
    )
    if not isinstance(payload, dict) or payload.get("error"):
        if isinstance(payload, dict) and payload.get("error", {}).get("code") == "maxlag":
            raise UpstreamError(429, "10")
        raise UpstreamError()
    if "query" not in payload and payload.get("batchcomplete") is True:
        return []
    return _records(payload.get("query"), "pages")


def _wiki_book(item):
    title = item.get("title", "")
    if (not _number_id(item.get("pageid")) or item.get("ns") != 0
            or item.get("missing") or not title or "/" in title
            or "disambiguation" in item.get("pageprops", {})):
        return None
    return book(
        item["pageid"], title, mediaType="book", languageCode="zh",
        url=public_url(item.get("canonicalurl")),
    )


def wiki_search(query, author, isbn, limit):
    if not query:
        return []
    items = _wiki_items(
        {"generator": "prefixsearch", "gpssearch": query, "gpsnamespace": 0, "gpslimit": 50}
    )
    items.sort(key=lambda item: item.get("index", 0))
    return [value for item in items if (value := _wiki_book(item))][:limit]


def wiki_lookup(identifier):
    if not _number_id(identifier):
        return None
    return next((_wiki_book(item) for item in _wiki_items({"pageids": identifier})), None)


def _otl_book(item):
    title = item["title"]
    edition = item.get("edition_statement")
    if edition and not norm(title).endswith(norm(edition)):
        title += f" {edition}"
    authors = [
        person_name(person) for person in item.get("contributors", ())
        if person.get("contribution") == "Author"
    ]
    publisher = next(
        (publisher["name"] for publisher in item.get("publishers", ()) if publisher.get("name")),
        None,
    )
    language = item.get("language", "")
    return book(
        item["id"], title, mediaType="book",
        authors=list(filter(None, authors)),
        publisher=publisher,
        description=plain_text(item.get("description")),
        isbn10=isbn_digits(item.get("isbn10")),
        isbn13=isbn_digits(item.get("isbn13")),
        publishedYear=publication_year(item.get("copyright_year")),
        languageCode=language if re.fullmatch(r"[a-z]{2,3}", language or "") else None,
        genres=[subject["name"] for subject in item.get("subjects", ()) if subject.get("name")],
        url=public_url(item.get("url")),
    )


def otl_search(query, author, isbn, limit):
    wanted = isbn_digits(isbn or query)
    query_text = re.sub(r"\s+[0-9]+e$", "", query, flags=re.IGNORECASE)
    term = wanted or query_text or author
    if not term:
        return []
    payload = get_json(OTL_API + ".json", {"q": term})
    matches = [_otl_book(item) for item in _records(payload, "data") if _valid_item(item)]
    if wanted:
        matches = [item for item in matches if wanted in (item.get("isbn13"), item.get("isbn10"))]
    return ranked(matches, query, author)[:limit]


def otl_lookup(identifier):
    if not _number_id(identifier):
        return None
    payload = get_json(f"{OTL_API}/{identifier}.json", not_found=True)
    if payload is None:
        return None
    item = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(item, dict) or not _valid_item(item):
        raise UpstreamError()
    return _otl_book(item)


def _openstax_book(item, requested_isbn=None):
    meta = item.get("meta", {})
    if meta.get("type") != "books.Book":
        return None
    if not _valid_item(item):
        raise UpstreamError()
    authors = [
        entry["value"]["name"] for entry in item.get("authors", ())
        if entry.get("type") == "author" and entry.get("value", {}).get("name")
    ]
    language = meta.get("locale")
    cover = public_url(item.get("cover_url")) or ""
    if cover.split("?", 1)[0].lower().endswith(".svg"):
        cover = None
    return book(
        item["id"], item["title"], mediaType="book", publisher="OpenStax",
        authors=authors,
        description=plain_text(item.get("description")),
        isbn13=requested_isbn or isbn_digits(item.get("digital_isbn_13")) or isbn_digits(item.get("print_isbn_13")),
        publishedYear=publication_year(item.get("publish_date")),
        languageCode=language if language in ("en", "es", "pl") else None,
        cover=cover,
        genres=[
            category["subject_category"] for category in item.get("book_categories", ())
            if category.get("subject_category")
        ],
        url=public_url(meta.get("html_url")),
    )


_openstax_catalog = (0, [])


def _openstax_books():
    global _openstax_catalog
    loaded_at, records = _openstax_catalog
    if time.monotonic() - loaded_at < 21600 and records:
        return records
    catalog = []
    while True:
        payload = get_json(OPENSTAX_API, {
            "type": "books.Book", "fields": OPENSTAX_FIELDS,
            "limit": 200, "offset": len(catalog),
        })
        items = _records(payload, "items")
        catalog.extend(items)
        total = payload.get("meta", {}).get("total_count")
        if not isinstance(total, int) or not items or total > 1000:
            raise UpstreamError()
        if len(catalog) >= total:
            break
    _openstax_catalog = (time.monotonic(), catalog)
    return catalog


def openstax_search(query, author, isbn, limit):
    wanted = isbn_digits(isbn or query)
    words = norm(query or author).split()
    if not wanted and not words:
        return []
    matches = []
    for item in _openstax_books():
        if item.get("book_state") != "live":
            continue
        if wanted and wanted not in {
            isbn_digits(item.get(key))
            for key in ("digital_isbn_13", "print_isbn_13", "print_softcover_isbn_13")
        }:
            continue
        result = _openstax_book(item, requested_isbn=wanted)
        if result:
            searchable = norm(" ".join((result["title"], *result.get("authors", ()))))
            if wanted or all(word in searchable for word in words):
                matches.append(result)
    return ranked(matches, query, author)[:limit]


def openstax_lookup(identifier):
    if not _number_id(identifier):
        return None
    item = get_json(f"{OPENSTAX_API}{identifier}/", not_found=True)
    return _openstax_book(item) if item is not None else None


PROVIDERS = {
    GUTENBERG.key: GUTENBERG,
    DOAB.key: DOAB,
    "librivox": Provider(
        "librivox", "LibriVox", librivox_search, librivox_lookup,
        media_types=("audiobook",),
        fields=("title", "authors", "description", "language", "duration", "audioCover"),
        color="#3976a2",
    ),
    "wikisource-zh": Provider(
        "wikisource-zh", "中文维基文库", wiki_search, wiki_lookup,
        fields=("title", "language"),
        url_template="https://zh.wikisource.org/?curid={id}",
        color="#3165a2",
    ),
    "open-textbook-library": Provider(
        "open-textbook-library", "Open Textbook Library", otl_search, otl_lookup,
        fields=("title", "authors", "publisher", "description", "isbn", "publishedYear", "language", "genres"),
        isbn_search=True, color="#7a263a",
    ),
    "openstax": Provider(
        "openstax", "OpenStax", openstax_search, openstax_lookup,
        fields=("title", "authors", "publisher", "description", "isbn", "publishedYear", "language", "genres", "cover"),
        isbn_search=True, color="#b44d27",
    ),
}
