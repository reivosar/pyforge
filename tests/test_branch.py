"""Tests for pyforge.cases.branch module."""
import ast

import pytest

from pyforge.models import MethodInfo
from pyforge.cases.branch import (
    _attr_to_name,
    _boundary_cases_from_condition,
    _camel,
    _condition_to_inputs,
    _condition_to_name,
    _numeric_const,
    _truncate_test_name,
    analyze_method_branches,
)


class TestCamel:
    """Tests for _camel."""

    def test_returnCapitalizedUser_whenSingleWord(self):
        """Given 'user', when _camel is called, then it returns 'User'."""
        assert _camel("user") == "User"

    def test_returnCapitalizedWithId_whenSnakeCase(self):
        """Given 'user_id', when _camel is called, then it returns 'UserId'."""
        assert _camel("user_id") == "UserId"

    def test_returnCapitalizedWithAllWords_whenMultipleWords(self):
        """Given 'some_method_name', when _camel is called, then it returns 'SomeMethodName'."""
        assert _camel("some_method_name") == "SomeMethodName"

    def test_returnEmptyString_whenInputEmpty(self):
        """Given an empty string, when _camel is called, then it returns an empty string."""
        assert _camel("") == ""

    def test_returnCamelCaseWithoutUnderscores_whenLeadingTrailingUnderscores(self):
        """Given a string with leading and trailing underscores, when _camel is called, then it returns the camelcased string without underscores."""
        assert _camel("_foo_") == "Foo"

    def test_returnCapitalizedWithAllWords_whenSpaceSeparated(self):
        """Given a space-separated string, when _camel is called, then it returns the camelcased version."""
        assert _camel("hello world") == "HelloWorld"


class TestNumericConst:
    """Tests for _numeric_const."""

    def test_returnIntValue_whenPositiveIntegerConstant(self):
        """Given a Constant node with a positive integer, when _numeric_const is called, then it returns the integer value."""
        node = ast.Constant(42)
        assert _numeric_const(node) == 42

    def test_returnFloatValue_whenFloatConstant(self):
        """Given a Constant node with a float, when _numeric_const is called, then it returns the float value."""
        node = ast.Constant(3.14)
        assert _numeric_const(node) == 3.14

    def test_returnNegatedValue_whenUnaryMinusApplied(self):
        """Given a UnaryOp node with unary minus on a negative constant, when _numeric_const is called, then it returns the negated value."""
        const_node = ast.Constant(-5)
        node = ast.UnaryOp(ast.USub(), const_node)
        result = _numeric_const(node)
        assert result == 5

    def test_returnNone_whenNodeIsNonNumericName(self):
        """Given a Name node, when _numeric_const is called, then it returns None."""
        node = ast.Name("x", ast.Load())
        assert _numeric_const(node) is None

    def test_returnNone_whenStringConstant(self):
        """Given a Constant node with a string value, when _numeric_const is called, then it returns None."""
        node = ast.Constant("hello")
        assert _numeric_const(node) is None


class TestTruncateTestName:
    """Tests for _truncate_test_name."""

    def test_returnSameString_whenLengthIsExactly80(self):
        """Given an 80-character string, when _truncate_test_name is called, then it returns the string unchanged."""
        name = "x" * 80
        assert _truncate_test_name(name) == name

    def test_returnSameString_whenLengthUnder80(self):
        """Given a short string, when _truncate_test_name is called, then it returns the string unchanged."""
        name = "test_name"
        assert _truncate_test_name(name) == name

    def test_returnTruncatedString_whenOver80AndContainsWhen(self):
        """Given a long name containing '_when', when _truncate_test_name is called, then it returns a truncated string with length <= 80."""
        name = "raiseValueError_when" + "x" * 100
        result = _truncate_test_name(name)
        assert len(result) <= 80

    def test_returnTruncatedString_whenOver80WithoutWhen(self):
        """Given a long string without '_when', when _truncate_test_name is called, then it returns a truncated string with length <= 80."""
        name = "x" * 100
        result = _truncate_test_name(name)
        assert len(result) <= 80

    def test_preserveMinimumSuffix_whenTruncatingWithWhen(self):
        """Given a very long name with '_when', when _truncate_test_name is called, then it preserves at least 8 characters after '_when'."""
        name = "x" * 100 + "_when" + "y" * 50
        result = _truncate_test_name(name)
        parts = result.split("_when")
        if len(parts) == 2:
            assert len(parts[1]) >= 8


