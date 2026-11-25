import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from evaluation.data import safe_path, validate, restore_file_modes


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rows = []
        self.files = []
        for i in range(42):
            track = 'two-turn' if i < 23 else 'multiround'
            variants = {}
            for variant in ('adapt', 'direct-b' if i < 23 else 'direct-final'):
                path = f'source/{track}/families/f{i}/{variant}'
                task = self.root / path / 'task.toml'
                task.parent.mkdir(parents=True)
                task.write_bytes(b'schema_version = "1.4"\n')
                variants[variant] = {'path': path}
                self.files.append({'path': path+'/task.toml', 'size': task.stat().st_size,
                                   'sha256': hashlib.sha256(task.read_bytes()).hexdigest(), 'mode': 0o644})
            self.rows.append({'id':f'f{i}', 'track':track, 'variants':variants})
        self.save()

    def save(self):
        (self.root/'manifest.json').write_text(json.dumps({'name':'UReCBench','version':'42-v1','families':self.rows}))
        (self.root/'files.json').write_text(json.dumps({'files':self.files}))

    def test_complete_release_and_modes(self):
        self.assertEqual(len(validate(self.root, hashes=True)['families']),42)
        restore_file_modes(self.root)

    def test_same_size_changed_content_rejected(self):
        p = self.root/self.files[0]['path']
        p.write_bytes(p.read_bytes().replace(b'1.4',b'9.9'))
        with self.assertRaisesRegex(ValueError,'changed'): validate(self.root, hashes=True)

    def test_missing_file_rejected(self):
        (self.root/self.files[-1]['path']).unlink()
        with self.assertRaisesRegex(ValueError,'Missing'): validate(self.root)

    def test_duplicate_family_rejected(self):
        self.rows[-1]['id']=self.rows[0]['id'];self.save()
        with self.assertRaisesRegex(ValueError,'distinct'): validate(self.root)

    def test_paths_cannot_escape_release(self):
        for path in ('../secret','/tmp/file','a/../../b','a\\b'):
            with self.subTest(path=path),self.assertRaises(ValueError): safe_path(self.root,path)

    def test_setuid_mode_rejected(self):
        self.files[0]['mode']=0o4755;self.save()
        with self.assertRaisesRegex(ValueError,'file mode'): restore_file_modes(self.root)

    def test_obsolete_archive_layout_rejected(self):
        (self.root/'manifest.json').write_text(json.dumps({'name':'old-release'}))
        with self.assertRaisesRegex(ValueError,'expanded'): validate(self.root)


if __name__=='__main__': unittest.main()
