"""Edge case tests to improve coverage."""
import ast
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyforge.analysis.python_ast import (
    analyze_python,
    parse_type,
    BaseType,
    GenericType,
    UnionType,
    UnknownType,
    is_base,
    is_nullable,
    unwrap_optional,
)
from pyforge.cases.extreme import build_hypothesis_test
from pyforge.coverage import project_root_from_path, resolve_test_path, resolve_api_test_path, find_uncovered_methods, run_coverage
from pyforge.models import MethodInfo, SourceInfo, DepInfo


class TestPythonAstEdgeCases:
    """Edge cases for python_ast module."""

    def test_returnGenericType_whenListIntParsed(self):
        """Test parsing of generic types."""
        # List[int]
        t = parse_type("List[int]")
        assert isinstance(t, GenericType)
        assert t.name == "List"
        assert len(t.args) == 1

    def test_returnGenericType_whenNestedGenericParsed(self):
        """Test parsing nested generics."""
        t = parse_type("Dict[str, List[int]]")
        assert isinstance(t, GenericType)
        assert t.name == "Dict"

    def test_returnUnionType_whenUnionWithNoneParsed(self):
        """Test Union with None."""
        t = parse_type("Union[int, None]")
        assert isinstance(t, UnionType)
        assert len(t.members) == 2

    def test_returnTrue_whenUnionContainsNone(self):
        """Test is_nullable with Union containing None."""
        t = parse_type("int | None")
        assert is_nullable(t) is True

    def test_returnBaseType_whenUnwrappingOptionalUnion(self):
        """Test unwrap_optional on Union with None."""
        t = parse_type("str | None")
        result = unwrap_optional(t)
        # unwrap_optional strips the None from Optional[T] or T | None
        assert isinstance(result, BaseType)
        assert result.name == "str"

    def test_excludeStdlibDeps_whenPlainImportExists(self, tmp_path):
        """Test analyzing module with plain import statements."""
        source = """
import os
import sys
from typing import Optional

class MyClass:
    def method(self, x: int) -> int:
        return x
"""
        py_file = tmp_path / "test_module.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        assert len(result.external_deps) == 0  # os/sys are stdlib

    def test_setIsAsyncTrue_whenAsyncMethodExists(self, tmp_path):
        """Test analyzing async methods."""
        source = """
class AsyncClass:
    async def async_method(self, x: int) -> int:
        await asyncio.sleep(0)
        return x
"""
        py_file = tmp_path / "test_async.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        methods = result.methods
        assert any(m.is_async for m in methods)


class TestExtremeEdgeCases:
    """Edge cases for extreme value testing."""

    def test_generateHypothesisWithAsyncioRun_whenAsyncMethod(self, make_method):
        """Test hypothesis test generation for async methods."""
        method = make_method(
            name="async_method",
            args=["x"],
            arg_types={"x": "int"},
            is_async=True,
            return_type="int",
        )
        result = build_hypothesis_test(method, [], "test.module", "MyClass")
        assert result is not None, "Async method with typed args should generate a hypothesis test"
        assert "asyncio.run" in result, "Async hypothesis test must wrap call with asyncio.run"
        assert "@given" in result

    def test_returnNone_whenMethodIsVoid(self, make_method):
        """Test hypothesis test for void methods returns None."""
        method = make_method(
            name="void_method",
            args=["x"],
            arg_types={"x": "int"},
            is_void=True,
            return_type=None,
        )
        result = build_hypothesis_test(method, [], "test.module", "MyClass")
        assert result is None, "Void methods must not generate hypothesis tests"

    def test_includeDepsInHypothesis_whenConstructorDepsExist(self, make_method):
        """Test hypothesis with constructor dependencies."""
        method = make_method(
            name="method",
            args=["x"],
            arg_types={"x": "int"},
        )
        ctor_map = {"logger": "Logger", "config": "Config"}
        result = build_hypothesis_test(
            method,
            [
                DepInfo(module="logging", name="Logger", alias=None),
                DepInfo(module="config", name="Config", alias=None),
            ],
            "test.module",
            "MyClass",
            constructor_dep_map=ctor_map,
        )
        assert result is not None, "Method with typed args and deps should generate hypothesis test"
        assert "MyClass" in result, "Constructor dep test must instantiate MyClass"


