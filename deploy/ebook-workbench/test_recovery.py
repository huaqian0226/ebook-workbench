import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backup import compose, restore


class RestoreTests(unittest.TestCase):
    def test_compose_uses_the_target_even_with_another_project_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / ".env").write_text("COMPOSE_PROJECT_NAME=one-test\nAPP_PORT=8101\n")
            with patch.dict(
                os.environ,
                {
                    "COMPOSE_PROJECT_NAME": "another",
                    "COMPOSE_FILE": "override.yml",
                    "APP_PORT": "8100",
                },
            ):
                with patch("backup.subprocess.run") as run:
                    compose(base, "config")
            argv = run.call_args.args[0]
            self.assertEqual(argv[argv.index("-p") + 1], "one-test")
            self.assertNotIn("APP_PORT", run.call_args.kwargs["env"])
            self.assertNotIn("COMPOSE_FILE", run.call_args.kwargs["env"])

    def test_legacy_compose_project_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / ".env").write_text("APP_PORT=8820\n")
            (base / "compose.yaml").write_text("name: original-shelf\nservices: {}\n")
            with patch("backup.subprocess.run") as run:
                compose(base, "config")
            argv = run.call_args.args[0]
            self.assertEqual(argv[argv.index("-p") + 1], "original-shelf")

    def test_a_failed_catalog_build_still_leaves_the_library_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "test.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for name in [
                    ".env",
                    "owner.json",
                    "database.dump",
                    "library-records.json",
                    "catalog-providers/Dockerfile",
                ]:
                    content = (
                        b"COMPOSE_PROJECT_NAME=source\nAPP_PORT=8820\n"
                        if name == ".env"
                        else b"test"
                    )
                    entry = tarfile.TarInfo(name)
                    entry.size = len(content)
                    tar.addfile(entry, io.BytesIO(content))
            calls = []

            def command(_dest, *args, **_kwargs):
                calls.append(args)
                if args[0] == "build":
                    raise subprocess.CalledProcessError(1, ["docker", "compose", *args])

            with (
                patch("backup.subprocess.check_output", return_value=b""),
                patch("backup.compose", side_effect=command),
            ):
                restore(archive, root / "restored", "restore-test", 8101)
            self.assertLess(
                calls.index(("up", "-d", "--wait", "app")),
                calls.index(("build", "oxford-solo")),
            )
