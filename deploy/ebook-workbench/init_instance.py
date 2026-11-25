"""Prepare a private, relocatable BookOrbit instance directory."""
import argparse
import json
import os
import re
from pathlib import Path
import secrets
import shutil

from channel_guide import TITLE, build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instance", type=Path)
    parser.add_argument("--port", type=int, default=8820)
    parser.add_argument("--project", default="ebook-workbench")
    args = parser.parse_args()
    if not re.fullmatch("[a-z][a-z0-9-]+", args.project):
        parser.error("use a lowercase Compose project name")
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    os.umask(0o077)
    base = args.instance.expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    if (base / ".env").exists() or (base / "owner.json").exists():
        parser.error("instance already initialised; use the existing credentials")
    for dirname in ("data/app", "data/postgres", "books/Library", "backups"):
        (base / dirname).mkdir(parents=True, exist_ok=True)
    env = {"COMPOSE_PROJECT_NAME": args.project, "APP_PORT": args.port, "PUID": os.getuid(), "PGID": os.getgid()}
    for key in ("POSTGRES_PASSWORD", "JWT_SECRET", "SETUP_BOOTSTRAP_TOKEN", "BOOK_REQUEST_ENCRYPTION_KEY"):
        env[key] = secrets.token_hex(32)
    with (base / ".env").open("x") as out:
        out.writelines(f"{k}={v}\n" for k, v in env.items())
    owner = {"username": "reader", "name": "Reader", "email": "reader@localhost.invalid",
             "password": "Aa9-" + secrets.token_urlsafe(32)}
    with (base / "owner.json").open("x") as out:
        json.dump(owner, out, indent=2)
        out.write("\n")
    bundle = Path(__file__).resolve().parent
    shutil.copyfile(bundle / "compose.yaml", base / "compose.yaml")
    shutil.copyfile(bundle / "channels.json", base / "channels.json")
    for plugin in sorted((bundle / "sources").glob("*/index.mjs")):
        dest = base / "data/app/plugins/indexers" / plugin.parent.name
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(plugin, dest / "index.mjs")
    build(json.loads((base / "channels.json").read_text()), base / "books/Library" / TITLE / (TITLE + ".epub"))


if __name__ == "__main__":
    main()
