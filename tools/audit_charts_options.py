"""静态审计 charts option 键的运行时读取情况。"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHARTS = ROOT / "pyqt6_ela_pro" / "charts"
MODELS = CHARTS / "models.py"


def _source_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in CHARTS.rglob("*.py")
        if path != MODELS
    )


def _keys(text: str) -> Counter:
    pattern = re.compile(r'\.get\(\s*["\']([A-Za-z][A-Za-z0-9_.]*)["\']')
    return Counter(pattern.findall(text))


def audit() -> dict:
    return {
        "option_keys": dict(sorted(_keys(_source_text()).items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    report = audit()
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(f"option keys read: {len(report['option_keys'])}")


if __name__ == "__main__":
    main()
