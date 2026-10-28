import pathlib
import subprocess
import sys
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]

class TestRelease(unittest.TestCase):
    def test_public_package_contract(self):
        subprocess.run([sys.executable, str(ROOT/'scripts'/'validate_public_package.py')], check=True)

    def test_build_preserves_source_bytes(self):
        subprocess.run([sys.executable, str(ROOT/'scripts'/'build_workbuddy_zip.py')], check=True)
        p = ROOT/'dist'/'ehelp-contacts-workbuddy-v0.2.6.zip'
        with zipfile.ZipFile(p) as z:
            assert z.testzip() is None
            for file in (ROOT/'skill'/'ehelp-mail').rglob('*'):
                if file.is_file():
                    name='ehelp-mail/'+file.relative_to(ROOT/'skill'/'ehelp-mail').as_posix()
                    self.assertEqual(z.read(name),file.read_bytes(),name)

if __name__ == '__main__':
    unittest.main()