class TestAttrToName:
    """Tests for _attr_to_name."""

    def test_returnAttributeChainWithoutSelfPrefix_whenChainedAccess(self):
        """Given a chained attribute access, when _attr_to_name is called, then it returns the attribute names without the self prefix."""
        source = "self.x.y"
        node = ast.parse(source, mode="eval").body
        result = _attr_to_name(node)
        assert "x" in result and "y" in result
        assert not result.startswith("self_")

    def test_returnSameName_whenBareName(self):
        """Given a bare name, when _attr_to_name is called, then it returns the name unchanged."""
        source = "x"
        node = ast.parse(source, mode="eval").body
        result = _attr_to_name(node)
        assert result == "x"


class TestConditionToName:
    """Tests for _condition_to_name."""

    def test_returnNameContainingPositive_whenGreaterThanZero(self):
        """Given a greater-than-zero comparison, when _condition_to_name is called, then it returns a name containing 'Positive'."""
        source = "x > 0"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Positive" in result

    def test_returnNameContainingNegative_whenLessThanZero(self):
        """Given a less-than-zero comparison, when _condition_to_name is called, then it returns a name containing 'Negative'."""
        source = "x < 0"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Negative" in result

    def test_returnNameContainingZeroOrNegative_whenLessThanOrEqualZero(self):
        """Given a less-than-or-equal-to-zero comparison, when _condition_to_name is called, then it returns a name containing 'Zero' or 'Negative'."""
        source = "x <= 0"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Zero" in result or "Negative" in result

    def test_returnNameContainingZeroOrPositive_whenGreaterThanOrEqualZero(self):
        """Given a greater-than-or-equal-to-zero comparison, when _condition_to_name is called, then it returns a name containing 'Zero' or 'Positive'."""
        source = "x >= 0"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Zero" in result or "Positive" in result

    def test_returnNameContainingEmpty_whenEqualityToEmptyString(self):
        """Given an equality comparison to an empty string, when _condition_to_name is called, then it returns a name containing 'Empty'."""
        source = 'x == ""'
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Empty" in result

    def test_returnNameContainingIsNone_whenIsNoneComparison(self):
        """Given an 'is None' comparison, when _condition_to_name is called, then it returns a name containing 'IsNone'."""
        source = "x is None"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "IsNone" in result

    def test_returnNameContainingIsNotNone_whenIsNotNoneComparison(self):
        """Given an 'is not None' comparison, when _condition_to_name is called, then it returns a name containing 'IsNotNone'."""
        source = "x is not None"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "IsNotNone" in result

    def test_returnNameContainingIn_whenInMembershipTest(self):
        """Given an 'in' membership test, when _condition_to_name is called, then it returns a name containing 'In'."""
        source = "x in [1, 2, 3]"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "In" in result

    def test_returnNameContainingNotIn_whenNotInMembershipTest(self):
        """Given a 'not in' membership test, when _condition_to_name is called, then it returns a name containing 'NotIn'."""
        source = "x not in valid"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "NotIn" in result

    def test_returnNameContainingStrType_whenIsinstanceCheckForStr(self):
        """Given an isinstance check for str type, when _condition_to_name is called, then it returns a name containing 'Str'."""
        source = "isinstance(val, str)"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Str" in result or "str" in result

    def test_returnNameContainingAnd_whenBooleanAND(self):
        """Given a boolean AND condition, when _condition_to_name is called, then it returns a name containing 'And'."""
        source = "x > 0 and y is None"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "And" in result

    def test_returnNameContainingOr_whenBooleanOR(self):
        """Given a boolean OR condition, when _condition_to_name is called, then it returns a name containing 'Or'."""
        source = "x > 0 or y is None"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Or" in result

    def test_returnNameReferencingVariable_whenLengthComparison(self):
        """Given a length comparison, when _condition_to_name is called, then it returns a name referencing the variable."""
        source = "len(title) > 100"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "title" in result.lower() or "Title" in result


