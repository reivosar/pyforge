"""Tests for pyforge.coverage module."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pyforge.coverage import (
    find_uncovered_methods,
    parse_missing_coverage,
    project_root_from_path,
    resolve_api_test_path,
    resolve_test_path,
    run_coverage,
)
from pyforge.models import MethodInfo, SourceInfo


class TestProjectRootFromPath:
    """Tests for project_root_from_path."""

    def test_returnGitRoot_whenInsideGitRepo(self, tmp_path):
        """Given a file inside a git repo, when project_root_from_path is called, then it returns the git root."""
        target = tmp_path / "module.py"
        target.touch()
        with patch("pyforge.coverage.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = str(tmp_path) + "\n"
            mock_run.return_value = mock_result
            result = project_root_from_path(target)
        assert result == tmp_path

    def test_returnParentDir_whenNotInsideGitRepo(self, tmp_path):
        """Given a file not inside a git repo, when project_root_from_path is called, then it returns the parent directory."""
        target = tmp_path / "module.py"
        target.touch()
        with patch("pyforge.coverage.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_run.return_value = mock_result
            result = project_root_from_path(target)
        assert result == tmp_path


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

        result, _ = run_coverage(test_file, tmp_path, 90)
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

        result, _ = run_coverage(test_file, tmp_path, 90)
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

        result, _ = run_coverage(test_file, tmp_path, 90)
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

        result, _ = run_coverage(test_file, tmp_path, 90)
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
    def test_useTargetModulePath_whenTargetInsideRoot(self, mock_run, tmp_path):
        """Given a target file inside root, when run_coverage is called, then it uses the dotted module path."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")
        target = tmp_path / "app" / "service.py"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        run_coverage(test_file, tmp_path, 90, target=target)
        call_args = mock_run.call_args[0][0]
        assert "--cov=app.service" in call_args

    @patch("pyforge.coverage.subprocess.run")
    def test_useTargetStem_whenTargetNotRelativeToRoot(self, mock_run, tmp_path):
        """Given a target file outside root, when run_coverage is called, then it falls back to stem as module name."""
        test_file = tmp_path / "test_service.py"
        test_file.write_text("pass")
        # target is in a completely different path (not relative to tmp_path)
        import tempfile
        with tempfile.TemporaryDirectory() as other_dir:
            target = Path(other_dir) / "mymodule.py"
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            run_coverage(test_file, tmp_path, 90, target=target)
            call_args = mock_run.call_args[0][0]
            assert "--cov=mymodule" in call_args

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


class TestParseMissingCoverage:
    """Tests for parse_missing_coverage."""

    def test_returnEmpty_whenNoCoverageData(self):
        """Given empty stdout, when parse_missing_coverage is called, then it returns an empty list."""
        result = parse_missing_coverage("")
        assert result == []

    def test_returnEmpty_whenAllCoverageHigh(self):
        """Given all files with high coverage, when parse_missing_coverage is called, then it returns empty list."""
        stdout = (
            "Name              Stmts   Miss  Cover   Missing\n"
            "----------------------------------------------\n"
            "service.py            20      1    95%   42\n"
            "----------------------------------------------\n"
            "TOTAL                 20      1    95%\n"
        )
        result = parse_missing_coverage(stdout)
        assert result == []

    def test_returnLowCoverageFiles_whenSomeFilesLowCoverage(self):
        """Given files with low coverage, when parse_missing_coverage is called, then it returns those files."""
        stdout = (
            "Name              Stmts   Miss  Cover   Missing\n"
            "----------------------------------------------\n"
            "service.py            50     25    50%   1-10, 20-30\n"
            "utils.py              20      3    85%   42\n"
            "----------------------------------------------\n"
            "TOTAL                 70     28    60%\n"
        )
        result = parse_missing_coverage(stdout)
        assert len(result) == 1
        assert any("service.py" in r for r in result)
        assert any("50%" in r for r in result)
        assert not any("utils.py" in r for r in result)  # 85% is above 80% threshold

    def test_excludeTOTAL_whenParsingCoverageOutput(self):
        """Given a TOTAL line, when parse_missing_coverage is called, then TOTAL is not included in results."""
        stdout = (
            "Name              Stmts   Miss  Cover\n"
            "--------------------------------------\n"
            "service.py            50     40    20%\n"
            "TOTAL                 50     40    20%\n"
        )
        result = parse_missing_coverage(stdout)
        assert any("service.py" in r for r in result)
        assert not any("TOTAL" in r for r in result)

    def test_returnZeroCoverageFile_whenFileHasZeroCoverage(self):
        """Given a file with 0% coverage, when parse_missing_coverage is called, then it is included."""
        stdout = (
            "Name          Stmts   Miss  Cover   Missing\n"
            "------------------------------------------\n"
            "new_module.py     30     30     0%   1-30\n"
        )
        result = parse_missing_coverage(stdout)
        assert len(result) == 1
        assert "new_module.py" in result[0]
        assert "0%" in result[0]
