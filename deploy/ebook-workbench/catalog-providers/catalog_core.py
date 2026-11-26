import contextlib
import hmac
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


VERSION = "0.1.0"
USER_AGENT = (
    f"EbookWorkbenchCatalogs/{VERSION} "
    "(https://github.com/huaqian0226/ebook-workbench)"
)
DEFAULT_TIMEOUT = 7
MAX_RESPONSE = 8 * 1024 * 1024

Book = dict


class UpstreamError(Exception):
    def __init__(self, status=502, retry_after=None):
        super().__init__(status)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    search: Callable[[str, str, str, int], list[Book]]
    lookup: Callable[[str], Book | None] | None = None
    fields: tuple[str, ...] = field(default=("title",), kw_only=True)
    media_types: tuple[str, ...] = field(default=("book",), kw_only=True)
    url_template: str | None = field(default=None, kw_only=True)
    isbn_search: bool = field(default=False, kw_only=True)
    id_max_length: int = field(default=100, kw_only=True)
    color: str | None = field(default=None, kw_only=True)
    min_interval_ms: int = field(default=500, kw_only=True)
    warmup: Callable[[], None] | None = field(default=None, kw_only=True)

    status: Callable[[], dict] | None = field(default=None, kw_only=True)

    def info(self, token=""):
        info = {
            "name": self.name,
            "key": self.key,
            "version": VERSION,
            "mediaTypes": list(self.media_types),
            "lookup": self.lookup is not None,
            "searchParams": ["limit", "isbn"] if self.isbn_search else ["limit"],
            "supportedFields": list(self.fields),
            "idMaxLength": self.id_max_length,
            "rateLimit": {"maxConcurrency": 1, "minIntervalMs": self.min_interval_ms},
            "authenticationRequired": bool(token),
        }
        if self.url_template:
            info["bookUrlTemplate"] = self.url_template
        if self.color:
            info["color"] = self.color
        return info


def authorized(token, header):
    return not token or hmac.compare_digest(
        f"Bearer {token}".encode(), header.encode()
    )


def public_url(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    try:
        url = urlsplit(value)
        if url.scheme in ("https", "http") and url.hostname and not url.username:
            return value
    except ValueError:
        pass
    return None


@contextlib.contextmanager
def open_source(url, params=None, *, not_found=False, timeout=DEFAULT_TIMEOUT,
                accept="application/json"):
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        status = exc.code
        retry_after = exc.headers.get("Retry-After")
        exc.close()
        if not_found and status == 404:
            yield None
            return
        if status == 429:
            raise UpstreamError(429, retry_after or "60") from None
        if status == 503:
            raise UpstreamError(503, retry_after) from None
        raise UpstreamError() from None
    except (URLError, TimeoutError, OSError):
        raise UpstreamError() from None
    try:
        with response:
            yield response
    except (TimeoutError, OSError):
        raise UpstreamError() from None


def get_bytes(url, params=None, *, not_found=False, timeout=DEFAULT_TIMEOUT,
              accept="*/*", max_bytes=MAX_RESPONSE):
    with open_source(url, params, not_found=not_found, timeout=timeout, accept=accept) as response:
        if response is None:
            return None
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise UpstreamError()
        return data


def get_json(url, params=None, *, not_found=False, timeout=DEFAULT_TIMEOUT):
    data = get_bytes(url, params, not_found=not_found, timeout=timeout, accept="application/json")
    if data is None:
        return None
    try:
        return json.loads(data)
    except (UnicodeError, ValueError):
        raise UpstreamError() from None


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "li", "div", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in ("p", "li", "div", "h1", "h2", "h3"):
            self.parts.append("\n")


def plain_text(value):
    if not isinstance(value, str):
        return None
    parser = _PlainText()
    parser.feed(value)
    parser.close()
    paragraphs = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n\n".join(filter(None, paragraphs))[:12000] or None


def norm(value):
    return " ".join(re.findall(r"[^\W_]+", str(value).casefold(), flags=re.UNICODE))


def isbn_digits(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r"[\s-]", "", value).upper()
    return value if re.fullmatch(r"(?:97[89][0-9]{10}|[0-9]{9}[0-9X])", value) else None


def publication_year(value):
    match = re.match(r"([12][0-9]{3})(?:-|$)", str(value or ""))
    return match.group(1) if match else None


def person_name(person):
    return " ".join(
        person[part].strip()
        for part in ("first_name", "middle_name", "last_name")
        if isinstance(person.get(part), str) and person[part].strip()
    )


def book(provider_id, title, **fields):
    return {
        "providerId": str(provider_id),
        "title": title.strip(),
        **{key: value for key, value in fields.items() if value},
    }


def ranked(matches, query, author):
    wanted = norm(query)
    wanted_author = norm(author)

    def score(match):
        title = norm(match["title"])
        authors = norm(" ".join(match.get("authors", ())))
        return (
            title != wanted,
            not title.startswith(wanted + " "),
            bool(wanted_author) and wanted_author not in authors,
        )

    return sorted(matches, key=score)
