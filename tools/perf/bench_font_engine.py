"""Win7 字体引擎 A/B 探针：ASCII → CJK → ASCII 的绘制耗时。

用来验证 bug #15（CJK shaping 后纯 Latin 文本变慢）是否与 DirectWrite 字体引擎有关。
同一台机器跑两次，只改平台插件参数：

    uv run python tools/perf/bench_font_engine.py
    $env:QT_QPA_PLATFORM='windows:nodirectwrite'
    uv run python tools/perf/bench_font_engine.py

关注 ``ascii_after`` 相对 ``ascii_before`` 的倍率：正常应接近 1；若达到 10~40×，
说明命中了 #15 的进程级 shaping 慢路径。``nodirectwrite`` 把 Qt 切到 GDI 字体
引擎（issue crystalidea/qt6windows7#63 的 workaround），用于判断换引擎是否消除。
"""

from __future__ import annotations

import argparse
import os
import statistics
import time

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QTextBrowser


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ascii-chars", type=int, default=13000)
    parser.add_argument("--cjk-chars", type=int, default=4000)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument(
        "--hinting",
        choices=("default", "no", "vertical", "full"),
        default="default",
        help="QFont 的 hinting preference（no/vertical 会强制 DirectWrite）",
    )
    return parser.parse_args(argv)


def _hinting_preference(name: str):
    return {
        "default": QFont.HintingPreference.PreferDefaultHinting,
        "no": QFont.HintingPreference.PreferNoHinting,
        "vertical": QFont.HintingPreference.PreferVerticalHinting,
        "full": QFont.HintingPreference.PreferFullHinting,
    }[name]


def _measure(browser: QTextBrowser, text: str, samples: int) -> tuple[float, float]:
    browser.setPlainText(text)
    QApplication.processEvents()
    times = []
    for _ in range(samples):
        started = time.perf_counter()
        browser.viewport().repaint()
        QApplication.processEvents()
        times.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(times), max(times)


def main(argv=None) -> int:
    args = _parse_args(argv)
    app = QApplication(["bench-font-engine"])
    font = QFont("Consolas", 10)
    font.setHintingPreference(_hinting_preference(args.hinting))

    browser = QTextBrowser()
    browser.resize(1000, 700)
    browser.setFont(font)
    browser.show()
    app.processEvents()

    ascii_text = ("The quick brown fox jumps over the lazy dog. " * 1000)[
        : args.ascii_chars
    ]
    cjk_text = ("这是一个用于测试字体回退性能的中文段落，包含常见汉字与标点。" * 1000)[
        : args.cjk_chars
    ]

    print(f"platform      {app.platformName()}")
    print(f"QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM', '')!r}")
    print(f"devicePixelRatio {app.devicePixelRatio()}")
    print(f"font          {font.family()} / hinting {args.hinting}")
    for label, text in (
        ("ascii_before", ascii_text),
        ("cjk", cjk_text),
        ("ascii_after", ascii_text),
    ):
        median, worst = _measure(browser, text, args.samples)
        print(f"{label:12}  median {median:7.2f} ms   max {worst:7.2f} ms")

    browser.close()
    browser.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
