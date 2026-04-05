"""Coverage measurement and test path resolution (Python only)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pyforge.models import MethodInfo, SourceInfo


def project_root_from_path(target: Path) -> Path:
    """Return git project root for target, or its parent directory."""
    r = subprocess.run(
        ["git", "-C", str(target.parent), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return Path(r.stdout.strip()) if r.returncode == 0 else target.parent


def resolve_test_path(target: Path, root: Path, integration: bool) -> Path:
    """Return the output path for the generated test file."""
    if integration:
        p = root / "tests" / "integration"
        p.mkdir(parents=True, exist_ok=True)
        return p / f"test_{target.name}"
    else:
        candidates = [p for p in root.glob("**/test_*.py") if "node_modules" not in str(p)]
        test_dir = candidates[0].parent if candidates else root
        return test_dir / f"test_{target.name}"


def resolve_api_test_path(target: Path, root: Path) -> Path:
    """Return the output path for an API test file."""
    candidates = [p for p in root.glob("**/test_*.py") if "node_modules" not in str(p)]
    test_dir = candidates[0].parent if candidates else root
    return test_dir / f"test_{target.stem}_api.py"


def find_uncovered_methods(info_: SourceInfo, test_file: Path) -> list[MethodInfo]:
    """Return methods not yet referenced in the test file."""
    test_content = test_file.read_text()
    return [m for m in info_.methods if m.name not in test_content]


def run_coverage(test_file: Path, root: Path, threshold: int) -> bool:
    """Run pytest with coverage and return True if threshold is met."""
    print(f"[test-gen] Running coverage (threshold: {threshold}%)...")
    try:
        module = test_file.stem.replace("test_", "")
        r = subprocess.run(
            [
                sys.executable, "-m", "pytest", str(test_file),
                f"--cov={module}", "--cov-report=term-missing",
                f"--cov-fail-under={threshold}",
            ],
            cwd=root, capture_output=True, text=True,
        )
        print(r.stdout)
        return r.returncode == 0
    except FileNotFoundError as e:
        print(f"[test-gen] Coverage tool not found ({e}), skipping.")
        return False
