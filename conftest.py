"""Repo-root pytest bootstrap.

Puts ``src/`` on ``sys.path`` so ``import asv`` resolves to the working tree even
without an editable install, and the repo root so ``import apps.api`` resolves.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _p in (_ROOT / "src", _ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)
