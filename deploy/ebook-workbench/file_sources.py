"""Install the reviewed file indexers into a running BookOrbit without changing other settings."""

import argparse
import json
from pathlib import Path
from urllib.request import Request
from uuid import uuid4

from metadata_providers import Api

SOURCES = {
    "gutenberg-files": ("Project Gutenberg · EPUB 原件", "http://gutenberg:8080"),
    "chapter-books": ("中文小说 · 完整章节 EPUB", "http://chapter-books:8080"),
}


def upload(api, kind):
    source = (Path(__file__).parent / "sources" / kind / "index.mjs").read_bytes()
    boundary = uuid4().hex
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="index.mjs"\r\n'
        "Content-Type: text/javascript\r\n\r\n"
    ).encode()
    data = prefix + source + f"\r\n--{boundary}--\r\n".encode()
    req = Request(
        api.root + "admin/request-indexers/plugins",
        data=data,
        headers={
            "Authorization": "Bearer " + api.token,
            "Content-Type": "multipart/form-data; boundary=" + boundary,
        },
    )
    with api.opener.open(req, timeout=60) as resp:
        result = json.load(resp)
    if result.get("restartRequired"):
        raise RuntimeError(f"{kind} requires a BookOrbit restart")


def install(api, kind):
    name, url = SOURCES[kind]
    path = "admin/request-indexers"
    rows = api.request(path)["indexers"]
    row = next((row for row in rows if row["adapterType"] == kind), None)
    if row and row["baseUrl"].rstrip("/") != url:
        raise RuntimeError(f"{kind} already has a different configured origin")
    upload(api, kind)
    if not row:
        row = api.request(
            path,
            {
                "adapterType": kind,
                "name": name,
                "baseUrl": url,
                "enabled": False,
                "allowPrivateAddress": True,
            },
        )
    endpoint = path + "/" + str(row["id"])
    test = api.request(endpoint + "/test", {})
    if not test.get("success"):
        raise RuntimeError(
            f"{kind}: {test.get('error', test.get('message', 'source test failed'))}"
        )
    if not row["enabled"]:
        api.request(endpoint, {"enabled": True}, "PUT")
    print(kind, row["id"], "verified and enabled", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument("--only", nargs="+", choices=SOURCES)
    args = parser.parse_args()
    api = Api(args.instance.expanduser())
    for kind in args.only or SOURCES:
        install(api, kind)
