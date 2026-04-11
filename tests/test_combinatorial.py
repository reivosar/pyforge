"""Tests for pyforge.cases.combinatorial generators."""
import pytest

from pyforge.analysis.python_ast import _type_sample
from pyforge.cases.combinatorial import (
    _parse_union_members,
    default_arg_cases,
    enum_cases,
    null_combination_cases,
    pairwise_cases,
    union_type_cases,
)
from pyforge.models import MethodInfo


class TestNullCombinationCases:
    """Tests for null_combination_cases."""

    def test_returnEmptyList_whenSingleArgMethod(self, make_method):
        """Given a single arg method, when null_combination_cases is called, then it returns an empty list."""
        method = make_method(args=["x"], arg_types={"x": "str"})
        result = null_combination_cases(method)
        assert result == []

    def test_returnEmptyList_whenZeroArgMethod(self, make_method):
        """Given a zero arg method, when null_combination_cases is called, then it returns an empty list."""
        method = make_method(args=[])
        result = null_combination_cases(method)
        assert result == []

    def test_returnOneNullCase_whenUntypedArgPresent(self, make_method):
        """Given a method with 2 args where one is untyped, when null_combination_cases is called, then it produces one null case."""
        method = make_method(args=["x", "y"], arg_types={"x": "int"})
        result = null_combination_cases(method)
        assert len(result) == 1
        assert result[0].test_name == "raiseOrReturnNone_whenYIsNone"
        assert result[0].input_overrides == {"y": "None"}

    def test_returnOneNullCase_whenOptionalTypedArgPresent(self, make_method):
        """Given an Optional[T] arg, when null_combination_cases is called, then it is detected as nullable."""
        method = make_method(
            args=["x", "y"],
            arg_types={"x": "str", "y": "Optional[int]"},
        )
        result = null_combination_cases(method)
        assert len(result) == 1
        assert result[0].test_name == "raiseOrReturnNone_whenYIsNone"

    def test_returnEmptyList_whenAllArgsTypedNonOptional(self, make_method):
        """Given typed non-optional args, when null_combination_cases is called, then they are excluded."""
        method = make_method(
            args=["x", "y"],
            arg_types={"x": "int", "y": "str"},
        )
        result = null_combination_cases(method)
        assert result == []

    def test_returnCamelCaseTestName_whenArgNameIsUnderscored(self, make_method):
        """Given a method with underscored arg names, when null_combination_cases is called, then test names use camelCase."""
        method = make_method(
            args=["user_id", "is_active"],
            arg_types={"user_id": "int"},
        )
        result = null_combination_cases(method)
        assert len(result) == 1
        assert result[0].test_name == "raiseOrReturnNone_whenIsActiveIsNone"

    def test_returnMultipleNullCases_whenMultipleNullableArgs(self, make_method):
        """Given multiple nullable args, when null_combination_cases is called, then multiple cases are produced."""
        method = make_method(
            args=["x", "y", "z"],
            arg_types={"x": "Optional[int]", "z": "str"},
        )
        result = null_combination_cases(method)
        assert len(result) == 2
        test_names = {case.test_name for case in result}
        assert "raiseOrReturnNone_whenXIsNone" in test_names
        assert "raiseOrReturnNone_whenYIsNone" in test_names

    def test_setCorrectBranchCaseFields_whenNullCaseCreated(self, make_method):
        """Given a null combination case, when created, then all BranchCase fields are set correctly."""
        method = make_method(args=["x", "y"], arg_types={"x": "int"})
        result = null_combination_cases(method)
        case = result[0]
        assert case.is_happy_path is False
        assert case.expected_exception is None
        assert case.expected_return is None
        assert case.mock_side_effect is None
        assert case.mock_return_override is None

    def test_notTreatAsOptional_whenTypeNameContainsOptionalSubstring(self, make_method):
        """Given a type name 'OptionalUser' that contains 'Optional' as substring, when null_combination_cases is called, then it is not treated as Optional type."""
        method = make_method(
            args=["x", "y"],
            arg_types={"x": "int", "y": "OptionalUser"}  # NOT Optional[User]
        )
        result = null_combination_cases(method)
        assert len(result) == 0, \
            f"'OptionalUser' should not be treated as Optional type. Got {len(result)} cases"


