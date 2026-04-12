"""pyforge MCP server — exposes test generation as MCP tools."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    raise ImportError(
        "The 'mcp' package is required to use the MCP server. "
        "Install it with: pip install pyforge[mcp]"
    ) from e

from pyforge import (
    analyze_python,
    detect_api_framework,
    find_uncovered_methods,
    generate_api_tests,
    generate_python_test_file,
    parse_missing_lines,
    project_root,
    resolve_test_path,
    run_coverage,
)

mcp = FastMCP("pyforge")


@mcp.tool()
def analyze_file(target: str) -> str:
    """Analyze a Python source file and return a structured summary.

    Returns a JSON object with:
    - module_path: dotted module path relative to the project root
    - class_name: name of the first non-Enum class found (or null)
    - classes: list of {name, methods: [{name, args, return_type, is_async}]}
    - module_level_functions: list of {name, args, return_type, is_async}
    - external_deps: list of {module, name}
    - api_framework: detected API framework ("fastapi", "flask", "django") or null

    Args:
        target: Absolute or relative path to the Python source file to analyze.
    """
    try:
        p = Path(target).resolve()
        root = project_root(p)
        info = analyze_python(p, root)
        source_text = p.read_text()
        api_fw = detect_api_framework(source_text)

        result = {
            "module_path": info.module_path,
            "class_name": info.class_name,
            "classes": [
                {
                    "name": cls.name,
                    "methods": [
                        {
                            "name": m.name,
                            "args": m.args,
                            "return_type": m.return_type,
                            "is_async": m.is_async,
                        }
                        for m in cls.methods
                    ],
                }
                for cls in info.all_classes
            ],
            "module_level_functions": [
                {
                    "name": m.name,
                    "args": m.args,
                    "return_type": m.return_type,
                    "is_async": m.is_async,
                }
                for m in info.module_level_methods
            ],
            "external_deps": [
                {"module": d.module, "name": d.name}
                for d in info.external_deps
            ],
            "api_framework": api_fw,
        }
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def dry_run(
    target: str,
    mode: str = "standard",
    coverage: int = 90,
) -> str:
    """Return the generated test file content without writing anything to disk.

    Useful for previewing what pyforge would generate before committing to disk.
    No coverage check is run. Safe to call on any file.

    Args:
        target:   Absolute or relative path to the Python source file.
        mode:     Test generation strategy — "minimal", "standard" (default),
                  or "exhaustive".
        coverage: Coverage threshold used only to embed the threshold marker in
                  the generated file header (no actual measurement is run).

    Returns:
        The full content of the generated test file as a string.
    """
    try:
        p = Path(target).resolve()
        root = project_root(p)
        info = analyze_python(p, root)
        return generate_python_test_file(p, root, info, coverage, mode=mode)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def generate_tests(
    target: str,
    mode: str = "standard",
    coverage: int = 90,
) -> str:
    """Generate a pytest test file for a Python source file and write it to disk.

    Analyzes the source file statically, generates test cases according to the
    selected mode, and writes the test file. Does NOT run coverage — call
    run_coverage_check separately after generation if needed.

    Args:
        target: Absolute or relative path to the Python source file.
        mode:   Test generation strategy — "minimal", "standard" (default),
                or "exhaustive". minimal=branches+happy-path;
                standard=+boundary+null+defaults+enum;
                exhaustive=all strategies including pairwise/hypothesis.
        coverage: Coverage threshold marker embedded in the generated file header.

    Returns:
        A JSON object: {"test_file": path, "action": "created"|"updated"|"skipped",
        "methods_added": N}
    """
    try:
        p = Path(target).resolve()
        root = project_root(p)
        info = analyze_python(p, root)
        source_text = p.read_text()
        api_fw = detect_api_framework(source_text)

        # Route to API tests if this is an API file
        if api_fw:
            content = generate_api_tests(source_text, api_fw, info.module_path, p)
            test_path = p.parent / f"test_{p.stem}.py"
        else:
            test_path = resolve_test_path(p, root, integration=False)
            content = generate_python_test_file(p, root, info, coverage, mode=mode)

        test_path.parent.mkdir(parents=True, exist_ok=True)
        if test_path.exists():
            uncovered = find_uncovered_methods(info, test_path)
            if not uncovered:
                return json.dumps({"test_file": str(test_path), "action": "skipped", "methods_added": 0})
            existing = test_path.read_text()
            test_path.write_text(existing.rstrip() + "\n\n" + content)
            return json.dumps({"test_file": str(test_path), "action": "updated", "methods_added": len(uncovered)})
        else:
            test_path.write_text(content)
            all_methods = [m for c in info.all_classes for m in c.methods] + info.module_level_methods
            return json.dumps({"test_file": str(test_path), "action": "created", "methods_added": len(all_methods)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def run_coverage_check(
    target: str,
    threshold: int = 90,
) -> str:
    """Run pytest + coverage against the generated test file for a source file.

    Resolves the expected test file path from the source file path, then runs
    pytest --cov with the given threshold. This tool executes a subprocess and
    requires pytest and pytest-cov to be installed in the active environment.

    Args:
        target:    Absolute or relative path to the Python source file.
        threshold: Minimum acceptable coverage percentage (default 90).

    Returns:
        A JSON object: {"status": "PASS"|"FAIL", "threshold": N,
        "test_file": path, "uncovered_methods": [name, ...], "output": pytest_stdout}
    """
    try:
        p = Path(target).resolve()
        root = project_root(p)
        test_path = resolve_test_path(p, root, integration=False)
        if not test_path.exists():
            return json.dumps({"error": f"No test file found at expected path: {test_path}"})

        # Capture print output from run_coverage to avoid contaminating MCP stdio
        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            success, stdout = run_coverage(test_path, root, threshold, target=p)

        # Map coverage missing-line output to function names via AST node line ranges
        info = analyze_python(p, root)
        rel_path = str(p.relative_to(root)).replace("\\", "/")
        missing_lines = parse_missing_lines(stdout, rel_path)
        uncovered_methods = [
            m.name
            for m in info.methods
            if m.ast_node is not None
            and set(range(m.ast_node.lineno, m.ast_node.end_lineno + 1)) & missing_lines
        ]

        return json.dumps({
            "status": "PASS" if success else "FAIL",
            "threshold": threshold,
            "test_file": str(test_path),
            "uncovered_methods": uncovered_methods,
            "output": stdout,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def run() -> None:
    """Entry point for the pyforge-mcp console script."""
    mcp.run()


if __name__ == "__main__":
    run()
