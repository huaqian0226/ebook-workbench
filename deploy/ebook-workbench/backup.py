"""Back up a BookOrbit instance or restore it to a separate empty directory."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import ProxyHandler, Request, build_opener


def compose(base, *args, **kwargs):
    # Always use this instance, even if the operator's shell points Compose at another project.
    base = base.resolve()
    env_file = base / ".env"
    settings = dict(line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line)
    project = settings["COMPOSE_PROJECT_NAME"]
    if not re.fullmatch(r"[a-z][a-z0-9-]+", project):
        raise SystemExit("Invalid instance project name")
    env = {key: value for key, value in os.environ.items() if key not in settings and not key.startswith("COMPOSE_")}
    cmd = ["docker", "compose", "-p", project, "--project-directory", str(base), "--env-file", str(env_file),
           "-f", str(base / "compose.yaml")]
    override = base / "compose.override.yaml"
    if override.is_file():
        cmd.extend(["-f", str(override)])
    return subprocess.run([*cmd, *args], cwd=base, env=env, check=True, **kwargs)


def dump_records(base, output):
    env = dict(line.split("=", 1) for line in (base / ".env").read_text().splitlines() if "=" in line)
    api = f"http://127.0.0.1:{env.get('APP_PORT', '8820')}/api/v1/"
    opener = build_opener(ProxyHandler({}))
    token = None

    def request(path, body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(api + path, headers=headers, data=None if body is None else json.dumps(body).encode())
        with opener.open(req, timeout=40) as response:
            body = response.read()
            return json.loads(body) if body else None

    owner = json.loads((base / "owner.json").read_text())
    token = request("auth/login", {k: owner[k] for k in ("username", "password")})["accessToken"]
    books = []
    page = 0
    while True:
        shelf = request("books/query", {"pagination": {"page": page, "size": 100}})
        for item in shelf["items"]:
            bid = item["id"]
            book = request(f"books/{bid}")
            entry = {"record": book, "progress": request(f"reading-progress?bookId={bid}"),
                     "bookmarks": request(f"books/{bid}/bookmarks")}
            if any(f.get("durationSeconds") for f in book["files"]):
                entry["audioProgress"] = request(f"books/{bid}/audio-progress")
            books.append(entry)
        if len(books) >= shelf["total"] or not shelf["items"]:
            break
        page += 1
    data = {"exportedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "libraries": request("libraries"), "books": books}
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def backup(base):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = base / "backups"
    out.mkdir(exist_ok=True)
    archive = out / f"bookorbit-{stamp}.tar.gz"
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        tmp = Path(tmp)
        dump_records(base, tmp / "library-records.json")
        compose(base, "stop", "app")
        try:
            with (tmp / "database.dump").open("wb") as f:
                compose(base, "exec", "-T", "postgres", "pg_dump", "-U", "bookorbit", "-Fc", "bookorbit", stdout=f)
            with tarfile.open(tmp / "backup.tmp", "w:gz", compresslevel=1) as tar:
                for name in ("compose.yaml", "compose.override.yaml", "catalog-providers", ".env", "owner.json", "channels.json", "books", "data/app"):
                    path = base / name
                    if path.exists():
                        tar.add(path, arcname=name)
                for name in ("database.dump", "library-records.json"):
                    tar.add(tmp / name, arcname=name)
        finally:
            compose(base, "up", "-d", "--wait", "app")
        os.rename(tmp / "backup.tmp", archive)
    print(archive)


def restore(archive, dest, project, port):
    if not re.fullmatch("[a-z][a-z0-9-]+", project) or not 1 <= port <= 65535:
        raise SystemExit("Invalid compose project name or port")
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit("Restore destination must be empty")
    collisions = subprocess.check_output(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"])
    if collisions.strip():
        raise SystemExit("Choose an unused compose project")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not (member.isfile() or member.isdir()):
                raise SystemExit("Unsupported archive entry")
        tar.extractall(dest, filter="data")
    env = dict(line.split("=", 1) for line in (dest / ".env").read_text().splitlines() if "=" in line)
    env.update(APP_PORT=str(port), COMPOSE_PROJECT_NAME=project, PUID=str(os.getuid()), PGID=str(os.getgid()))
    (dest / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    for key in (".env", "owner.json", "database.dump", "library-records.json"):
        (dest / key).chmod(0o600)
    compose(dest, "up", "-d", "--wait", "postgres")
    with (dest / "database.dump").open("rb") as sql:
        compose(dest, "exec", "-T", "postgres", "pg_restore", "-U", "bookorbit", "-d", "bookorbit",
                "--exit-on-error", "--single-transaction", stdin=sql)
    compose(dest, "up", "-d", "--wait", "app")
    print(f"Restored {project} at http://127.0.0.1:{port}/", flush=True)
    if (dest / "catalog-providers" / "Dockerfile").is_file():
        try:
            compose(dest, "build", "oxford-solo")
            compose(dest, "up", "-d", "--wait", "--wait-timeout", "240")
        except subprocess.CalledProcessError:
            print("The library is running. Catalogue services need attention. "
                  "From the restored directory run docker compose build oxford-solo, "
                  "then docker compose up -d --wait.", file=sys.stderr)



if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="cmd", required=True)
    for command in ("export", "backup", "restore"):
        cmd = commands.add_parser(command)
        if command == "restore":
            cmd.add_argument("archive", type=Path)
            cmd.add_argument("destination", type=Path)
            cmd.add_argument("--project", required=True)
            cmd.add_argument("--port", required=True, type=int)
        else:
            cmd.add_argument("instance", type=Path)
            if command == "export":
                cmd.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.cmd == "restore":
        restore(args.archive, args.destination, args.project, args.port)
    elif args.cmd == "export":
        dump_records(args.instance, args.output)
    else:
        backup(args.instance)
