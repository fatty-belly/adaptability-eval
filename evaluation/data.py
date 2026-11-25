"""Validate expanded UReCBench data without modifying task content."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def safe_path(root, name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name:
        raise ValueError(f'Invalid dataset path: {name}')
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Dataset path escapes its root: {name}')
    return path


def validate(root, *, hashes=False):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('name') != 'UReCBench' or manifest.get('version') != '42-v1':
        raise ValueError('Expected the expanded UReCBench 42-v1 release. Download it again; no archive extraction or task patching is needed.')
    families = manifest['families']
    if len(families) != 42 or len({row['id'] for row in families}) != 42:
        raise ValueError('The release must contain exactly 42 distinct families')
    if sum(row['track'] == 'two-turn' for row in families) != 23:
        raise ValueError('Expected 23 two-turn families and 19 multi-round families')
    for row in families:
        direct = 'direct-b' if row['track'] == 'two-turn' else 'direct-final'
        if set(row['variants']) != {'adapt', direct}:
            raise ValueError(f'Unexpected variants for {row["id"]}')
        for variant in row['variants'].values():
            if not (safe_path(root, variant['path']) / 'task.toml').is_file():
                raise ValueError(f'Missing task package: {variant["path"]}')
    inventory = json.loads((root / 'files.json').read_text(encoding='utf-8'))['files']
    paths = set()
    for entry in inventory:
        if entry['path'] in paths:
            raise ValueError('Duplicate inventory path: ' + entry['path'])
        paths.add(entry['path'])
        path = safe_path(root, entry['path'])
        if not path.is_file() or path.stat().st_size != entry['size']:
            raise ValueError('Missing or incomplete dataset file: ' + entry['path'])
        if hashes:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != entry['sha256']:
                raise ValueError('Dataset file changed: ' + entry['path'])
    return manifest


def restore_file_modes(root):
    """HF snapshots carry bytes, not POSIX executable bits; restore declared modes."""
    root = Path(root).resolve()
    entries = json.loads((root / 'files.json').read_text(encoding='utf-8'))['files']
    for entry in entries:
        mode = entry['mode']
        if mode not in (0o644, 0o755):
            raise ValueError('Unsupported file mode in dataset inventory')
        safe_path(root, entry['path']).chmod(mode)
