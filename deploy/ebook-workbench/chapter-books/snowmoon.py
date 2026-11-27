"""Build the 32-chapter independent Simplified Chinese edition from its pinned GPL source."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

REV = "d11edb183ec0c1e41f8e02b939047b68c3b55793"
SOURCE = "https://github.com/sdsunqian/Snowmoon/tree/" + REV
ARCHIVE = "https://codeload.github.com/sdsunqian/Snowmoon/zip/" + REV
DIGEST = "23a861623e098607f9e72a237b54bd0701c3b15e3f52750d15ea844484913e7b"
RELEASE = dict(
    slug="snowmoon-zh",
    title="雪月",
    author="Vitalik Buterin",
    aliases=["Snowmoon", "雪月（Snowmoon）"],
    language="zh-Hans",
    sourceUrl=SOURCE,
    chapterCount=32,
    editionId="zh2-" + REV[:12],
)
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
# HTML's SVG parser restores mixed-case names. XML EPUB readers require those names literally.
SVG_CASE = {
    k.lower(): k
    for k in (
        "viewBox",
        "markerWidth",
        "markerHeight",
        "markerUnits",
        "refX",
        "refY",
        "attributeName",
        "calcMode",
        "repeatCount",
        "keyTimes",
        "patternUnits",
        "clipPath",
        "radialGradient",
    )
}


def repair_diagrams(body, original):
    """Reinstate local SVG references dropped by the upstream HTML translation pass."""
    diagrams = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.I)
    originals = diagrams.findall(original)
    rendered = diagrams.findall(body)
    source_index = 0
    tag = re.compile(r"<([A-Za-z][\w:-]*)\b[^>]*>")
    for number, translated in enumerate(rendered, 1):
        refs = set(re.findall(r"(?:url\(#|href=\"#)([\w-]+)", translated))
        for value in re.findall(r'aria-labelledby="([^"]+)"', translated):
            refs.update(value.split())
        if not refs:
            continue
        # The full original HTML also includes unrelated icons in its page header and footer.
        while source_index < len(originals):
            source = originals[source_index]
            source_index += 1
            if refs <= set(re.findall(r'\sid="([^"]+)"', source)):
                break
        else:
            raise ValueError("No corresponding original diagram")
        positions, counts = {}, {}
        for m in tag.finditer(source):
            name = m[1].lower()
            counts[name] = counts.get(name, 0) + 1
            ident = re.search(r'\sid="([^"]+)"', m[0])
            if ident and ident[1] in refs:
                positions[(name, counts[name])] = ident[1]
        counts.clear()
        attached = set()

        def restore(m):
            name = m[1].lower()
            counts[name] = counts.get(name, 0) + 1
            ident = positions.get((name, counts[name]))
            if ident:
                attached.add(ident)
                return m[0].replace("<" + m[1], f'<{m[1]} id="fig{number}-{ident}"', 1)
            return m[0]

        result = tag.sub(restore, translated)
        if attached != refs:
            raise ValueError("Diagram reference missing in the source edition")
        result = re.sub(
            r'(url\(#|href="#)([\w-]+)', lambda m: f"{m[1]}fig{number}-{m[2]}", result
        )
        result = re.sub(
            r'aria-labelledby="([^"]+)"',
            lambda m: (
                'aria-labelledby="'
                + " ".join(f"fig{number}-{v}" for v in m[1].split())
                + '"'
            ),
            result,
        )
        body = body.replace(translated, result, 1)
    return body


def chapters(z):
    root = "Snowmoon-" + REV + "/"
    episodes = json.loads(z.read(root + "content/episodes.json"))
    if [ep["id"] for ep in episodes] != list(range(1, 33)):
        raise ValueError("Incomplete or reordered Snowmoon edition")
    for ep in episodes:
        i = ep["id"]
        stem = root + f"content/zh/chapter-{i:02}"
        raw = z.read(stem + ".html")
        meta = json.loads(z.read(stem + ".json"))
        if (
            meta["chapter"] != i
            or meta["omittedBlocks"] != 0
            or meta["sourceParagraphs"] != meta["outputParagraphs"]
            or meta["sourceTranslatableNodes"] != meta["translatedNodes"]
            or hashlib.sha256(raw).hexdigest() != meta["translationFileSha256"]
        ):
            raise ValueError(f"Incomplete or modified Snowmoon chapter {i}")
        body = (
            raw.decode()
            .strip()
            .replace("<center>", '<div style="text-align:center">')
            .replace("</center>", "</div>")
        )
        if "<svg" in body:
            body = repair_diagrams(
                body, z.read(root + f"content/original/chapter-{i:02}.html").decode()
            )

        # Rewrite only XML tag and attribute names, preserving the text and all diagram coordinates.
        def restore_case(match):
            return match[1] + SVG_CASE.get(match[2], match[2])

        body = re.sub(r"(</?)([a-z]+)(?=[\s/>])", restore_case, body)
        body = re.sub(r'(\s)([a-z]+)(?==")', restore_case, body)
        ET.fromstring("<body>" + body + "</body>")
        yield f"第{i}章 {ep['zhTitle']}", body


def page(title, body):
    return (
        f'<html xmlns="{XHTML}" xmlns:epub="{EPUB}" xml:lang="zh-Hans"><head>'
        f"<title>{escape(title)}</title><style>svg{{max-width:100%;height:auto}}table{{border-collapse:collapse}}"
        f"td,th{{padding:.2em;border:1px solid}}</style></head><body><h1>{escape(title)}</h1>{body}</body></html>"
    )


def make_epub(source, out_path):
    uid = "urn:bookorbit:snowmoon:" + RELEASE["editionId"]
    with ZipFile(io.BytesIO(source)) as upstream, ZipFile(out_path, "w") as out:

        def write(name, data, method=ZIP_DEFLATED):
            out.writestr(
                ZipInfo(name, (2026, 11, 1, 0, 0, 0)), data, compress_type=method
            )

        write("mimetype", "application/epub+zip", ZIP_STORED)
        write(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        manifest = [
            '<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>',
            '<item id="credits" href="credits.xhtml" media-type="application/xhtml+xml"/>',
        ]
        items, nav = [], []
        for i, (title, body) in enumerate(chapters(upstream), 1):
            file = f"ch{i:02}.xhtml"
            write(file, page(title, body))
            svg = ' properties="svg"' if "<svg" in body else ""
            manifest.append(
                f'<item id="c{i}" href="{file}"{svg} media-type="application/xhtml+xml"/>'
            )
            items.append(f'<itemref idref="c{i}"/>')
            nav.append(f'<li><a href="{file}">{escape(title)}</a></li>')
        nav.append('<li><a href="credits.xhtml">版本、翻译与许可</a></li>')
        write(
            "nav.xhtml",
            page("目录", '<nav epub:type="toc"><ol>' + "".join(nav) + "</ol></nav>"),
        )
        root = "Snowmoon-" + REV + "/"
        credits = (
            f"<p>原作者 Vitalik Buterin。独立简体中文机器辅助译本，未经作者审定。"
            f'本版将全部 32 章、图表与授权说明重新编排为 EPUB。</p><p><a href="{SOURCE}">译本及翻译工具</a> · '
            f'<a href="{ARCHIVE}">完整对应源码 ZIP</a> · '
            '<a href="https://vitalik.eth.limo/snowmoon/">作者原版</a> · <a href="https://github.com/huaqian0226/ebook-workbench/blob/workbench-v0.3.0/deploy/ebook-workbench/chapter-books/snowmoon.py">本版 EPUB 转换程序</a></p>'
        )
        for f in ("NOTICE.md", "LICENSE"):
            credits += "<pre>" + escape(upstream.read(root + f).decode()) + "</pre>"
        write("credits.xhtml", page("版本、翻译与许可", credits))
        write(
            "book.opf",
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">{uid}</dc:identifier><dc:title>雪月</dc:title><dc:creator>Vitalik Buterin</dc:creator><dc:language>zh-Hans</dc:language><dc:rights>GPL-3.0-only</dc:rights><dc:source>{SOURCE}</dc:source><meta property="dcterms:modified">2026-11-01T00:00:00Z</meta></metadata><manifest>'
            + "".join(manifest)
            + "</manifest><spine>"
            + "".join(items)
            + '<itemref idref="credits"/></spine></package>',
        )


def build(dest: Path):
    with urlopen(
        Request(ARCHIVE, headers={"User-Agent": "BookOrbit Chapter Books"}), timeout=45
    ) as resp:
        source = resp.read(12 * 1024 * 1024 + 1)
    if hashlib.sha256(source).hexdigest() != DIGEST:
        raise ValueError("Upstream archive differs from the reviewed edition")
    with NamedTemporaryFile(dir=dest.parent, prefix=".snowmoon-", delete=False) as tmp:
        name = Path(tmp.name)
    try:
        make_epub(source, name)
        os.replace(name, dest)
    finally:
        name.unlink(missing_ok=True)
