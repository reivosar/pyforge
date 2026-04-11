"""Tests for pyforge.coverage module."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyforge.coverage import (
    find_uncovered_methods,
    resolve_api_test_path,
    resolve_test_path,
    run_coverage,
)
from pyforge.models import MethodInfo, SourceInfo


class TestResolveTestPath:
    """Tests for resolve_test_path."""

    def test_returnTestServicePath_whenUnitTestFlag(self, tmp_path):
        """Given a target file for unit testing, when resolve_test_path is called, then it returns a path ending with test_{target_name}."""
        target = tmp_path / "service.py"
        result = resolve_test_path(target, tmp_path, integration=False)
        assert str(result).endswith("test_service.py")

    def test_returnIntegrationPath_whenIntegrationFlag(self, tmp_path):
        """Given a target file for integration testing, when resolve_test_path is called, then it returns a path under tests/integration/."""
        target = tmp_path / "service.py"
        result = resolve_test_path(target, tmp_path, integration=True)
        assert "integration" in str(result)
        assert "test_service.py" in str(result)

    def test_useExistingTestsDir_whenTestsDirExists(self, tmp_path):
        """Given an existing test directory, when resolve_test_path is called, then it uses that directory."""
        # Create existing test file
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_existing.py").touch()

        target = tmp_path / "service.py"
        result = resolve_test_path(target, tmp_path, integration=False)
        # Should use tests/ directory
        assert "tests" in str(result)

    def test_fallBackToRoot_whenNoTestDirExists(self, tmp_path):
        """Given no existing tests, when resolve_test_path is called, then it falls back to the root directory."""
        target = tmp_path / "service.py"
        result = resolve_test_path(target, tmp_path, integration=False)
        # Should be directly in root (or its subdirectory)
        assert "test_" in str(result)


class TestResolveApiTestPath:
    """Tests for resolve_api_test_path."""

    def test_returnApiPath_whenApiTestPathResolved(self, tmp_path):
        """Given a target file for API testing, when resolve_api_test_path is called, then it returns a path ending with test_{stem}_api.py."""
        target = tmp_path / "routes.py"
        result = resolve_api_test_path(target, tmp_path)
        assert str(result).endswith("test_routes_api.py")

    def test_useExistingTestsDir_whenTestsDirExistsForApi(self, tmp_path):
        """Given an existing test directory, when resolve_api_test_path is called, then it uses that directory."""
        # Create existing test file
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_existing.py").touch()

        target = tmp_path / "routes.py"
        result = resolve_api_test_path(target, tmp_path)
        # Should use tests/ directory
        assert "tests" in str(result)


class TestFindUncoveredMethods:
    """Tests for find_uncovered_methods."""

    def test_returnEmptyList_whenAllMethodsCovered(self, tmp_path):
        """Given a test file covering all methods, when find_uncovered_methods is called, then it returns an empty list."""
        # Create test file with method names
        test_file = tmp_path / "test_service.py"
        test_file.write_text("""
def test_get_user():
    ...

def test_delete_user():
    ...
""")

        method1 = MethodInfo(
            name="get_user",
            args=[],
            arg_types={},
            return_type="str",
            is_void=False,
            is_public=True,
        )
        method2 = MethodInfo(
            name="delete_user",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )

        source = SourceInfo(
            lang="python",
            class_name="Service",
            methods=[method1, method2],
            external_deps=[],
            module_path="app.service",
        )

        result = find_uncovered_methods(source, test_file)
        assert result == []

    def test_returnMissingMethods_whenSomeMethodsUncovered(self, tmp_path):
        """Given a test file missing coverage for some methods, when find_uncovered_methods is called, then it returns the missing methods."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("""
def test_get_user():
    ...
""")

        method1 = MethodInfo(
            name="get_user",
            args=[],
            arg_types={},
            return_type="str",
            is_void=False,
            is_public=True,
        )
        method2 = MethodInfo(
            name="delete_user",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )

        source = SourceInfo(
            lang="python",
            class_name="Service",
            methods=[method1, method2],
            external_deps=[],
            module_path="app.service",
        )

        result = find_uncovered_methods(source, test_file)
        assert len(result) == 1
        assert result[0].name == "delete_user"

    def test_returnAllMethods_whenNoMethodsCovered(self, tmp_path):
        """Given an empty test file, when find_uncovered_methods is called, then it returns all methods as uncovered."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("")

        method1 = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )

        source = SourceInfo(
            lang="python",
            class_name="Service",
            methods=[method1],
            external_deps=[],
            module_path="app.service",
        )

        result = find_uncovered_methods(source, test_file)
        assert len(result) == 1
        assert result[0].name == "foo"


class TestRunCoverage:
    """Tests for run_coverage."""

    @patch("pyforge.coverage.subprocess.run")
    def test_returnFalse_whenFileNotFound(self, mock_run, tmp_path):
        """Given a missing test file, when run_coverage is called, then it returns False."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")
        mock_run.side_effect = FileNotFoundError()

        result = run_coverage(test_file, tmp_path, 90)
        assert result is False

    @patch("pyforge.coverage.subprocess.run")
    def test_returnTrue_whenSubprocessSucceeds(self, mock_run, tmp_path):
        """Given a test with successful subprocess execution, when run_coverage is called, then it returns True."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")

        # Mock successful subprocess run
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "coverage: 95%\n"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run_coverage(test_file, tmp_path, 90)
        assert result is True

    @patch("pyforge.coverage.subprocess.run")
    def test_returnTrue_whenTestFailNotCoverageRelated(
        self, mock_run, tmp_path
    ):
        """Given a test failure unrelated to coverage, when run_coverage is called, then it returns True."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")

        # Mock failing subprocess with test failure, not coverage failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED test_foo"
        mock_result.stderr = "AssertionError: expected 1 but got 2"
        mock_run.return_value = mock_result

        result = run_coverage(test_file, tmp_path, 90)
        assert result is True

    @patch("pyforge.coverage.subprocess.run")
    def test_returnFalse_whenCoverageBelowThreshold(
        self, mock_run, tmp_path
    ):
        """Given a coverage result below the threshold, when run_coverage is called, then it returns False."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")

        # Mock coverage failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Required test coverage of 90% not met. Total coverage: 80%.\n"
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        result = run_coverage(test_file, tmp_path, 90)
        assert result is False

    @patch("pyforge.coverage.subprocess.run")
    def test_passModuleName_whenRunCoverageCalled(self, mock_run, tmp_path):
        """Given a test file, when run_coverage is called, then it calls subprocess with the correct module name."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        run_coverage(test_file, tmp_path, 90)

        # Check that subprocess was called with the correct module name
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        # test_service.py → module = "service" → --cov=service
        assert "--cov=service" in call_args, (
            f"Expected '--cov=service' in command, got: {call_args}"
        )

    @patch("pyforge.coverage.subprocess.run")
    def test_passThresholdValue_whenRunCoverageCalled(self, mock_run, tmp_path):
        """Given a coverage threshold value, when run_coverage is called, then it passes the threshold to the subprocess."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result

        run_coverage(test_file, tmp_path, 85)

        # Check that subprocess was called with threshold
        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "--cov-fail-under=85" in call_args
