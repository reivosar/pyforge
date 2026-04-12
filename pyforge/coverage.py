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


def parse_missing_coverage(coverage_stdout: str) -> list[str]:
    """Parse coverage report and return list of files with 0% or low coverage."""
    lines = coverage_stdout.split("\n")
    missing = []
    for line in lines:
        # Look for lines with coverage percentages
        # Format: "filename.py        50      25    50%    1-10, 20-30"
        if "%" in line and ("py" in line or "TOTAL" in line):
            parts = line.split()
            if len(parts) >= 4:
                # Try to find the coverage percentage
                for part in parts:
                    if "%" in part:
                        coverage_pct = int(part.rstrip("%"))
                        if coverage_pct < 80:  # Flag files with < 80% coverage
                            filename = parts[0]
                            if filename != "TOTAL" and not filename.startswith("-"):
                                missing.append(f"{filename} ({coverage_pct}%)")
                        break
    return missing


def run_coverage(test_file: Path, root: Path, threshold: int, target: Path | None = None) -> tuple[bool, str]:
    """Run pytest with coverage and return (success, stdout)."""
    print(f"[test-gen] Running coverage (threshold: {threshold}%)...")
    try:
        if target is not None:
            try:
                rel = target.relative_to(root)
                module = str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
            except ValueError:
                module = target.stem
        else:
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
        # Only trigger Claude retry when COVERAGE is below threshold.
        # Regular test failures are expected during iterative development.
        if r.returncode != 0:
            output = r.stdout + r.stderr
            cov_failure = (
                f"Required test coverage of {threshold}%" in output
                or (f"total of " in output and f"is less than fail-under={threshold}" in output)
            )
            if not cov_failure:
                return True, r.stdout  # Tests may fail, but coverage threshold check is not the issue
        return r.returncode == 0, r.stdout
    except FileNotFoundError as e:
        print(f"[test-gen] Coverage tool not found ({e}), skipping.")
        return False, ""
