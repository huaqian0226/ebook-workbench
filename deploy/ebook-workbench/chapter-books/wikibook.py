"""Compile the reviewed Wikisource edition of 老殘遊記 from pinned public revisions."""

import hashlib
import html
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass

ORIGIN = "https://zh.wikisource.org"
LICENSE = "https://creativecommons.org/licenses/by-sa/4.0/"
EPUB_TYPE = "application/epub+zip"
CONTACT = "https://github.com/huaqian0226/ebook-workbench/issues"
PAGE_LIMIT = 2 * 1024 * 1024

TOC_LINE = re.compile(r"^\*\[\[/([^|\[\]]+)\|([^\[\]]+)\]\]([^\n]*)$", re.MULTILINE)
WRAPPER = re.compile(
    r'<div class="?text"?\>\{\{Textquality\|50%\}\}\n'
    r'\{\{novel\|(?P<book>[^|]+)\|(?P<title>[^|]+)\|[^}]*\}\}[ \t\n]*'
    r'(?P<body>.+?)\n+\{\{novel-f\|[^}]*\}\}\n</div>\n__NOEDITSECTION__',
    re.DOTALL,
)
GLYPH = re.compile(r"\{\{!\|([^|{}]+)\|([^|{}]+)\}\}")
OTHER_MARKUP = re.compile(r"\{\{|\}\}|\[\[|\]\]|<[a-z/!]|^\s*[;:#*=]", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Revision:
    page: str
    number: int
    digest: str

    @property
    def source_url(self):
        return f"{ORIGIN}/w/index.php?oldid={self.number}"


@dataclass(frozen=True)
class Book:
    slug: str
    title: str
    author: str
    aliases: tuple[str, ...]
    modified: str
    chapter_count: int
    toc: Revision
    chapters: tuple[Revision, ...]

    @property
    def edition_id(self):
        return f"v2-{self.toc.number}-{self.chapters[-1].number}"

    def release(self):
        return {
            "slug": self.slug,
            "title": self.title,
            "author": self.author,
            "aliases": self.aliases,
            "language": "zh-Hant",
            "sourceUrl": self.toc.source_url,
            "chapterCount": self.chapter_count,
            "editionId": self.edition_id,
        }


def fetch_pinned_revisions(revisions):
    params = urllib.parse.urlencode({
        "action": "query",
        "format": "json",
        "formatversion": 2,
        "prop": "revisions",
        "rvprop": "ids|content",
        "rvslots": "main",
        "revids": "|".join(str(item.number) for item in revisions),
    })
    request = urllib.request.Request(f"{ORIGIN}/w/api.php?{params}", headers={
        "User-Agent": f"OxfordEbookWorkbench/1.0 ({CONTACT})",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            data = response.read(PAGE_LIMIT + 1)
    except urllib.error.HTTPError as error:
        raise ValueError(f"Wikisource returned HTTP {error.code}") from error
    if len(data) > PAGE_LIMIT:
        raise ValueError("Wikisource response exceeded the size limit")

    payload = json.loads(data)
    if payload.get("error") or payload.get("warnings"):
        raise ValueError("Wikisource could not supply the reviewed revision set")
    expected_pages = {item.number: item.page for item in revisions}
    pages = {}
    for page in payload["query"]["pages"]:
        for revision in page.get("revisions", []):
            number = revision["revid"]
            if expected_pages.get(number) != page["title"] or number in pages:
                raise ValueError(f"Unexpected or duplicate Wikisource revision {number}")
            pages[number] = revision["slots"]["main"]["content"]
    return pages


def compile_epub(book, fetch_pages=fetch_pinned_revisions):
    revisions = (book.toc, *book.chapters)
    pages = fetch_pages(revisions)
    if set(pages) != {revision.number for revision in revisions}:
        raise ValueError("Wikisource returned an incomplete revision set")
    for revision in revisions:
        if hashlib.sha256(pages[revision.number].encode()).hexdigest() != revision.digest:
            raise ValueError(f"Source content differs from reviewed revision {revision.number}")

    table = [(f"{book.title}/{page}", "".join((title, subtitle)))
             for page, title, subtitle in TOC_LINE.findall(pages[book.toc.number])]
    ordered_pages = [f"{book.title}/自敘", *(f"{book.title}/第{number:02}回"
                                            for number in range(1, book.chapter_count + 1))]
    if [page for page, title in table] != ordered_pages or [r.page for r in book.chapters] != ordered_pages:
        raise ValueError("Wikisource contents did not match the reviewed preface and chapter order")

    sections = []
    for revision, (_, title) in zip(book.chapters, table, strict=True):
        title = "　".join(title.split())
        body = render_chapter(book.title, title, pages[revision.number])
        sections.append((title, body, revision.source_url))
    return pack_epub(book, sections)


def render_chapter(book_title, title, wikitext):
    match = WRAPPER.fullmatch(wikitext)
    if not match or match["book"] != book_title or "　".join(match["title"].split()) != title:
        raise ValueError(f"Missing or changed Wikisource structure in {title}")
    body = match["body"].removeprefix("== 自敘 ==\n\n")
    if not body.strip() or OTHER_MARKUP.search(GLYPH.sub("", re.sub(r"^::;", "", body, flags=re.MULTILINE))):
        raise ValueError(f"Empty chapter or unsupported Wikisource markup in {title}")

    rendered = []
    for paragraph in re.split(r"\n[ \t]*\n", body):
        lines = paragraph.splitlines()
        if all(line.startswith("::;") for line in lines):
            verse = "<br/>".join(render_glyphs(line.removeprefix("::;")) for line in lines)
            rendered.append(f'<blockquote><p>{verse}</p></blockquote>')
        else:
            rendered.append(f'<p>{"<br/>".join(render_glyphs(line.removeprefix("::;")) for line in lines)}</p>')
    return "\n".join(rendered)


def render_glyphs(line):
    parts = GLYPH.split(line)
    output = [html.escape(parts[0])]
    for glyph, description, tail in zip(parts[1::3], parts[2::3], parts[3::3], strict=True):
        output.append(f'<span title="{html.escape(description)}">{html.escape(glyph)}</span>{html.escape(tail)}')
    return "".join(output)


def pack_epub(book, sections):
    title = html.escape(book.title)
    author = html.escape(book.author)
    entry = '<item id="{}" href="{}" media-type="application/xhtml+xml"{}/>'
    manifest = [entry.format("nav", "nav.xhtml", ' properties="nav"'),
                entry.format("credits", "credits.xhtml", "")]
    spine = []
    nav = []
    credits = [f'<li><a href="{book.toc.source_url}">目錄原文</a></li>']
    files = {
        "META-INF/container.xml": '<?xml version="1.0" encoding="utf-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>'
        '</rootfiles></container>',
    }
    for index, (section_title, body, source) in enumerate(sections):
        escaped_title = html.escape(section_title)
        section_id = f"section-{index:02}"
        filename = f"{section_id}.xhtml"
        manifest.append(entry.format(section_id, filename, ""))
        spine.append(f'<itemref idref="{section_id}"/>')
        nav.append(f'<li><a href="{filename}">{escaped_title}</a></li>')
        credits.append(f'<li><a href="{source}">{escaped_title}</a></li>')
        files[f"EPUB/{filename}"] = xhtml(escaped_title, f"<h1>{escaped_title}</h1>\n{body}")

    spine.append('<itemref idref="credits"/>')
    nav.append('<li><a href="credits.xhtml">版本與授權</a></li>')
    files["EPUB/credits.xhtml"] = xhtml(title, f"""<h1>{title}</h1><p>{author}</p>
<p>維基文庫標記原作出版於 1907 年，本電子版收錄該目錄所列的自敘與二十回。</p>
<h2>版本與授權</h2>
<p>劉鶚原作屬公有領域。本 EPUB 改編自維基文庫貢獻者的轉錄，使用
<a href="{LICENSE}">CC BY-SA 4.0</a>授權。轉換移除網頁導覽和維基版面標記，保留章回、段落和詩句，
並加上 EPUB 目錄。下列連結指向實際使用的修訂，可由每頁的歷史查看貢獻者。</p>
<ul>{"".join(credits)}</ul>""")
    files["EPUB/nav.xhtml"] = xhtml(title, f'<nav epub:type="toc" id="toc"><h1>目錄</h1><ol>{"".join(nav)}</ol></nav>')
    files["EPUB/package.opf"] = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="zh-Hant">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">urn:bookorbit:chapter-books:{book.slug}:{book.edition_id}</dc:identifier>
    <dc:title>{title}</dc:title><dc:creator>{author}</dc:creator><dc:language>zh-Hant</dc:language>
    <dc:source>{book.toc.source_url}</dc:source><dc:rights>{LICENSE}</dc:rights>
    <meta property="dcterms:modified">{book.modified}</meta>
  </metadata>
  <manifest>{"".join(manifest)}</manifest>
  <spine>{"".join(spine)}</spine>
</package>"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as epub:
        epub.writestr(zipfile.ZipInfo("mimetype"), EPUB_TYPE)
        for name, content in files.items():
            epub.writestr(zipfile.ZipInfo(name), content, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def xhtml(title, body):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-Hant" xml:lang="zh-Hant">
  <head><title>{title}</title></head>
  <body>{body}</body>
</html>"""


LAO_CAN = Book(
    "lao-can-youji", "老殘遊記", "劉鶚", ("老残游记", "The Travels of Lao Can"),
    "2026-11-01T06:42:20Z", 20,
    Revision("老殘遊記", 12704905, "f3ac3007b9fb1ef748e2605f61b918c3aab11706855f501e71fa7dddda5e7d1b"),
    (
        Revision("老殘遊記/自敘", 2598346, "5f3a4d21be6ab0b90c6997e0a6fbae500a209ed70e6570bba56e1de767042311"),
        Revision("老殘遊記/第01回", 2367222, "40d45f2d9cf1aa23a452364b885b7cd710c346a1b1c93d8acd26707de04e01b4"),
        Revision("老殘遊記/第02回", 2367223, "4d71f9d7b1899391512f4d4959f9c8c09e0f0364a3416b5a5c4a70802595d75d"),
        Revision("老殘遊記/第03回", 2367233, "e16d973d528e43a2377c3ae97cffabcdaa6b116e0f822c3a05b96ac8723e3157"),
        Revision("老殘遊記/第04回", 2367238, "8dc17ae2bdd991ef8054e43087d2684e195530fdd26cc209ed02ccdc52460330"),
        Revision("老殘遊記/第05回", 2367240, "8f38f437f7f770702097c3a4fcc59fd7d53656a194a9acdf288b9588271e9dd6"),
        Revision("老殘遊記/第06回", 2367239, "4cf8f6abfdc397d0409b86bf7bffffecce1718746fbd3e3ec2b815847d98f310"),
        Revision("老殘遊記/第07回", 2367225, "c8924310cd8e3d9abc36598baaaf2af458708b530461e8ebf76b9f5cb0ab3ab3"),
        Revision("老殘遊記/第08回", 2367237, "05753aeb08a69603dc60b9c0c1502f0db2014331654cf22e1aa2d260ba4a2ee6"),
        Revision("老殘遊記/第09回", 2367229, "898b1e0ee66df00f51deb4c1a1f6eefb54a68698289518b693726d57bb268630"),
        Revision("老殘遊記/第10回", 2367227, "ca6ff0ef5fc096d3ee3b4be808b1fc36771641cfa06da480ba639b59307c0106"),
        Revision("老殘遊記/第11回", 2367228, "8c80bda5b64d602cdcae8a5f856868b3d8b8416c10f230be51d71cd06f074b79"),
        Revision("老殘遊記/第12回", 2367226, "9010973da10d2fed81d8786d782c21ddbea07253eb0c34286a2b3de58e570063"),
        Revision("老殘遊記/第13回", 2367234, "530cfd5edb3c4001efeb860a3fea795475968fda0e0ea2c12add21f1c0b82ce6"),
        Revision("老殘遊記/第14回", 2367224, "e69932df7b13ff86bf0a20abec5d5811a0335b261d4dc81c2165ad6ea7bcd11d"),
        Revision("老殘遊記/第15回", 2367235, "df6e0f0de9177aa6ff8257ff6a4bcf1ae062e6e902b4ee6f8eecd926c861e3bf"),
        Revision("老殘遊記/第16回", 2367231, "cf76e3c9c3db52a07bb4e51c228d059b23d0e4a76ed808a755381d4d90664aec"),
        Revision("老殘遊記/第17回", 2367236, "aaafb72eb2e470569a05f6bf81425932ac7ffd2632c0fc793d4b8c529f66fc07"),
        Revision("老殘遊記/第18回", 2367232, "386a2cb354aa278336f9b6bd30b4d3cd31cbce11a22a20b2d405c34f7450e24f"),
        Revision("老殘遊記/第19回", 2367230, "a9b81106512cdce8197fe861c35fd5c8fa112e1573d2124c0dc08a2c34cbc428"),
        Revision("老殘遊記/第20回", 2367241, "1eab24ca20874afa81f59139ca6f3ceddcb9c2ddf8a02b857bdf3d51ecef38a8"),
    ),
)
