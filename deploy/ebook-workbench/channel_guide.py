"""Build the in-library channel guide from an editable JSON source list."""
from argparse import ArgumentParser
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
import json
import os
import tempfile

TITLE = "找书与借阅 · 来源目录"
IDENTIFIER = "urn:ebook-workbench:source-directory"
MIME = "application/epub+zip"


def build(channels, output):
    paragraphs = []
    for row in channels:
        if row.get("archived"):
            continue
        parsed = urlsplit(row["url"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError(f"Invalid source URL for {row['name']}")
        paragraphs.append('<p><a href="{}">{}</a><br/>{}</p>'.format(
            escape(row["url"], quote=True), escape(row["name"]), escape(row.get("note", ""))))
    title = escape(TITLE)
    content = f'''<html xmlns="http://www.w3.org/1999/xhtml" lang="zh">
<head><title>{title}</title></head><body><h1>{title}</h1>
<p>在 BookOrbit 的「请求」里输入书名，选择版本、文件和目标书架。馆藏借阅和需要本人登录的网站从下面进入。</p>
<p>Oxford SOLO 可按书名或电子 ISBN 查找，例如 9781108380980。选定版本，打开 View Online，按馆方提示用自己的账户登录。借阅期限、续借和归还以供应商账户为准。</p>
{''.join(paragraphs)}</body></html>'''
    container = '''<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
    opf = f'''<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">{IDENTIFIER}</dc:identifier>
<dc:title>{title}</dc:title><dc:language>zh</dc:language><dc:creator>电子书工作台</dc:creator>
<meta property="dcterms:modified">2026-11-25T00:00:00Z</meta></metadata>
<manifest><item id="guide" href="guide.xhtml" media-type="application/xhtml+xml"/>
<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/></manifest>
<spine><itemref idref="guide"/></spine></package>'''
    nav = f'''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>目录</title></head><body><nav epub:type="toc"><ol><li><a href="guide.xhtml">{title}</a></li></ol></nav></body></html>'''
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tmp", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        with ZipFile(tmp_path, "w", ZIP_DEFLATED) as archive:
            archive.writestr("mimetype", MIME, ZIP_STORED)
            for name, body in [("META-INF/container.xml", container), ("book.opf", opf),
                               ("guide.xhtml", content), ("nav.xhtml", nav)]:
                archive.writestr(name, '<?xml version="1.0" encoding="utf-8"?>' + body)
        os.replace(tmp_path, output)
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("channels", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(json.loads(args.channels.read_text()), args.output)
