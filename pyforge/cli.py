"""pyforge CLI — auto test generator for Python files."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from pyforge.analysis.python_ast import (
    analyze_python,
    detect_framework,
    detect_lang,
    project_root,
)
from pyforge.coverage import (
    find_uncovered_methods,
    resolve_api_test_path,
    resolve_test_path,
    run_coverage,
)
from pyforge.renderers.api_renderer import detect_api_framework, generate_api_tests
from pyforge.renderers.pytest_renderer import generate_python_test_file
from pyforge.renderers.db_integration_renderer import generate_db_integration_block


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def info(msg: str) -> None:
    print(f"[pyforge] {msg}")


def _strip_markdown_fence(text: str) -> str:
    """Remove markdown code fence if LLM wrapped response in ```python...```."""
    text = text.strip()
    # Match ```python\n...\n``` or ```\n...\n``` format
    m = re.match(r"^```(?:python)?\n(.*)\n```$", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def call_claude(prompt: str) -> str:
    r = subprocess.run(["claude", "--print"], input=prompt, capture_output=True, text=True)
    if r.returncode != 0:
        die(f"Claude failed:\n{r.stderr}")
    return _strip_markdown_fence(r.stdout.strip())


def _build_arg_parser():
    p = argparse.ArgumentParser(
        description="Auto test generator for Python files (pytest)."
    )
    p.add_argument("target", help="Path to the Python source file")
    p.add_argument("--integration", action="store_true",
                   help="Generate integration tests (tests/integration/)")
    p.add_argument("--api", action="store_true",
                   help="Generate API/HTTP endpoint tests")
    p.add_argument(
        "--coverage", type=int,
        default=int(os.getenv("COVERAGE_THRESHOLD", "90")),
        help="Coverage threshold percent (default: 90)",
    )
    p.add_argument(
        "--mode",
        choices=["minimal", "standard", "exhaustive"],
        default="standard",
        help=(
            "minimal=branches+happy-path only; "
            "standard=+boundary+null+defaults+enum; "
            "exhaustive=all strategies"
        ),
    )
    p.add_argument(
        "--execute-capture",
        action="store_true",
        help=(
            "[opt-in] Import and execute the module to capture return values. "
            "WARNING: runs module-level code (may have side effects)."
        ),
    )
    p.add_argument(
        "--db-integration",
        action="store_true",
        help=(
            "Append a real DB integration test class and generate conftest.py. "
            "Activates only when DB dependencies (sqlalchemy, django.db, psycopg2, etc.) "
            "are detected in the source file."
        ),
    )
    return p


def main():
    args = _build_arg_parser().parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        die(f"File not found: {target}")

    # If target is a directory, process all Python files recursively
    if target.is_dir():
        python_files = sorted(target.glob("**/*.py"))
        if not python_files:
            die(f"No Python files found in {target}")
        info(f"Found {len(python_files)} Python file(s)")
        for py_file in python_files:
            info(f"Processing: {py_file}")
            _process_file(py_file, args)
        return

    # Single file mode
    _process_file(target, args)


def _process_file(target: Path, args):
    """Process a single Python file."""
    lang = detect_lang(target)
    root = project_root(target)
    framework = detect_framework(lang, root)
    info(f"Language: {lang} / {framework}")

    source_text = target.read_text()
    try:
        rel = target.relative_to(root).with_suffix("")
        module_path = ".".join(rel.parts)
    except ValueError:
        module_path = target.stem

    # ── API mode ───────────────────────────────────────────────────────────────
    api_framework = detect_api_framework(source_text)
    if args.api or api_framework:
        if not api_framework:
            die("No API routes detected in this file.")
        info(f"API framework: {api_framework}")
        content = generate_api_tests(source_text, api_framework, module_path, source_path=target)
        if not content:
            info("No endpoints detected statically — delegating to Claude.")
            content = call_claude(
                f"Generate pytest API tests for this {api_framework} file.\n"
                f"Source:\n{source_text}\n\n"
                "Output ONLY the test file."
            )
        test_path = resolve_api_test_path(target, root)
        test_path.parent.mkdir(parents=True, exist_ok=True)
        test_path.write_text(content)
        info(f"API test written: {test_path}")
        return

    # ── Unit / integration mode ────────────────────────────────────────────────
    src_info = analyze_python(target, root)
    info(f"Methods found: {[m.name for m in src_info.methods]}")
    info(f"External deps: {[d.name for d in src_info.external_deps]}")

    test_path = resolve_test_path(target, root, args.integration)
    test_path.parent.mkdir(parents=True, exist_ok=True)
    info(f"Test output: {test_path}")

    # incremental mode
    if test_path.exists():
        info("Existing test file found — checking for uncovered methods...")
        uncovered = find_uncovered_methods(src_info, test_path)
        if not uncovered:
            info("All methods covered. Nothing to add.")
            return
        info(f"Uncovered: {[m.name for m in uncovered]}")
        src_info.methods = uncovered

    # generate skeleton via static analysis
    content = generate_python_test_file(
        target, root, src_info, args.coverage,
        mode=args.mode,
        execute_capture=args.execute_capture,
    )
    info("Skeleton generated statically (no Claude call).")

    # write test file
    if test_path.exists():
        existing = test_path.read_text()
        test_path.write_text(existing.rstrip() + "\n\n" + content)
    else:
        test_path.write_text(content)
    info(f"Written: {test_path}")

    # Skip further processing if no tests were generated
    if not content.strip():
        info("No tests generated. Skipping coverage check.")
        return

    # ── DB integration test generation ────────────────────────────────────────
    if args.db_integration:
        integration_block, conftest_content = generate_db_integration_block(target, root, src_info)
        if integration_block:
            test_path.write_text(test_path.read_text().rstrip() + "\n\n" + integration_block)
            info("DB integration test class appended.")
            conftest_path = test_path.parent / "conftest.py"
            if conftest_path.exists():
                info(f"conftest.py already exists at {conftest_path} — skipping (merge manually).")
            else:
                conftest_path.write_text(conftest_content)
                info(f"conftest.py written: {conftest_path}")
        else:
            info("--db-integration passed but no DB dependencies detected — skipping.")

    # coverage check
    if not args.integration:
        if run_coverage(test_path, root, args.coverage, target=target):
            info(f"Coverage ≥ {args.coverage}% achieved.")
        else:
            info(f"WARNING: Coverage below {args.coverage}%. Review and add tests manually.")

    info(f"Done: {test_path}")


if __name__ == "__main__":
    main()