class TestConditionToInputs:
    """Tests for _condition_to_inputs."""

    def test_returnXMappedToOne_whenGreaterThanZero(self):
        """Given a greater-than-zero condition, when _condition_to_inputs is called, then it returns x mapped to 1."""
        source = "x > 0"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {"x": "int"})
        assert result["x"] == "1"

    def test_returnXMappedToMinusOne_whenLessThanZero(self):
        """Given a less-than-zero condition, when _condition_to_inputs is called, then it returns x mapped to -1."""
        source = "x < 0"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {"x": "int"})
        assert result["x"] == "-1"

    def test_returnXMappedToNone_whenIsNoneCondition(self):
        """Given an 'is None' condition, when _condition_to_inputs is called, then it returns x mapped to None."""
        source = "x is None"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {})
        assert result["x"] == "None"

    def test_returnXMappedToFirstElement_whenInMembershipCondition(self):
        """Given an 'in' membership condition, when _condition_to_inputs is called, then it returns x mapped to the first list element."""
        source = "x in [1, 2, 3]"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {})
        assert "x" in result
        assert "1" in result["x"]

    def test_returnXMappedToSentinelInt_whenNotInMembershipCondition(self):
        """Given a 'not in' membership condition with int type, when _condition_to_inputs is called, then it returns a sentinel value."""
        source = "x not in [1, 2]"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {"x": "int"})
        assert "x" in result
        assert result["x"] == "-99999"

    def test_returnValMappedToQuotedString_whenIsinstanceCheckForStr(self):
        """Given an isinstance check for str type, when _condition_to_inputs is called, then it returns a string value with quotes."""
        source = "isinstance(val, str)"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {"val": "str"})
        assert "val" in result
        assert "'" in result["val"]

    def test_returnXMappedToMidpoint_whenChainedRangeCondition(self):
        """Given a chained range condition, when _condition_to_inputs is called, then it returns x mapped to the midpoint value."""
        source = "0 < x < 10"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {"x": "int"})
        assert result["x"] == "5"

    def test_returnMappingsForAllVariables_whenBooleanAND(self):
        """Given a boolean AND condition, when _condition_to_inputs is called, then it returns mappings for all variables."""
        source = "x > 0 and y is None"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_inputs(node, {"x": "int"})
        assert "x" in result
        assert "y" in result


class TestBoundaryCasesFromCondition:
    """Tests for _boundary_cases_from_condition."""

    def test_returnBoundaryCases_whenGreaterThanCondition(self):
        """Given a greater-than boundary condition, when _boundary_cases_from_condition is called, then it returns boundary test cases."""
        source = "x > 5"
        node = ast.parse(source, mode="eval").body
        result = _boundary_cases_from_condition(node, {"x": "int"}, "ValueError")
        assert len(result) > 0

    def test_returnEmptyList_whenRightSideIsNonNumeric(self):
        """Given a comparison with a non-constant right side, when _boundary_cases_from_condition is called, then it returns an empty list."""
        source = "x > y"
        node = ast.parse(source, mode="eval").body
        result = _boundary_cases_from_condition(node, {}, "ValueError")
        assert result == []

    def test_returnEmptyList_whenNodeIsNotComparison(self):
        """Given a boolean operation instead of a comparison, when _boundary_cases_from_condition is called, then it returns an empty list."""
        source = "x > 0 or y < 5"
        node = ast.parse(source, mode="eval").body
        result = _boundary_cases_from_condition(node, {}, "ValueError")
        assert result == []