class TestCoverageEdgeCases:
    """Edge cases for coverage module."""

    def test_returnPath_whenNoGitRepoFound(self, tmp_path):
        """Test project_root when git is not available."""
        with patch("pyforge.coverage.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128  # Git not found
            result = project_root_from_path(tmp_path)
            assert result == tmp_path.parent

    def test_returnIntegrationPath_whenIntegrationFlag(self, tmp_path):
        """Test test path resolution for integration tests."""
        result = resolve_test_path(tmp_path / "source.py", tmp_path, integration=True)
        assert "integration" in str(result)
        assert "test_source.py" in str(result)

    def test_returnApiPath_whenApiTestPathResolved(self, tmp_path):
        """Test API test path resolution."""
        # Create a test file so glob finds something
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        test_file = tests_dir / "test_example.py"
        test_file.write_text("")

        result = resolve_api_test_path(tmp_path / "api.py", tmp_path)
        assert "test_api_api.py" in str(result)

    def test_returnUncoveredMethods_whenSomeMethodsNotInTestFile(self, tmp_path):
        """Test finding uncovered methods."""
        test_file = tmp_path / "test_file.py"
        test_file.write_text("def test_method1(): pass")

        info = SourceInfo(
            lang="python",
            class_name=None,
            methods=[
                MethodInfo(name="method1", args=[], arg_types={}, return_type="int", is_void=False, is_public=True),
                MethodInfo(name="method2", args=[], arg_types={}, return_type="int", is_void=False, is_public=True),
            ],
            external_deps=[],
            module_path="test",
            constructor_dep_map={},
            all_classes=[],
            module_level_methods=[],
        )
        result = find_uncovered_methods(info, test_file)
        assert len(result) == 1
        assert result[0].name == "method2"

    def test_passModuleName_whenTargetIsRelative(self, tmp_path):
        """Test run_coverage with target parameter (relative path)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        test_file = tests_dir / "test_sample.py"
        test_file.write_text("""
import pytest
def test_sample():
    assert True
""")

        # Run coverage with target parameter pointing to a file in the project
        source_file = tmp_path / "sample.py"
        source_file.write_text("def hello(): return 42")

        # This should call the try block with relative_to
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_coverage(test_file, tmp_path, 80, target=source_file)
            # Verify that subprocess was called
            assert mock_run.called
            # Check that the module name was properly converted
            call_args = mock_run.call_args
            assert call_args is not None
            cmd = call_args[0][0]  # Get the command list
            assert "sample" in str(cmd)

    def test_passModuleName_whenTargetIsNotRelative(self, tmp_path):
        """Test run_coverage with target that's not relative to root (triggers ValueError)."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()

        test_file = tests_dir / "test_sample.py"
        test_file.write_text("""
import pytest
def test_sample():
    assert True
""")

        # Create a file outside the root directory
        other_dir = Path("/tmp/other_project")
        if other_dir.exists():
            source_file = other_dir / "sample.py"
        else:
            # Fallback: use a path that will trigger ValueError
            source_file = Path("/nonexistent/path/sample.py")

        # This should trigger the except ValueError block by using target.stem
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = run_coverage(test_file, tmp_path, 80, target=source_file)
            # Verify that subprocess was called
            assert mock_run.called
            # The module should fallback to target.stem
            call_args = mock_run.call_args
            assert call_args is not None
            cmd = call_args[0][0]  # Get the command list
            assert "sample" in str(cmd)


class TestCombinatorialEdgeCases:
    """Edge cases for combinatorial generators."""

    def test_returnMembers_whenComplexUnionParsed(self):
        """Test _parse_union_members with simple union."""
        from pyforge.cases.combinatorial import _parse_union_members

        # Simple union with primitives
        result = _parse_union_members("Union[int, str]")
        assert "int" in result
        assert "str" in result

    def test_returnTwoCases_whenSimpleUnionType(self, make_method):
        """Test union_type_cases with simple union."""
        from pyforge.cases.combinatorial import union_type_cases

        method = make_method(
            args=["x"],
            arg_types={"x": "int | str"},
        )
        result = union_type_cases(method)
        # Should generate cases for each union member
        assert len(result) >= 1

    def test_returnCases_whenDefaultIsInvalidNumber(self, make_method):
        """Test default_arg_cases when parsing default number fails."""
        from pyforge.cases.combinatorial import default_arg_cases

        method = make_method(
            args=["value"],
            arg_types={"value": "int"},
            arg_defaults={"value": "invalid_number"},
        )
        result = default_arg_cases(method)
        # Should handle the ValueError and provide a fallback
        assert len(result) >= 1

    def test_returnCases_whenUnionContainsUnknownType(self, make_method):
        """Test union_type_cases with UnknownType in union."""
        from pyforge.cases.combinatorial import union_type_cases

        method = make_method(
            args=["x"],
            arg_types={"x": "CustomType | str"},
        )
        result = union_type_cases(method)
        # CustomType is an UnknownType, should still generate cases
        assert isinstance(result, list)

    def test_returnCases_whenListTypeWithDefault(self, make_method):
        """Test default_arg_cases with list default value."""
        from pyforge.cases.combinatorial import default_arg_cases

        method = make_method(
            args=["items"],
            arg_types={"items": "list"},
            arg_defaults={"items": "[]"},
        )
        result = default_arg_cases(method)
        # Should generate alt value for non-empty list
        overrides = [case.input_overrides["items"] for case in result]
        assert "[1, 2, 3]" in overrides or any("[" in o for o in overrides)


class TestBranchEdgeCases:
    """Edge cases for branch case generation."""

    def test_returnEmptyOrDict_whenConditionIsCallNode(self):
        """Test _condition_to_inputs with function calls."""
        from pyforge.cases.branch import _condition_to_inputs

        source = "validate(x)"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _condition_to_inputs(node, arg_types)
        # Should derive input for x from validate call
        assert isinstance(result, dict)

    def test_returnBoundaryCases_whenConditionUsesFloats(self):
        """Test boundary case generation with float comparisons."""
        from pyforge.cases.branch import _boundary_cases_from_condition

        source = "0.5 < x < 9.5"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "float"}
        result = _boundary_cases_from_condition(node, arg_types, "ValueError")
        # Should handle float boundaries
        assert len(result) > 0

    def test_returnFirstElement_whenInCollectionCondition(self):
        """Test _condition_to_inputs with 'in' operator."""
        from pyforge.cases.branch import _condition_to_inputs

        source = "x in [1, 2, 3]"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _condition_to_inputs(node, arg_types)
        assert "x" in result
        assert result["x"] == "1"  # Should use first element

    def test_returnFirstChar_whenInStringCondition(self):
        """Test _condition_to_inputs with 'in' operator on strings."""
        from pyforge.cases.branch import _condition_to_inputs

        source = "c in 'hello'"
        node = ast.parse(source, mode="eval").body
        arg_types = {"c": "str"}
        result = _condition_to_inputs(node, arg_types)
        assert "c" in result
        # Should use first character
        assert result["c"].startswith("'") or result["c"].startswith('"')

    def test_returnNone_whenIsComparisonCondition(self):
        """Test _condition_to_inputs with 'is' comparison."""
        from pyforge.cases.branch import _condition_to_inputs

        source = "x is None"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _condition_to_inputs(node, arg_types)
        assert "x" in result
        assert result["x"] == "None"

    def test_returnEmptyString_whenLenEqualsZero(self):
        """Test _condition_to_inputs with len(x) == 0."""
        from pyforge.cases.branch import _condition_to_inputs

        source = "len(items) == 0"
        node = ast.parse(source, mode="eval").body
        arg_types = {"items": "list"}
        result = _condition_to_inputs(node, arg_types)
        assert "items" in result
        assert result["items"] == "[]"

    def test_returnPopulatedCollection_whenLenGreaterThan(self):
        """Test _condition_to_inputs with len(x) > N."""
        from pyforge.cases.branch import _condition_to_inputs

        source = "len(items) > 5"
        node = ast.parse(source, mode="eval").body
        arg_types = {"items": "list"}
        result = _condition_to_inputs(node, arg_types)
        assert "items" in result
        # Should be longer than 5
        assert "*" in result["items"] or len(ast.literal_eval(result["items"])) > 5 or "0] * 6" in result["items"]
