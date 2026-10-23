"""charts 可选依赖：numpy 与 tsdownsample 的可用性必须独立。"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_numpy_survives_missing_tsdownsample():
    pytest.importorskip("numpy")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys
                sys.modules["tsdownsample"] = None
                from pyqt6_ela_pro.charts import _downsample as ds
                print(ds.np is not None)
                print(ds.available())
                print(ds.is_sorted([1, 2, 3]))
                print(ds.bucket_minmax_indices(ds.np.arange(100.0), 10) is not None)
                """
            ),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["True", "False", "True", "True"]