class TestAnalyzeMethodBranches:
    """Tests for analyze_method_branches."""

    def test_returnHappyPathOnly_whenAstNodeIsNone(self, make_method):
        """Given a method with no AST node, when analyze_method_branches is called, then it returns a single happy-path case."""
        method = make_method(name="foo", ast_node=None)
        result = analyze_method_branches(method)
        assert len(result) == 1
        assert result[0].is_happy_path is True

    def test_returnExceptionAndHappyPathCases_whenConditionalRaiseExists(self, make_method):
        """Given a method with a conditional raise statement, when analyze_method_branches is called, then it returns an exception case and a happy-path case."""
        source = """
def foo(x):
    if x < 0:
        raise ValueError("negative")
    return x
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        method = make_method(name="foo", args=["x"], arg_types={"x": "int"}, ast_node=fn_node)
        result = analyze_method_branches(method)
        exception_cases = [c for c in result if c.expected_exception]
        assert len(exception_cases) > 0
        assert any(c.is_happy_path for c in result)

    def test_returnEarlyReturnAndHappyPathCases_whenReturnInsideIf(self, make_method):
        """Given a method with an early return statement, when analyze_method_branches is called, then it returns both an early return case and a happy-path case."""
        source = """
def foo(x):
    if x == 0:
        return None
    return x * 2
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        method = make_method(name="foo", args=["x"], arg_types={"x": "int"}, ast_node=fn_node)
        result = analyze_method_branches(method)
        assert len(result) >= 2

    def test_alwaysReturnHappyPathCase_whenBranchesExist(self, make_method):
        """Given a method with conditional branches, when analyze_method_branches is called, then it always includes a happy-path case."""
        source = """
def foo(x):
    if x < 0:
        raise ValueError()
    return x
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        method = make_method(name="foo", args=["x"], arg_types={"x": "int"}, ast_node=fn_node)
        result = analyze_method_branches(method)
        assert len(result) > 0
        assert any(c.is_happy_path for c in result)


class TestConditionToInputsSubstringBugs:
    """Bugs in _condition_to_inputs from substring type matching."""

    def test_doNotMatchStringTypeIncorrectly_whenCustomStringType(self):
        """Given a custom 'string' type, when _condition_to_inputs is called, then it does not incorrectly match 'str'."""
        source = "x not in [1, 2, 3]"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "string"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") != '"__not_in_value__"'

    def test_doNotMatchIntTypeIncorrectly_whenCustomIntegerType(self):
        """Given a custom 'integer' type, when _condition_to_inputs is called, then it does not incorrectly match 'int'."""
        source = "x not in valid"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "integer"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") != "-99999"

    def test_doNotMatchListTypeIncorrectly_whenCustomMylistType(self):
        """Given a custom 'mylist' type, when _condition_to_inputs is called, then it does not incorrectly match 'list'."""
        source = "not items"
        node = ast.parse(source, mode="eval").body
        arg_types = {"items": "mylist"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("items") != "[]"

    def test_doNotMatchDictTypeIncorrectly_whenCustomDictionaryType(self):
        """Given a custom 'dictionary' type, when _condition_to_inputs is called, then it does not incorrectly match 'dict'."""
        source = "not data"
        node = ast.parse(source, mode="eval").body
        arg_types = {"data": "dictionary"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("data") != "{}"

    def test_doNotMatchBoolTypeIncorrectly_whenCustomBooleanLikeType(self):
        """Given a custom 'boolean_like' type, when _condition_to_inputs is called, then it does not incorrectly match 'bool'."""
        source = "x not in [True, False]"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "boolean_like"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") != "-99999", "'boolean_like' must not match int sentinel (-99999)"
        assert result.get("x") != '"__not_in_value__"', "'boolean_like' must not match str sentinel"



class TestCriticalBugs:
    """Critical bugs found by deep analysis of branch.py."""

    def test_generateCorrectExceptionCases_whenChainedComparisonBoundary(self):
        """Given a chained comparison with boundary values, when _boundary_cases_from_condition is called, then it generates correct exception cases."""
        source = "0 < x < 10"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _boundary_cases_from_condition(node, arg_types, "ValueError")

        case_at_0 = next((c for c in result if c.input_overrides.get("x") == "0"), None)

        assert case_at_0 is not None
        assert case_at_0.expected_exception is None

    def test_doNotGenerateEmptyTestNames_whenAstNodeIsNone(self):
        """Given a method with no AST node, when analyze_method_branches is called, then it does not generate empty test names."""
        from pyforge.cases.branch import analyze_method_branches
        method = MethodInfo(
            name="foo",
            args=["x"],
            arg_types={"x": "int"},
            return_type=None,
            is_void=True,
            is_public=True,
        )
        result = analyze_method_branches(method)

        empty_name_cases = [c for c in result if c.test_name == ""]
        assert len(empty_name_cases) == 0

    def test_generateBoundaryCases_whenLengthEqualityCheckZero(self):
        """Given a length equality check with zero, when _boundary_cases_from_condition is called, then it generates boundary test cases."""
        source = "len(title) == 0"
        node = ast.parse(source, mode="eval").body
        arg_types = {"title": "str"}
        result = _boundary_cases_from_condition(node, arg_types, "ValueError")
        assert len(result) > 0

    def test_generateInnerBoundaryCases_whenChainedComparison(self):
        """Given a chained comparison, when _boundary_cases_from_condition is called, then it generates cases for inner boundary values."""
        source = "0 < x < 10"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _boundary_cases_from_condition(node, arg_types, "ValueError")

        inner_cases = [c for c in result if c.input_overrides.get("x") in ("1", "9")]
        assert len(inner_cases) > 0

    def test_generateCorrectExceptionCases_whenGreaterThanOrEqualZero(self):
        """Given a greater-than-or-equal-to-zero boundary, when _boundary_cases_from_condition is called, then it generates correct exception cases for boundary values."""
        source = "x >= 0"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _boundary_cases_from_condition(node, arg_types, "ValueError")

        case_minus1 = next((c for c in result if c.input_overrides.get("x") == "-1"), None)
        case_0 = next((c for c in result if c.input_overrides.get("x") == "0"), None)

        assert case_minus1 is not None
        assert case_minus1.expected_exception is None

        assert case_0 is not None
        assert case_0.expected_exception == "ValueError"


class TestConditionToNameChainedComparisons:
    """Tests for _condition_to_name with chained comparisons."""

    def test_returnNameContainingBetween_whenNonNumericLeftSide(self):
        """Given a chained comparison with non-numeric left side, when _condition_to_name is called, then it generates a descriptive name."""
        source = "a < x < b"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Between" in result

    def test_returnValidName_whenNonNumericRightSide(self):
        """Given a chained comparison with non-numeric right side, when _condition_to_name is called, then it generates a valid name."""
        source = "0 < x < max_val"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "Between" in result or "X" in result


class TestConditionToInputsComparisonPatterns:
    """Tests for _condition_to_inputs simple comparison patterns."""

    def test_returnThresholdValue_whenGreaterThanOrEqualComparison(self):
        """Given a greater-than-or-equal comparison, when _condition_to_inputs is called, then it sets the variable to the threshold value."""
        source = "x >= 10"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") in ("10", "10.0")

    def test_returnThresholdMinusOne_whenLessThanComparison(self):
        """Given a less-than comparison, when _condition_to_inputs is called, then it sets the variable to threshold minus one."""
        source = "x < 10"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") in ("9", "9.0")

    def test_returnThresholdValue_whenLessThanOrEqualComparison(self):
        """Given a less-than-or-equal comparison, when _condition_to_inputs is called, then it sets the variable to the threshold value."""
        source = "x <= 10"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "int"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") in ("10", "10.0")


class TestConditionToNameNotChained:
    """Tests for _condition_to_name with 'not' operator on chained comparison."""

    def test_returnNameContainingOutOfRange_whenNegatedChainedComparison(self):
        """Given a negated chained comparison, when _condition_to_name is called, then it generates an OutOfRange name."""
        source = "not (0 < x < 10)"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "OutOfRange" in result or "False" in result

    def test_returnNameContainingTooLong_whenLengthComparisonGreaterThan(self):
        """Given a length comparison for too-long string, when _condition_to_name is called, then it generates a TooLong name."""
        source = "len(name) > 5"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "TooLong" in result

    def test_returnNameContainingTooShort_whenLengthComparisonLessThan(self):
        """Given a length comparison for too-short string, when _condition_to_name is called, then it generates a TooShort name."""
        source = "len(name) < 5"
        node = ast.parse(source, mode="eval").body
        result = _condition_to_name(node)
        assert "TooShort" in result


class TestAdditionalSubstringBugs:
    """More substring matching bugs in _condition_to_inputs and _boundary_cases_from_condition."""

    def test_doNotMatchStringInNotInCondition_whenCustomStringType(self):
        """Given a custom 'string' type in not-in condition, when _condition_to_inputs is called, then it does not match 'str'."""
        source = "x not in ['a', 'b']"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "string"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") != '"__not_in_value__"'

    def test_doNotMatchIntInNotInCondition_whenCustomIntegerType(self):
        """Given a custom 'integer' type in not-in condition, when _condition_to_inputs is called, then it does not match 'int'."""
        source = "x not in [1, 2]"
        node = ast.parse(source, mode="eval").body
        arg_types = {"x": "integer"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("x") != "-99999"

    def test_doNotMatchListInNotCondition_whenCustomMylistType(self):
        """Given a custom 'mylist' type in not condition, when _condition_to_inputs is called, then it does not match 'list'."""
        source = "not items"
        node = ast.parse(source, mode="eval").body
        arg_types = {"items": "mylist"}
        result = _condition_to_inputs(node, arg_types)
        assert result.get("items") != "[]"

    def test_generateBoundaryCase_whenLengthBoundaryWithCustomStringType(self):
        """'string' type must NOT be treated as str — boundary values must use list form, not string form."""
        source = "len(title) > 10"
        node = ast.parse(source, mode="eval").body
        arg_types = {"title": "string"}
        result = _boundary_cases_from_condition(node, arg_types, "ValueError")
        assert len(result) > 0
        # "string" is an UnknownType, not BaseType("str") — must produce list-based values
        for case in result:
            val = next(iter(case.input_overrides.values()), "")
            assert '"a"' not in val, (
                f"'string' type must not be treated as str; got string-based value '{val}'"
            )


class TestCoveragePathBugs:
    """Bugs in coverage.py and utility functions."""

    def test_resolveCorrectTestPath_whenMultipleTestDirectories(self):
        """Given multiple test directories, when resolve_test_path is called, then it resolves to a test path with the correct test name."""
        from pyforge.coverage import resolve_test_path
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "tests" / "unit").mkdir(parents=True, exist_ok=True)
            (tmp_path / "tests" / "integration").mkdir(parents=True, exist_ok=True)
            (tmp_path / "deep" / "nested" / "tests").mkdir(parents=True, exist_ok=True)

            (tmp_path / "tests" / "unit" / "test_utils.py").touch()
            (tmp_path / "tests" / "integration" / "test_api.py").touch()
            (tmp_path / "deep" / "nested" / "tests" / "test_other.py").touch()

            target = tmp_path / "module.py"
            target.touch()

            result = resolve_test_path(target, tmp_path, integration=False)
            assert result.name == "test_module.py"

