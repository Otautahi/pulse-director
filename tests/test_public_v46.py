"""Public distribution defaults; offline/source-only checks (no device I/O)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class PublicV46Tests(unittest.TestCase):
    def test_public_default_profile_is_lan(self):
        src = (ROOT / 'edge_dashboard.py').read_text()
        self.assertIn('p.add_argument("--profile", choices=("lan", "hybrid"), default="lan",', src)
        self.assertNotIn('p.add_argument("--profile", choices=("lan", "hybrid"), default="hybrid",', src)
    def test_current_public_docs_are_v46(self):
        for path in ('README.md', 'docs/INSTALL.md', 'docs/SECURITY.md', 'docs/HYBRID.md'):
            self.assertIn('v4.6', (ROOT / path).read_text(), path)
    def test_obsolete_autopublishing_workflow_is_not_in_current_tree(self):
        self.assertFalse((ROOT / '.github/workflows/publish-experimental-prerelease.yml').exists())

if __name__ == '__main__':
    unittest.main()
