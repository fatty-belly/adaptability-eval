"""Compatibility command: validate expanded data; no task patches are applied."""
from argparse import ArgumentParser
from pathlib import Path
from evaluation.data import validate


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    args = parser.parse_args()
    manifest = validate(args.data, hashes=True)
    print(f'Validated {len(manifest["families"])} families. No task content changed.')


if __name__ == '__main__':
    main()
