"""Check a committed feature branch, then publish it: python3 tools/publish.py."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def git_output(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main():
    try:
        branch = git_output('symbolic-ref', '--quiet', '--short', 'HEAD')
        if branch in ('main', 'master'):
            raise ValueError(
                'Publish a feature branch; update main through a pull request.'
            )
        if git_output('status', '--porcelain'):
            raise ValueError(
                'Commit the intended changes before publishing; the working tree must be clean.'
            )
        git_output('remote', 'get-url', 'origin')
        commands = [
            [sys.executable, '-m', 'hearthstone.catalog'],
            [sys.executable, '-m', 'hearthstone.manifest'],
            [
                sys.executable,
                '-m',
                'black',
                '--check',
                'hearthstone',
                'tests',
                'tools',
                'examples',
            ],
            [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
            ['git', 'push', '--set-upstream', 'origin', branch],
        ]
        for command in commands:
            print('Running: ' + ' '.join(command), flush=True)
            subprocess.run(command, cwd=ROOT, check=True)
    except (ValueError, subprocess.CalledProcessError) as error:
        print(f'Publication stopped: {error}', file=sys.stderr)
        return 1
    print(f'Published {branch}. Check GitHub CI and open/update its pull request.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
