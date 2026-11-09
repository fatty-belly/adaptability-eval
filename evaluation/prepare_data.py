"""Add the missing workspace capture declarations to the extracted release."""
from argparse import ArgumentParser
from pathlib import Path
import tomllib

ARTIFACT_FAMILIES = frozenset({
    'new28-003', 'new28-005', 'new28-015', 'new28-020',
    'new28-028', 'new28-029', 'new9-004', 'new9-006',
})


def prepare(root):
    changes = []
    found = set()
    for path in sorted(root.glob('*/two-turn/families/*/adapt/task.toml')):
        ident = path.parent.parent.name
        if ident not in ARTIFACT_FAMILIES:
            continue
        if ident in found:
            raise ValueError(f'Duplicate task family: {ident}')
        found.add(ident)
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError(f'Task configuration is outside the extracted release: {path}')
        original = path.read_bytes()
        config = tomllib.loads(original.decode('utf-8'))
        entries = config.get('artifacts', [])
        if any((entry.get('source') if isinstance(entry,dict) else entry)=='/app' for entry in entries):
            continue
        if 'artifacts' in config:
            raise ValueError(f'Unexpected custom artifact declaration: {path}')
        updated = b'artifacts = ["/app"]\n' + original
        assert tomllib.loads(updated.decode('utf-8')) == {**config,'artifacts':['/app']}
        changes.append((path,updated))
    if found != ARTIFACT_FAMILIES:
        raise ValueError(f'Extract the complete archive first. Missing families: {sorted(ARTIFACT_FAMILIES-found)}')
    for path,updated in changes:
        temp = path.with_name('task.toml.prepare-data.tmp')
        with temp.open('xb') as stream:
            stream.write(updated)
        temp.chmod(path.stat().st_mode & 0o777)
        temp.replace(path)
    return len(changes)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('data',type=Path)
    args = parser.parse_args()
    print(f'Prepared {len(ARTIFACT_FAMILIES)} task configurations ({prepare(args.data.resolve())} updated).')


if __name__=='__main__':
    main()
