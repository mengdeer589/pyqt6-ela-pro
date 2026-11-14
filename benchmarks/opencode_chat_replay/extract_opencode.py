"""Export an opencode session to an ElaChatView bundle (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapter import load_bundle, validate_bundle  # noqa: E402

DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
DEFAULT_SESSION = "ses_e734295a1ffeFEIRdCrlNDpg9f"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--mode", choices=("stress", "typical"), default="stress")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-children", action="store_true")
    parser.add_argument("--max-tool-output", type=int)
    parser.add_argument("--max-text", type=int)
    parser.add_argument("--skip-validate", action="store_true")
    args = parser.parse_args()

    out = args.out
    if out is None:
        out = BASE / "data" / f"{args.session}.{args.mode}.json"
    out.parent.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    bundle = load_bundle(
        args.db,
        args.session,
        mode=args.mode,
        include_children=not args.no_children,
        max_tool_output=args.max_tool_output,
        max_text=args.max_text,
    )
    loaded = time.perf_counter()

    if not args.skip_validate:
        validate_bundle(bundle)
    validated = time.perf_counter()

    with out.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(bundle, stream, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    written = time.perf_counter()

    counts = bundle["extra"]["counts"]
    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"session: {args.session}")
    print(f"mode:    {args.mode}")
    print(f"out:     {out}")
    print(f"size:    {size_mb:.2f} MB")
    print(f"counts:  {json.dumps(counts, ensure_ascii=False)}")
    print(f"time:    load={loaded - started:.2f}s validate={validated - loaded:.2f}s write={written - validated:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
