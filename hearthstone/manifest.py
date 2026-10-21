"""Verify frozen catalog/schema bytes without contacting external services."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verify(manifest):
    errors = []
    for file in manifest['files']:
        path = (ROOT / file['path']).resolve()
        if not path.is_relative_to(ROOT):
            errors.append(f'path escapes project: {file["path"]}')
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            errors.append(str(error))
            continue
        if digest != file['sha256']:
            errors.append(f'hash mismatch: {file["path"]}')
    return errors


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Verify a frozen catalog manifest')
    parser.add_argument('path', nargs='?', default=str(ROOT / 'cards/manifest-v9.json'))
    args = parser.parse_args()
    manifest = json.loads(Path(args.path).read_text())
    errors = verify(manifest)
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f"Verified {len(manifest['files'])} frozen files for {manifest['catalogId']}")
