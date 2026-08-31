"""Convenience launcher: build the frontend (if needed) then start the
FastAPI backend, which serves the built bundle — one command, one port.

Usage:
    python scripts/run_webapp.py [--no-build] [--port 8000] [--reload]

For active frontend development, run the backend here and
``npm run dev`` in web/ separately instead (Vite proxies /api to :8000).
"""

import argparse
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = _PROJECT_ROOT / "web"
_DIST_DIR = _WEB_DIR / "dist"


def _build_frontend() -> None:
    if not _WEB_DIR.exists():
        print("[ASV] web/ not found — skipping frontend build (backend will run API-only)")
        return
    print("[ASV] Building frontend (npm install && npm run build)...")
    subprocess.run(["npm", "install"], cwd=str(_WEB_DIR), check=True, shell=(sys.platform == "win32"))
    subprocess.run(["npm", "run", "build"], cwd=str(_WEB_DIR), check=True, shell=(sys.platform == "win32"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-build", action="store_true", help="Skip building web/ even if dist/ is missing")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if not args.no_build and not _DIST_DIR.exists():
        _build_frontend()

    sys.path.insert(0, str(_PROJECT_ROOT))
    import uvicorn

    print(f"[ASV] Starting backend on http://127.0.0.1:{args.port}")
    uvicorn.run("api.main:app", host="127.0.0.1", port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
