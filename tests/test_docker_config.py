"""Offline Docker key persistence and safety defaults; no device I/O."""
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import edge_dashboard


class DockerTests(unittest.TestCase):
    def test_key_persists_and_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".edge_dashboard_key"
            with patch.object(edge_dashboard, "KEY_FILE", path):
                key = edge_dashboard.access_key()
                self.assertGreaterEqual(len(key), 12)
                self.assertEqual(key, edge_dashboard.access_key())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_key_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            victim = Path(td) / "victim"
            victim.write_text("untouched", encoding="utf-8")
            path = Path(td) / ".edge_dashboard_key"
            path.symlink_to(victim)
            with patch.object(edge_dashboard, "KEY_FILE", path):
                with self.assertRaisesRegex(RuntimeError, "symlink"):
                    edge_dashboard.access_key()
            self.assertEqual(victim.read_text(encoding="utf-8"), "untouched")

    def test_key_rejects_directory(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".edge_dashboard_key"
            path.mkdir()
            with patch.object(edge_dashboard, "KEY_FILE", path):
                with self.assertRaisesRegex(RuntimeError, "regular file"):
                    edge_dashboard.access_key()

    def test_environment_override_new_process(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / ".edge_dashboard_key"
            env = dict(os.environ, PULSEDIRECTOR_KEY_FILE=str(path))
            code = "import edge_dashboard; print(edge_dashboard.KEY_FILE); edge_dashboard.access_key()"
            run = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                 env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout.strip(), str(path))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_safe_compose_and_image_defaults(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("PULSEDIRECTOR_HOST_BIND_IP:-127.0.0.1", compose)
        self.assertIn("PULSEDIRECTOR_PHONE_IP:?", compose)
        self.assertIn("read_only: true", compose)
        self.assertNotIn("network_mode: host", compose)
        df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("USER 10001:10001", df)
        self.assertIn('"--profile", "lan"', df)
        self.assertIn('"--no-print-key"', df)
        ctx = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        self.assertIn("!edge_dashboard.py", ctx)
        self.assertNotIn("!.env", ctx)
