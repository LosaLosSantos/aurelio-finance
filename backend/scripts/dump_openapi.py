"""Write the API's own description to a file: python -m scripts.dump_openapi OUT

FastAPI serves this at /openapi.json, but the frontend's type generation must
not need a running server — a build that only works when :8000 happens to be up
is a build that fails on a clean checkout. `app.openapi()` is the same document,
produced from the same routers and Pydantic models, without binding a port.

The lifespan never runs here, so no table is created and no migration applied.
DATABASE_URL is pinned to an in-memory database anyway: importing app.main
constructs an Engine, and this script must not be able to reach backend/data.db
even by accident.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

# backend/ — this file is backend/scripts/dump_openapi.py — so `app` imports
# whether the caller ran us from backend/ or from frontend/.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.main import app  # noqa: E402  (must follow the DATABASE_URL pin)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    out = pathlib.Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys so an unchanged API produces a byte-identical file, and the
    # generator downstream can skip rewriting schema.d.ts.
    out.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
