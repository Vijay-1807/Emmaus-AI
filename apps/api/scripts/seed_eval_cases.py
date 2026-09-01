"""Seed evaluation cases into MongoDB.

Usage:
    uv run python scripts/seed_eval_cases.py [path-to-json]

Defaults to ../../evaluation/datasets/vedax_eval_cases.json
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import connect_db, close_db
from app.evaluation.runner import seed_cases


async def main() -> None:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = Path(__file__).resolve().parents[2] / "evaluation" / "datasets" / "vedax_eval_cases.json"
    if not path.exists():
        print(f"eval case file not found: {path}")
        sys.exit(1)
    cases = json.loads(path.read_text(encoding="utf-8"))
    await connect_db()
    inserted = await seed_cases(cases)
    await close_db()
    print(f"seeded {inserted}/{len(cases)} evaluation cases")


if __name__ == "__main__":
    asyncio.run(main())
