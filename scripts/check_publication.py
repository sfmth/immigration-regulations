#!/usr/bin/env python3
"""Check the tracked publication boundary without printing credential values."""

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'Google API key': re.compile(rb'\bAIza[0-9A-Za-z_-]{35}\b'),
    'GitHub token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'),
    'AWS access key': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'private key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
}


def main() -> None:
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    problems = []
    for name in filter(None, paths):
        if name.startswith('data/'):
            problems.append(f'{name}: raw research corpus must remain local')
            continue
        path = ROOT / name
        # Large binary data has a separate allowlisted database/pack validation.
        if not path.is_file() or path.suffix in {'.sqlite', '.pack', '.wasm', '.zip'}:
            continue
        content = path.read_bytes()
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                problems.append(f'{name}: {label} pattern detected (value withheld)')
    if problems:
        raise SystemExit('\n'.join(problems))
    print('Publication boundary and credential-pattern checks passed.')


if __name__ == '__main__':
    main()
