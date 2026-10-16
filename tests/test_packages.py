import importlib.util
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('companion_build', ROOT / 'scripts/build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PackageTests(unittest.TestCase):
    def test_packages_are_reproducible_and_exclude_user_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            for folder in (ROOT / 'addons').iterdir():
                if not folder.is_dir():
                    continue
                a = builder.build(folder.name, Path(tmp) / 'a')
                b = builder.build(folder.name, Path(tmp) / 'b')
                self.assertEqual(a.read_bytes(), b.read_bytes())
                with ZipFile(a) as z:
                    self.assertIn(folder.name + '/LICENSE', z.namelist())
                    self.assertFalse(any('/addon_data/' in n or '/userdata/' in n or n.endswith(
                        ('.jks', '.pass', '.db', '.log')) for n in z.namelist()))

    def test_voice_app_id_and_signer_storage_are_separate_from_existing_installation(self):
        text = (ROOT / 'android/voice-search/AndroidManifest.xml').read_text()
        self.assertIn('package="io.github.glasgowm148.kodivoice"', text)
        self.assertIn('android:allowBackup="false"', text)
        self.assertIn('android:permission="android.permission.DUMP"', text)
        self.assertNotIn('com.household', text)
        source = (ROOT / 'android/voice-search/build.py').read_text()
        self.assertIn('.local/share/bingie-companion/signing', source)


if __name__ == '__main__':
    unittest.main()
