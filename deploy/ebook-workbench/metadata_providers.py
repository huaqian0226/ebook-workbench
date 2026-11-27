"""Register this deployment's catalogues through BookOrbit's settings API."""

import argparse
import json
import shutil
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

# A live, public title for each source. Registration never applies fields to existing books.
SAMPLES = {
    "douban": "三体",
    "oxford-solo": "9781108380980",
    "apple-books-gb": "Pride and Prejudice",
    "standard-ebooks": "Persuasion",
    "free-programming-books": "Pro Git",
    "pepper-carrot-zh": "客栈",
    "librivox": "Pride and Prejudice",
    "wikisource-zh": "红楼梦",
    "open-textbook-library": "College Algebra",
    "openstax": "Astronomy",
    "doab": "Exploring Digital Legal Landscapes",
    "gutenberg": "Pride and Prejudice",
}


class Api:
    def __init__(self, base):
        env = dict(
            l.split("=", 1)
            for l in (base / ".env").read_text().splitlines()
            if "=" in l
        )
        self.root = f"http://127.0.0.1:{env.get('APP_PORT', '8820')}/api/v1/"
        self.opener = build_opener(ProxyHandler({}))
        self.token = None
        owner = json.loads((base / "owner.json").read_text())
        self.token = self.request(
            "auth/login", {k: owner[k] for k in ("username", "password")}
        )["accessToken"]

    def request(self, path, body=None, method=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = Request(
            self.root + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        try:
            with self.opener.open(req, timeout=95) as resp:
                data = resp.read()
                return json.loads(data) if data else None
        except HTTPError as e:
            info = e.read(800).decode(errors="replace")
            raise RuntimeError(f"{req.get_method()} {path}: {e.code} {info}") from None


def copy_bundle(base):
    bundle = Path(__file__).resolve().parent

    for name in ("chapter-books", "chapter-runtime"):
        target = base / name
        target.mkdir(exist_ok=True)
        for source in (bundle / name).iterdir():
            if source.name == "Dockerfile" or (source.suffix in (".py", ".cjs", ".json") and not source.name.startswith("test")):
                shutil.copy2(source, target / source.name)
    client = bundle.parents[1] / "client/dist"
    if not (client / "index.html").is_file():
        raise SystemExit("Build the fork client first: pnpm --filter client run build-only")
    public = base / "chapter-runtime/public"
    shutil.copytree(client, public, dirs_exist_ok=True)
    core = bundle.parents[1] / "server/src/modules/book-request/fulfillment"
    for name in ("direct-download.service.ts", "chapter-file.ts"):
        shutil.copy2(core / name, base / "chapter-runtime" / name)
    shutil.copy2(bundle / "compose.override.yaml", base / "compose.override.yaml")
    dest = base / "catalog-providers"
    dest.mkdir(exist_ok=True)
    for p in (bundle / "catalog-providers").iterdir():
        if p.name == "Dockerfile" or (
            p.suffix == ".py" and not p.name.startswith("test_")
        ):
            shutil.copy2(p, dest / p.name)


def register(api, key):
    endpoint = "metadata-http-providers"
    address = f"http://{key}:8080"
    row = next((p for p in api.request(endpoint) if p["key"] == key), None)
    if row and row["baseUrl"].rstrip("/") != address:
        raise RuntimeError(f"{key} already uses another address: {row['baseUrl']}")
    if not row:
        row = api.request(
            endpoint,
            {"baseUrl": address, "allowPrivateAddress": True, "timeoutMs": 30000},
        )
    path = endpoint + "/" + str(row["id"])
    verdict = api.request(path + "/test", {"query": SAMPLES[key]})
    if not verdict["ok"] or not verdict["resultCount"]:
        raise RuntimeError(
            f"{key} has no verified sample: {verdict.get('error') or '0 results'}"
        )
    if not row["enabled"]:
        row = api.request(path, {"enabled": True}, "PATCH")
    print(key, row["id"], verdict["resultCount"], verdict["sampleTitle"], flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("instance", type=Path)
    p.add_argument(
        "--copy",
        action="store_true",
        help="place the deployment files into an existing instance",
    )
    p.add_argument("--only", nargs="+", choices=SAMPLES)
    args = p.parse_args()
    base = args.instance.expanduser()
    if args.copy:
        copy_bundle(base)
        return
    api = Api(base)
    failures = []
    for key in args.only or SAMPLES:
        try:
            register(api, key)
        except (OSError, RuntimeError) as e:
            failures.append(key)
            print(f"{key}: {e}", file=sys.stderr, flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
