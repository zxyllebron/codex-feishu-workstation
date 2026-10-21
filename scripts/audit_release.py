#!/usr/bin/env python3
"""Small release-specific privacy/packaging check; not a general secret scanner."""
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
if (ROOT/'.git').exists():
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    files=[ROOT/n for n in names if n]
else:
    files=[p for p in ROOT.rglob('*') if p.is_file() and not any(x in p.parts for x in ('__pycache__','.git','.venv'))]
issues=[]
patterns=[r'/home/(?!example(?:/|\b))[A-Za-z0-9_-]+/',r'(?:oc_|ou_)[a-f0-9]{30,}',
          r'(?:gh[pousr]_|glpat-|sk-)[A-Za-z0-9_-]{24,}',r'https?://[^\s/]*anyverse[^\s/]*',
          r'-----BEGIN [A-Z ]*PRIVATE KEY-----\n[A-Za-z0-9+/=\n]{40,}']
for p in files:
    rel=p.relative_to(ROOT)
    if rel.parts[0] in ('data','dist') or p.name in ('config.json','auth.json','runtime.local.json','LOCAL-DEPLOYMENT.md','sync_personal.py') or p.suffix in ('.sqlite','.db','.log'):
        issues.append(str(rel)+': private/runtime file included');continue
    if p.suffix in ('.png','.jpg','.zip'):continue
    try:text=p.read_text(encoding='utf-8')
    except (UnicodeError,OSError):continue
    for pattern in patterns:
        if re.search(pattern,text):issues.append(str(rel)+': possible private identifier/credential')
    if p.suffix=='.md':
        for target in re.findall(r'\]\(([^\s)]+)\)',text):
            if '://' in target or target.startswith(('#','mailto:')):continue
            local=target.split('#')[0]
            if local and not (p.parent/local).exists():issues.append(str(rel)+': broken link '+local)
if issues:
    print('\n'.join(issues));sys.exit(1)
print(f'Release audit passed: {len(files)} files; no runtime data, known private IDs or broken local Markdown links.')
