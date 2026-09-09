"""Command-line entrypoint for a single RivalMap run."""

from __future__ import annotations

import json
import sys

from dotenv import load_dotenv

from .contracts import RivalMapRequest
from .runtime import RivalMapRuntime


def main() -> int:
    load_dotenv()
    idea = " ".join(sys.argv[1:]).strip()
    if not idea:
        print("Usage: python -m rivalmap '<product idea>'", file=sys.stderr)
        return 2
    result = RivalMapRuntime().run(RivalMapRequest(idea=idea))
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