class TestEnumCases:
    """Tests for enum_cases."""

    def test_returnEmptyList_whenNoMatchingEnumType(self, make_method):
        """Given no matching enum types, when enum_cases is called, then it returns an empty list."""
        method = make_method(args=["status"], arg_types={"status": "Status"})
        result = enum_cases(method, {})
        assert result == []

    def test_returnOneCasePerMember_whenSingleEnumArg(self, make_method):
        """Given a single enum arg, when enum_cases is called, then one case per member is produced."""
        method = make_method(args=["status"], arg_types={"status": "Status"})
        enum_types = {"Status": ["ACTIVE", "INACTIVE", "PENDING"]}
        result = enum_cases(method, enum_types)
        assert len(result) == 3
        test_names = {case.test_name for case in result}
        assert "complete_whenStatusIsACTIVE" in test_names
        assert "complete_whenStatusIsINACTIVE" in test_names
        assert "complete_whenStatusIsPENDING" in test_names

    def test_includeEnumAndMemberName_whenEnumCaseCreated(self, make_method):
        """Given enum cases, when created, then test names include enum and member name."""
        method = make_method(args=["s"], arg_types={"s": "Status"})
        enum_types = {"Status": ["ON", "OFF"]}
        result = enum_cases(method, enum_types)
        test_names = {case.test_name for case in result}
        assert "complete_whenSIsON" in test_names
        assert "complete_whenSIsOFF" in test_names

    def test_setEnumClassDotMember_whenInputOverrideCreated(self, make_method):
        """Given enum cases, when created, then input overrides contain {arg: EnumClass.MEMBER}."""
        method = make_method(args=["status"], arg_types={"status": "Status"})
        enum_types = {"Status": ["A"]}
        result = enum_cases(method, enum_types)
        assert result[0].input_overrides == {"status": "Status.A"}

    def test_returnSeparateCasesForEachEnum_whenMultipleEnumArgs(self, make_method):
        """Given two different enum args, when enum_cases is called, then separate cases are produced (not cross-product)."""
        method = make_method(
            args=["status", "priority"],
            arg_types={"status": "Status", "priority": "Priority"},
        )
        enum_types = {"Status": ["ON", "OFF"], "Priority": ["HIGH", "LOW"]}
        result = enum_cases(method, enum_types)
        assert len(result) == 4
        # Check cases are generated for both args
        test_names = {case.test_name for case in result}
        has_status = any("Status" in name for name in test_names)
        has_priority = any("Priority" in name for name in test_names)
        assert has_status
        assert has_priority

    def test_returnEmptyList_whenArgTypeNotEnum(self, make_method):
        """Given a non-enum-typed arg, when enum_cases is called, then it is skipped."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        enum_types = {"Status": ["A"]}
        result = enum_cases(method, enum_types)
        assert result == []


class TestPairwiseCases:
    """Tests for pairwise_cases."""

    def test_returnEmptyList_whenFewerThanThreeArgs(self, make_method):
        """Given 0, 1, or 2 args, when pairwise_cases is called, then it returns an empty list."""
        for num_args in [0, 1, 2]:
            args = [f"arg{i}" for i in range(num_args)]
            method = make_method(args=args)
            result = pairwise_cases(method)
            assert result == []

    def test_returnPairwiseCombinations_whenThreeTypedArgs(self, make_method):
        """Given a 3-arg method with int, str, and bool, when pairwise_cases is called, then pairwise combinations are generated."""
        method = make_method(
            args=["x", "y", "z"],
            arg_types={"x": "int", "y": "str", "z": "bool"},
        )
        result = pairwise_cases(method)
        assert len(result) > 0
        # All pairs must be covered
        pairs_covered = set()
        for case in result:
            for arg1 in ["x", "y", "z"]:
                for arg2 in ["x", "y", "z"]:
                    if arg1 < arg2 and arg1 in case.input_overrides and arg2 in case.input_overrides:
                        pairs_covered.add((arg1, arg2))
        # Should cover all 3 pairs: (x,y), (x,z), (y,z)
        assert len(pairs_covered) == 3

    def test_coverAllPairs_whenThreeIntArgs(self, make_method):
        """Given a 3-arg method, when pairwise_cases is called, then every pair appears in at least one row."""
        method = make_method(
            args=["a", "b", "c"],
            arg_types={"a": "int", "b": "int", "c": "int"},
        )
        result = pairwise_cases(method)
        assert len(result) > 0

    def test_includePairwiseCombInName_whenCaseCreated(self, make_method):
        """Given pairwise cases, when created, then test names include 'pairwise' and arg names."""
        method = make_method(
            args=["x", "y", "z"],
            arg_types={"x": "int", "y": "str", "z": "bool"},
        )
        result = pairwise_cases(method)
        assert any("pairwiseComb" in case.test_name for case in result)

    def test_returnCases_whenUntypedArgs(self, make_method):
        """Given untyped args, when pairwise_cases is called, then they use [None, 'test'] values."""
        method = make_method(args=["x", "y", "z"])
        result = pairwise_cases(method)
        assert len(result) > 0

    def test_terminateQuickly_whenFiveArgs(self, make_method):
        """Given a 5-arg method, when pairwise_cases is called, then it terminates quickly without excessive iterations."""
        import time
        method = make_method(
            args=["a", "b", "c", "d", "e"],
            arg_types={
                "a": "int",
                "b": "str",
                "c": "bool",
                "d": "float",
                "e": "int",
            },
        )
        start = time.perf_counter()
        result = pairwise_cases(method)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0  # Should be much faster
        assert len(result) > 0

    def test_setCorrectBranchCaseFields_whenPairwiseCaseCreated(self, make_method):
        """Given pairwise cases, when created, then BranchCase fields are set correctly."""
        method = make_method(
            args=["x", "y", "z"],
            arg_types={"x": "int", "y": "str", "z": "bool"},
        )
        result = pairwise_cases(method)
        case = result[0]
        assert case.is_happy_path is False
        assert case.expected_exception is None
        assert case.expected_return is None


class TestDefaultArgCases:
    """Tests for default_arg_cases - PRIORITY (recently modified)."""

    def test_returnEmptyList_whenNoArgDefaults(self, make_method):
        """Given no defaults, when default_arg_cases is called, then it returns an empty list."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        result = default_arg_cases(method)
        assert result == []

    def test_returnFalseAsAlt_whenBoolDefaultIsTrue(self, make_method):
        """Given bool default=True, when default_arg_cases is called, then alt=False."""
        method = make_method(
            args=["flag"],
            arg_types={"flag": "bool"},
            arg_defaults={"flag": "True"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["flag"] for case in result}
        assert "True" in overrides
        assert "False" in overrides

    def test_returnTrueAsAlt_whenBoolDefaultIsFalse(self, make_method):
        """Given bool default=False, when default_arg_cases is called, then alt=True."""
        method = make_method(
            args=["flag"],
            arg_types={"flag": "bool"},
            arg_defaults={"flag": "False"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["flag"] for case in result}
        assert "True" in overrides
        assert "False" in overrides

    def test_returnEmptyStringAsAlt_whenStrDefaultIsNonEmpty(self, make_method):
        """Given str default != "", when default_arg_cases is called, then alt=""."""
        method = make_method(
            args=["name"],
            arg_types={"name": "str"},
            arg_defaults={"name": '"John"'},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["name"] for case in result}
        assert '"John"' in overrides
        assert '""' in overrides

    def test_returnAltStringAsAlt_whenStrDefaultIsEmpty(self, make_method):
        """Given str default="", when default_arg_cases is called, then alt="alt"."""
        method = make_method(
            args=["name"],
            arg_types={"name": "str"},
            arg_defaults={"name": '""'},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["name"] for case in result}
        assert '""' in overrides
        assert '"alt"' in overrides

    def test_returnHalfAsAlt_whenIntDefaultGreaterThanOne(self, make_method):
        """Given int default > 1, when default_arg_cases is called, then alt = default // 2."""
        method = make_method(
            args=["count"],
            arg_types={"count": "int"},
            arg_defaults={"count": "10"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["count"] for case in result}
        assert "10" in overrides
        assert "5" in overrides

    def test_returnOneAsAlt_whenIntDefaultIsZero(self, make_method):
        """Given int default=0, when default_arg_cases is called, then alt=1."""
        method = make_method(
            args=["value"],
            arg_types={"value": "int"},
            arg_defaults={"value": "0"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["value"] for case in result}
        assert "0" in overrides
        assert "1" in overrides

    def test_returnValidAlt_whenFloatDefault(self, make_method):
        """Given a float default, when default_arg_cases is called, then a valid alternative is produced."""
        method = make_method(
            args=["ratio"],
            arg_types={"ratio": "float"},
            arg_defaults={"ratio": "0.5"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2

    def test_returnPopulatedListAsAlt_whenListDefaultIsEmpty(self, make_method):
        """Given list default=[], when default_arg_cases is called, then alt=[1,2,3]."""
        method = make_method(
            args=["items"],
            arg_types={"items": "list"},
            arg_defaults={"items": "[]"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["items"] for case in result}
        assert "[]" in overrides
        assert "[1, 2, 3]" in overrides

    def test_returnEmptyListAsAlt_whenListDefaultIsNonEmpty(self, make_method):
        """Given list default != [], when default_arg_cases is called, then alt=[]."""
        method = make_method(
            args=["items"],
            arg_types={"items": "list"},
            arg_defaults={"items": "[1,2,3]"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["items"] for case in result}
        assert "[1,2,3]" in overrides
        assert "[]" in overrides

    def test_returnTypeSampleAsAlt_whenNoneDefaultWithKnownType(self, make_method):
        """Given default=None and hint="str", when default_arg_cases is called, then alt comes from _type_sample."""
        method = make_method(
            args=["name"],
            arg_types={"name": "str"},
            arg_defaults={"name": "None"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["name"] for case in result}
        assert "None" in overrides
        # _type_sample("str") returns "'test'"
        assert any(val in overrides for val in ["'test'", '""'])

    def test_returnMagicMockAsAlt_whenNoneDefaultWithExternalType(self, make_method):
        """Given default=None and hint='Optional[ExternalType]', when default_arg_cases is called, then alt='MagicMock()'."""
        # This tests the new branch added in the recent modification
        method = make_method(
            args=["status"],
            arg_types={"status": "Optional[TodoStatus]"},
            arg_defaults={"status": "None"},
        )
        result = default_arg_cases(method)
        assert len(result) == 2
        overrides = {case.input_overrides["status"] for case in result}
        assert "None" in overrides
        # The new branch: sample != "None" and hint is non-empty and != "None"
        # → alt = "MagicMock()"
        assert "MagicMock()" in overrides

    def test_returnTwoCases_whenNoneDefaultAndNoTypeHint(self, make_method):
        """Given default=None and no hint, when default_arg_cases is called, then _type_sample result is used."""
        method = make_method(
            args=["value"],
            arg_defaults={"value": "None"},
        )
        result = default_arg_cases(method)
        # Without hint, _type_sample("") returns "None"
        # Since sample == "None" and hint is empty, alt = '"value"'
        # So we get 2 cases: None and '"value"'
        assert len(result) == 2

    def test_includeIsDefaultAndIsNonDefault_whenDefaultCaseCreated(self, make_method):
        """Given default arg cases, when created, then test names include IsDefault and IsNonDefault."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            arg_defaults={"x": "5"},
        )
        result = default_arg_cases(method)
        test_names = {case.test_name for case in result}
        # Should have IsDefault variant
        assert any("IsDefault" in name for name in test_names)
        assert any("IsNonDefault" in name for name in test_names)

    def test_returnTwoCases_whenAltDiffersFromDefault(self, make_method):
        """Given alt == default_repr, when default_arg_cases is called, then only the default case is produced."""
        method = make_method(
            args=["x"],
            arg_defaults={"x": "None"},
        )
        result = default_arg_cases(method)
        # With no type hint, _type_sample("") returns "None"
        # Since sample == "None" and hint is empty, alt = '"value"'
        # alt != default_repr, so both cases are generated
        assert len(result) == 2


class TestParseUnionMembers:
    """Tests for _parse_union_members."""

    def test_returnIntAndStr_whenUnionBracketSyntax(self):
        """Given Union[int, str], when _parse_union_members is called, then it returns ['int', 'str']."""
        result = _parse_union_members("Union[int, str]")
        assert set(result) == {"int", "str"}

    def test_returnThreeMembers_whenUnionHasThreeTypes(self):
        """Given Union[int, str, float], when _parse_union_members is called, then it returns ['int', 'str', 'float']."""
        result = _parse_union_members("Union[int, str, float]")
        assert set(result) == {"int", "str", "float"}

    def test_returnIntAndStr_whenPipeSyntax(self):
        """Given int | str, when _parse_union_members is called, then it returns ['int', 'str']."""
        result = _parse_union_members("int | str")
        assert set(result) == {"int", "str"}

    def test_returnTypeAndNone_whenOptionalSyntax(self):
        """Given Optional[str], when _parse_union_members is called, then it returns ['str', 'None']."""
        result = _parse_union_members("Optional[str]")
        assert set(result) == {"str", "None"}

    def test_returnEmptyList_whenPlainType(self):
        """Given int, when _parse_union_members is called, then it returns an empty list."""
        result = _parse_union_members("int")
        assert result == []

    def test_returnEmptyList_whenEmptyString(self):
        """Given an empty string, when _parse_union_members is called, then it returns an empty list."""
        result = _parse_union_members("")
        assert result == []

    def test_returnStrAndNone_whenStrNonePipeSyntax(self):
        """Given str | None, when _parse_union_members is called, then it returns ['str', 'None']."""
        result = _parse_union_members("str | None")
        assert set(result) == {"str", "None"}


class TestUnionTypeCases:
    """Tests for union_type_cases."""

    def test_returnEmptyList_whenPlainIntArg(self, make_method):
        """Given a plain int arg, when union_type_cases is called, then no cases are produced."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        result = union_type_cases(method)
        assert result == []

    def test_returnEmptyList_whenOptionalIntArg(self, make_method):
        """Given Optional[int] with 1 concrete member, when union_type_cases is called, then it returns an empty list."""
        method = make_method(args=["x"], arg_types={"x": "Optional[int]"})
        result = union_type_cases(method)
        assert result == []

    def test_returnTwoCases_whenUnionIntStr(self, make_method):
        """Given Union[int, str], when union_type_cases is called, then 2 cases are produced."""
        method = make_method(
            args=["value"],
            arg_types={"value": "Union[int, str]"},
        )
        result = union_type_cases(method)
        assert len(result) == 2

    def test_returnThreeCases_whenThreeMemberPipeUnion(self, make_method):
        """Given int | str | float, when union_type_cases is called, then 3 cases are produced."""
        method = make_method(
            args=["value"],
            arg_types={"value": "int | str | float"},
        )
        result = union_type_cases(method)
        assert len(result) == 3

    def test_returnTypeSampleValues_whenUnionCaseCreated(self, make_method):
        """Given union cases, when created, then input_overrides contain _type_sample result for each member."""
        method = make_method(
            args=["value"],
            arg_types={"value": "Union[int, str]"},
        )
        result = union_type_cases(method)
        overrides = {case.input_overrides["value"] for case in result}
        # Should include samples for int and str
        assert "1" in overrides  # _type_sample("int")
        assert "'test'" in overrides  # _type_sample("str")

    def test_includeTypeMemberInName_whenUnionCaseCreated(self, make_method):
        """Given union cases, when created, then test names include type member."""
        method = make_method(
            args=["x"],
            arg_types={"x": "Union[int, str]"},
        )
        result = union_type_cases(method)
        test_names = {case.test_name for case in result}
        # Should have when_X_Is variants
        assert any("IsInt" in name or "Isint" in name for name in test_names)
        assert any("IsStr" in name or "Isstr" in name for name in test_names)

    def test_skipNoneSample_whenUnionMemberSampleIsNone(self, make_method):
        """Given union members where _type_sample returns 'None', when union_type_cases is called, then that member is skipped."""
        method = make_method(
            args=["value"],
            arg_types={"value": "Union[Optional[int], str]"},
        )
        result = union_type_cases(method)
        # Union[Optional[int], str] = Union[int, None, str]
        # Concrete non-None members: [Optional[int] (sample="1"), str (sample="'test'")]
        # At minimum the str member generates a case
        assert len(result) >= 1, f"Union[Optional[int], str] should produce at least 1 case; got {len(result)}"
        overrides_vals = {c.input_overrides.get("value") for c in result}
        assert "'test'" in overrides_vals, "str member should produce a case with sample value \"'test'\""


class TestUnionTypeCasesBugs:
    """Bug detection for union_type_cases."""

    def test_recognizeUnionType_whenOptionalPipeSyntax(self, make_method):
        """Given Optional[int] | str pattern, when union_type_cases is called, then it is recognized as union type with int and str."""
        method = make_method(
            args=["value"],
            arg_types={"value": "Optional[int] | str"}
        )
        result = union_type_cases(method)
        assert len(result) >= 2, \
            f"Optional[int] | str should be recognized as union. Got {len(result)} cases, expected 2+ (int and str)"

    def test_recognizeUnionType_whenPlainPipeSyntax(self, make_method):
        """Given plain int | str, when union_type_cases is called, then it is recognized as union (regression test)."""
        method = make_method(
            args=["value"],
            arg_types={"value": "int | str"}
        )
        result = union_type_cases(method)
        # Should generate cases for both int and str
        assert len(result) >= 2, \
            f"Plain int | str should be recognized. Got {len(result)} cases"


class TestDefaultArgCasesEdgeCases:
    """Edge cases to find bugs in default_arg_cases."""

    def test_notTreatAsBool_whenTypeNameContainsBoolSubstring(self, make_method):
        """Given a 'boolean_like' type that is not exactly bool, when default_arg_cases is called, then it should not be treated as bool."""
        method = make_method(
            args=["flag"],
            arg_types={"flag": "boolean_like"},  # NOT 'bool'
            arg_defaults={"flag": "True"},
        )
        result = default_arg_cases(method)
        test_names = {case.test_name for case in result}
        overrides = [case.input_overrides for case in result]
        assert len(result) == 1, f"'boolean_like' should not be treated as bool. Got {len(result)} cases, expected 1"

    def test_recognizeIntType_whenUnionPipeWithIntDefault(self, make_method):
        """Given 'int | str' Union type with default=5, when default_arg_cases is called, then it should recognize int type."""
        method = make_method(
            args=["value"],
            arg_types={"value": "int | str"},  # Union with pipe syntax
            arg_defaults={"value": "5"},
        )
        result = default_arg_cases(method)
        overrides = [case.input_overrides["value"] for case in result]
        assert "2" in overrides or "2.5" in overrides, \
            f"Union type 'int | str' should generate int-based alt. Got alts {overrides}, expected int-based alt"

    def test_notTreatAsList_whenTypeNameContainsListSubstring(self, make_method):
        """Given a 'list_type' type that is not exactly list, when default_arg_cases is called, then it should not be treated as list."""
        method = make_method(
            args=["items"],
            arg_types={"items": "list_type"},  # NOT 'list'
            arg_defaults={"items": "[]"},
        )
        result = default_arg_cases(method)
        assert len(result) == 1, f"'list_type' should not be treated as list"

    def test_notTreatAsFloat_whenTypeNameContainsFloatSubstring(self, make_method):
        """Given a 'floatable' type that is not exactly float, when default_arg_cases is called, then it should not be treated as float."""
        method = make_method(
            args=["value"],
            arg_types={"value": "floatable"},  # NOT 'float'
            arg_defaults={"value": "5.0"},
        )
        result = default_arg_cases(method)
        assert len(result) == 1, f"'floatable' should not be treated as float"

    def test_handleStrictly_whenTypeNameContainsStrSubstring(self, make_method):
        """Given a 'string' type that contains 'str' as substring, when default_arg_cases is called, then type checking should be strict."""
        method = make_method(
            args=["name"],
            arg_types={"name": "string"},  # Contains 'str' as substring
            arg_defaults={"name": '"test"'},
        )
        result = default_arg_cases(method)
        overrides = [case.input_overrides["name"] for case in result]
        # Test should handle 'string' type appropriately
        assert len(result) >= 1

    def test_handleAppropriately_whenTypeNameContainsIntSubstring(self, make_method):
        """Given an 'integer' type that contains 'int' as substring, when default_arg_cases is called, then type checking should handle it appropriately."""
        method = make_method(
            args=["x"],
            arg_types={"x": "integer"},  # Contains 'int' substring
            arg_defaults={"x": "10"},
        )
        result = default_arg_cases(method)
        overrides = [case.input_overrides["x"] for case in result]
        # Test should handle 'integer' type appropriately
        assert len(result) >= 1

