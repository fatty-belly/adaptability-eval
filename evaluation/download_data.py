"""Download expanded Harbor packages and verify their published checksums."""
from argparse import ArgumentParser
from pathlib import Path
import json
from huggingface_hub import snapshot_download
from evaluation.data import restore_file_modes, validate

REPOSITORY = 'fatty-belly/adaptability-harbor'
REVISION = 'urecbench-42-v1'


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--local-dir', type=Path, required=True)
    parser.add_argument('--revision', default=REVISION, help='HF commit or tag; defaults to the frozen 42-task release')
    args = parser.parse_args()
    root = args.local_dir.resolve()
    if (root / 'manifest.json').exists():
        existing = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        if existing.get('name') != 'UReCBench' or existing.get('version') != '42-v1':
            raise ValueError('Choose a new directory instead of overlaying an older dataset')
    snapshot_download(repo_id=REPOSITORY, repo_type='dataset', revision=args.revision,
                      local_dir=root,
                      allow_patterns=['manifest.json', 'files.json', 'README.md',
                                      'evo-code/**', 'nl2repo/**', 'swe-chat/**', 'swejourney/**',
                                      'catalog/**', 'provenance.json'])
    manifest = validate(root, hashes=True)
    restore_file_modes(root)
    print(json.dumps({'dataset': str(root), 'families': len(manifest['families']),
                      'version': manifest['version'], 'checksums': 'verified'}))


if __name__ == '__main__':
    main()
