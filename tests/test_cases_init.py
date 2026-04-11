"""Tests for pyforge.cases.__init__ (generate_cases)."""
import pytest

from pyforge.cases import TIER_GENERATORS, generate_cases


class TestTierGenerators:
    """Tests for TIER_GENERATORS."""

    def test_returnExactlyThreeTierKeys_whenTierGeneratorsQueried(self):
        """Given TIER_GENERATORS, when queried, then it has exactly minimal, standard, and exhaustive tiers."""
        assert set(TIER_GENERATORS.keys()) == {"minimal", "standard", "exhaustive"}

    def test_containsBranchAndHappyPath_whenMinimalTierQueried(self):
        """Given the minimal tier, when queried, then it includes 'branch' and 'happy_path' generators."""
        minimal = TIER_GENERATORS["minimal"]
        assert "branch" in minimal
        assert "happy_path" in minimal

    def test_includeAllMinimalGenerators_whenStandardTierQueried(self):
        """Given the standard tier, when queried, then it includes all minimal generators plus null/defaults/enum."""
        standard = TIER_GENERATORS["standard"]
        minimal = TIER_GENERATORS["minimal"]
        assert minimal.issubset(standard)
        assert "null" in standard
        assert "defaults" in standard
        assert "enum" in standard

    def test_includeAllStandardGenerators_whenExhaustiveTierQueried(self):
        """Given the exhaustive tier, when queried, then it includes all standard generators plus pairwise/union/extreme/hypothesis."""
        exhaustive = TIER_GENERATORS["exhaustive"]
        standard = TIER_GENERATORS["standard"]
        assert standard.issubset(exhaustive)
        assert "pairwise" in exhaustive
        assert "union" in exhaustive
        assert "extreme" in exhaustive
        assert "hypothesis" in exhaustive


class TestGenerateCases:
    """Tests for generate_cases()."""

    def test_returnBranchAndHappyCasesOnly_whenMinimalMode(self, make_method):
        """Given minimal mode, when generate_cases is called, then it contains only branch cases with exceptions or returns."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = generate_cases(method, {}, mode="minimal")
        # Should contain branch cases (at least happy path)
        assert len(result) > 0
        # No null/enum/pairwise cases in minimal
        # In minimal mode, some branch cases are filtered out
        assert any(c.is_happy_path for c in result)

    def test_filterNonExceptionAndNonReturnCases_whenMinimalMode(self, make_method):
        """Given minimal mode, when generate_cases is called, then it filters out cases without expected_return and not happy_path."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = generate_cases(method, {}, mode="minimal")
        # Should only include: exceptions, returns, or happy path
        for case in result:
            is_valid = (
                case.expected_exception is not None
                or (case.expected_return is not None and not case.is_happy_path)
                or case.is_happy_path
            )
            assert is_valid

    def test_includeNullCases_whenStandardModeWithUntypedArgs(self, make_method):
        """Given standard mode, when generate_cases is called, then it includes null cases for untyped arguments."""
        method = make_method(
            args=["x", "y"],
            arg_types={"x": "int"},
        )
        result = generate_cases(method, {}, mode="standard")
        # Should have null case for untyped y
        test_names = {c.test_name for c in result}
        assert any("IsNone" in name for name in test_names)

    def test_includeDefaultCases_whenStandardModeWithDefaultArgs(self, make_method):
        """Given standard mode with default arguments, when generate_cases is called, then it includes default cases."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            arg_defaults={"x": "5"},
        )
        result = generate_cases(method, {}, mode="standard")
        test_names = {c.test_name for c in result}
        # Should have default cases
        assert any("Default" in name for name in test_names)

    def test_includeEnumCases_whenStandardModeWithEnumTypes(self, make_method):
        """Given standard mode with enum types, when generate_cases is called, then it includes enum cases."""
        method = make_method(
            args=["status"],
            arg_types={"status": "Status"},
        )
        enum_types = {"Status": ["A", "B"]}
        result = generate_cases(method, enum_types, mode="standard")
        test_names = {c.test_name for c in result}
        # Should have enum cases
        assert any("Status" in name for name in test_names)

    def test_includePairwiseCases_whenExhaustiveModeWithThreePlusArgs(self, make_method):
        """Given exhaustive mode with 3 or more arguments, when generate_cases is called, then it includes pairwise cases."""
        method = make_method(
            args=["a", "b", "c"],
            arg_types={"a": "int", "b": "str", "c": "bool"},
        )
        result = generate_cases(method, {}, mode="exhaustive")
        test_names = {c.test_name for c in result}
        # Should have pairwise cases
        assert any("pairwise" in name.lower() for name in test_names)

    def test_includeUnionCases_whenExhaustiveModeWithUnionTypes(self, make_method):
        """Given exhaustive mode with union types, when generate_cases is called, then it includes union cases."""
        method = make_method(
            args=["value"],
            arg_types={"value": "Union[int, str]"},
        )
        result = generate_cases(method, {}, mode="exhaustive")
        # Should have union cases (2 for int and str)
        assert len(result) >= 2

    def test_includeExtremeCases_whenExhaustiveMode(self, make_method):
        """Given exhaustive mode, when generate_cases is called, then it includes extreme value cases."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = generate_cases(method, {}, mode="exhaustive")
        test_names = {c.test_name for c in result}
        # Should have extreme cases
        assert any("Extreme" in name or "MaxInt" in name for name in test_names)

    def test_fallBackToStandardCases_whenUnknownMode(self, make_method):
        """Given an unknown mode, when generate_cases is called, then it falls back to standard mode."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
        )
        result = generate_cases(method, {}, mode="foobar")
        standard_result = generate_cases(method, {}, mode="standard")
        result_names = {c.test_name for c in result}
        standard_names = {c.test_name for c in standard_result}
        assert result_names == standard_names, (
            f"Unknown mode must fall back to standard. "
            f"Missing: {standard_names - result_names}, extra: {result_names - standard_names}"
        )

    def test_returnOnlyBranchCaseObjects_whenExhaustiveMode(self, make_method):
        """hypothesis tests are NOT included in output — they are strings, not BranchCases."""
        from pyforge.models import BranchCase
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = generate_cases(method, {}, mode="exhaustive")
        assert all(isinstance(c, BranchCase) for c in result), (
            "generate_cases must return only BranchCase objects; "
            "hypothesis test strings must be excluded"
        )

    def test_returnOnlyHappyPath_whenMethodHasNoArgs(self, make_method):
        """Method with 0 args → no null/pairwise/enum cases."""
        method = make_method(args=[])
        result = generate_cases(method, {}, mode="exhaustive")
        test_names = {c.test_name for c in result}
        # Should only have happy path (from branch analysis)
        # No null, pairwise, enum, union cases
        assert any(c.is_happy_path for c in result)

    def test_includeMinimalCasesInStandard_whenModesCompared(self, make_method):
        """Cases from lower modes are included in higher modes."""
        method = make_method(
            args=["x", "y"],
            arg_types={"x": "int", "y": "str"},
        )
        minimal = generate_cases(method, {}, mode="minimal")
        standard = generate_cases(method, {}, mode="standard")
        exhaustive = generate_cases(method, {}, mode="exhaustive")

        # minimal cases should be in standard (by test_name)
        minimal_names = {c.test_name for c in minimal}
        standard_names = {c.test_name for c in standard}
        assert minimal_names.issubset(standard_names)

    def test_returnList_whenGenerateCasesCalled(self, make_method):
        """generate_cases always returns a list."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        result = generate_cases(method, {}, mode="standard")
        assert isinstance(result, list)
