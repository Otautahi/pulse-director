"""Additional offline checks added by the v4.6 development staging kit."""
import pathlib
import unittest
import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import edge2_pairing_ui

class PortabilityTests(unittest.TestCase):
    def test_pairing_script_is_relative_to_checkout(self):
        self.assertEqual(edge2_pairing_ui.PROBE, ROOT / 'https-standard-probe' / 'https_probe.py')
    def test_stage_script_is_not_bound_to_owner_home(self):
        s=(ROOT/'stage.sh').read_text(encoding='utf-8')
        self.assertNotIn('/home/otautahi/',s)
        self.assertNotIn('README_V46_UNIFIED.md',s)
        self.assertNotIn('"$SRC/V46_SECURITY_AND_TESTING.md"',s)
        self.assertIn('docs',s)
    def test_login_hint_not_bound_to_legacy_path(self):
        dashboard=(ROOT/'edge_dashboard.py').read_text(encoding='utf-8')
        self.assertNotIn('~/edge-ai/.edge_dashboard_key', dashboard)
    def test_v46_docs_present(self):
        self.assertTrue((ROOT/'docs/V46_SECURITY_AND_TESTING.md').is_file())
        self.assertTrue((ROOT/'docs/INSTALL.md').is_file())

if __name__=='__main__': unittest.main()
