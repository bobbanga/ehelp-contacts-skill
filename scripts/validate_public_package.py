"""Offline static checks. Does not inspect or connect to real mail clients."""
from pathlib import Path
import ast
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skill' / 'ehelp-mail'
frontmatter = (SKILL / 'SKILL.md').read_text(encoding='utf-8')
assert frontmatter.startswith('---\n'), 'Missing YAML frontmatter'
parts = frontmatter.split('---', 2)
assert len(parts) >= 3, 'Broken frontmatter'
meta = parts[1]


def items_for(name):
    match = re.search(rf'(?m)^{re.escape(name)}:\s*\n((?:  - .+\n)+)', meta)
    assert match, f'Missing list {name}'
    return [s.strip() for s in match.group(1).splitlines() if s.strip()]

zh = items_for('examples_zh')
en = items_for('examples_en')
assert len(zh) == len(en) == 3, f'Examples invalid: Chinese={len(zh)}, English={len(en)}'
assert re.search(r'(?m)^version:\s*0\.2\.7\s*$', meta)

release = json.loads((SKILL / 'scripts' / 'release.json').read_text(encoding='utf-8'))
assert release['version'] == '0.2.7'

pyfiles = list((SKILL / 'scripts').glob('*.py'))
assert len(pyfiles) >= 15
for path in pyfiles:
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))

manifest_path = SKILL / 'scripts' / 'MANIFEST.sha256.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
# Original market package has its own validation contract; keep it unchanged.
assert manifest

for path in SKILL.rglob('*'):
    if not path.is_file():
        continue
    name = path.name.lower()
    assert name not in {'.env', 'contacts.sqlite3', 'token.json', 'config.yaml'}
    assert path.suffix.lower() not in {'.db', '.sqlite3', '.xlsx', '.xls', '.eml', '.pst', '.ost', '.pem', '.key', '.pfx'}

print(f'OK: {len(pyfiles)} Python files parsed; 3+3 examples; version 0.2.7; no obvious data artifacts')
