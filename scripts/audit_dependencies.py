from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'__future__'}
stdlib = set()
try:
    import sys
    stdlib = set(sys.stdlib_module_names)
except AttributeError:
    stdlib = set()
imports = set()
for base in ('core', 'modules', 'api', 'scripts', 'consciousness'):
    folder = ROOT / base
    if not folder.exists():
        continue
    for path in folder.rglob('*.py'):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split('.')[0])
external = sorted(name for name in imports if name not in stdlib and name not in SKIP and name not in {'core','modules','api','scripts','consciousness'})
missing = sorted(name for name in external if importlib.util.find_spec(name) is None)
print(json.dumps({'external_imports': external, 'missing_imports': missing}, ensure_ascii=False, indent=2))
