"""Provision the library and the bundled public sources on a new local instance."""
import argparse
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

SOURCES = (
    ("standard-ebooks", "Standard Ebooks · 英文经典", "https://standardebooks.org"),
    ("wikimedia-commons-books", "Wikimedia Commons · 中文古籍", "https://commons.wikimedia.org"),
    ("librivox", "LibriVox · 有声书", "https://librivox.org"),
    ("duke-open-comics", "Duke · 开放漫画", "https://cspd.law.duke.edu"),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    base = parser.parse_args().instance.expanduser()
    env = dict(line.split("=", 1) for line in (base / ".env").read_text().splitlines() if "=" in line)
    owner = json.loads((base / "owner.json").read_text())
    opener = build_opener(ProxyHandler({}))
    api = f"http://127.0.0.1:{env.get('APP_PORT', '8820')}/api/v1/"
    token = None

    def call(path, body=None, method=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        if token:
            h["Authorization"] = "Bearer " + token
        req = Request(api + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=h)
        with opener.open(req, timeout=45) as response:
            data = response.read()
            return json.loads(data) if data else None

    if call("auth/setup-status")["needsSetup"]:
        token = call("auth/setup", owner, headers={"x-setup-token": env["SETUP_BOOTSTRAP_TOKEN"]})["accessToken"]
    else:
        token = call("auth/login", {k: owner[k] for k in ("username", "password")})["accessToken"]
    libraries = call("libraries")
    library = next((lib for lib in libraries if any(f["path"] == "/books/Library" for f in lib["folders"])), None)
    if library is None:
        library = call("libraries", {"name": "共享书架", "icon": "book", "folders": ["/books/Library"],
                                      "watch": True, "fileWriteEnabled": False})
    existing = {s["adapterType"] for s in call("admin/request-indexers")["indexers"]}
    supported = {a["type"] for a in call("admin/request-indexers/adapters")["adapters"]}
    for kind, name, url in SOURCES:
        if kind not in supported:
            raise SystemExit(f"Source plugin is missing: {kind}")
        if kind not in existing:
            call("admin/request-indexers", {"adapterType": kind, "name": name, "baseUrl": url, "enabled": True})
    dest = {"libraryId": library["id"], "folderId": library["folders"][0]["id"]}
    call("admin/book-request-automation", {"destinations": {"ebook": dest, "audiobook": dest}}, "PUT")
    dock = call("book-dock/settings")
    dock.pop("bookDockPath", None)
    dock.update(autoFetchMetadata=False, autoFinalizeMetadataMode="embedded_only")
    call("book-dock/settings", dock, "PUT")
    try:
        call(f"scanner/libraries/{library['id']}/scan", {})
    except HTTPError as error:
        if error.code != 409:
            raise
        message = json.loads(error.read()).get("message", "")
        if message != f"A scan is already running for library {library['id']}":
            raise RuntimeError(message) from error
    print("Configured", library["name"], "and", len(SOURCES), "public sources.")


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        raise SystemExit(f"BookOrbit returned HTTP {error.code} for {error.url}") from None
