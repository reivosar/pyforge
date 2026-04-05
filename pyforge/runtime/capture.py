"""Opt-in runtime execution to capture actual return values for assertions.

WARNING: This imports the target module, which may trigger module-level side effects
(DB connections, env var reads, logger initialization, etc.).
Only use when --execute-capture is explicitly passed.
"""
from __future__ import annotations

import importlib.util
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from pyforge.analysis.python_ast import SAMPLE_VALUES
from pyforge.models import MethodInfo, SourceInfo


def try_execute_and_capture(
    target: Path,
    root: Path,
    info_: SourceInfo,
    method: MethodInfo,
    verbose: bool = False,
) -> str | None:
    """
    Import the module, mock all external deps, call the method, and return
    the captured result as a repr string. Returns None if anything fails.

    Only works for Python, non-void, non-async methods.
    """
    if info_.lang != "python" or method.is_void or method.is_async:
        return None

    try:
        spec = importlib.util.spec_from_file_location(info_.module_path, target)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(root))

        patch_targets = [f"{info_.module_path}.{dep.name}" for dep in info_.external_deps]

        with _apply_patches(patch_targets):
            spec.loader.exec_module(mod)
            if info_.class_name:
                cls = getattr(mod, info_.class_name, None)
                if cls is None:
                    return None
                instance = cls.__new__(cls)
                for dep in info_.external_deps:
                    attr = dep.alias or dep.name.lower()
                    setattr(instance, attr, MagicMock())
                func = getattr(instance, method.name, None)
            else:
                func = getattr(mod, method.name, None)

            if func is None:
                return None

            sample_args = {
                arg: _make_sample_value(method.arg_types.get(arg))
                for arg in method.args
            }
            result = func(**sample_args)
            r = repr(result)
            try:
                compile(r, "<repr>", "eval")
                return r
            except SyntaxError:
                return None

    except Exception as exc:
        if verbose:
            print(
                f"[execute-capture] {method.name}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        return None
    finally:
        if str(root) in sys.path:
            sys.path.remove(str(root))


def _apply_patches(targets: list[str]) -> ExitStack:
    """Context manager that patches all given targets."""
    stack = ExitStack()
    for t in targets:
        try:
            stack.enter_context(patch(t, MagicMock()))
        except Exception:
            pass
    return stack


def _make_sample_value(type_hint: str | None) -> Any:
    if not type_hint:
        return None
    base = type_hint.split("[")[0].strip()
    samples = SAMPLE_VALUES.get(base)
    return samples[1] if samples and len(samples) > 1 else None
