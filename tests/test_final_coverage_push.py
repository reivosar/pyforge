"""Final push tests to reach 90% coverage."""
import ast
from pyforge.cases.branch import (
    _condition_to_inputs,
    _boundary_cases_from_condition,
    _condition_to_name,
    _numeric_const,
    _arg_name_from_node,
)


def test_returnBoundaryCases_whenLenLessThanCondition():
    """Test len(x) < N boundary cases."""
    source = "len(items) < 5"
    node = ast.parse(source, mode="eval").body
    arg_types = {"items": "list"}
    result = _boundary_cases_from_condition(node, arg_types, "ValueError")
    assert len(result) > 0


def test_returnBoundaryCases_whenLenLessOrEqualCondition():
    """Test len(x) <= N boundary cases."""
    source = "len(items) <= 5"
    node = ast.parse(source, mode="eval").body
    arg_types = {"items": "list"}
    result = _boundary_cases_from_condition(node, arg_types, "ValueError")
    assert len(result) > 0


def test_returnEmptyString_whenEmptyStringComparison():
    """Test _condition_to_inputs with empty string comparison."""
    source = 'name == ""'
    node = ast.parse(source, mode="eval").body
    arg_types = {"name": "str"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("name") == '""'


def test_returnNegativeOne_whenLessThanZeroComparison():
    """Test _condition_to_inputs with zero comparisons."""
    source = "x < 0"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("x") == "-1"


def test_returnOnePlusThreshold_whenGreaterThanComparison():
    """Test _condition_to_inputs with > comparison."""
    source = "x > 10"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("x") == "11"


def test_returnThresholdValue_whenGreaterThanOrEqualComparison():
    """Test _condition_to_inputs with >= comparison."""
    source = "x >= 10"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("x") == "10"


def test_returnThresholdValue_whenLessThanOrEqualComparison():
    """Test _condition_to_inputs with <= comparison."""
    source = "x <= 10"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("x") == "10"


def test_returnNegativeOne_whenLessThanZeroCondition():
    """Test _condition_to_inputs with < 0."""
    source = "x < 0"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("x") == "-1"


def test_returnNegativeOne_whenLessThanOrEqualZeroCondition():
    """Test _condition_to_inputs with <= 0."""
    source = "x <= 0"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("x") == "-1"


def test_returnEmptyList_whenNotEmptyListCondition():
    """Test _condition_to_inputs with not empty list condition."""
    source = "not items"
    node = ast.parse(source, mode="eval").body
    arg_types = {"items": "list"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("items") == "[]"


def test_returnEmptyString_whenNotEmptyStringCondition():
    """Test _condition_to_inputs with not empty string condition."""
    source = "not name"
    node = ast.parse(source, mode="eval").body
    arg_types = {"name": "str"}
    result = _condition_to_inputs(node, arg_types)
    assert result.get("name") == '""'


def test_returnNumericValue_whenNumericNodeParsed():
    """Test _numeric_const function."""
    # Test extracting a numeric constant
    node = ast.parse("5", mode="eval").body
    result = _numeric_const(node)
    assert result == 5

    # Test with float
    node = ast.parse("3.14", mode="eval").body
    result = _numeric_const(node)
    assert result == 3.14


def test_returnArgName_whenSimpleNameNode():
    """Test _arg_name_from_node with simple name."""
    node = ast.parse("x", mode="eval").body
    result = _arg_name_from_node(node)
    assert result == "x"


def test_includeVarAndThreshold_whenSimpleComparisonCondition():
    """Test _condition_to_name with simple comparison: x > 5 → 'XIsGt5'."""
    source = "x > 5"
    node = ast.parse(source, mode="eval").body
    result = _condition_to_name(node)
    assert "X" in result, f"Variable name 'X' expected in result, got '{result}'"
    assert "5" in result, f"Threshold '5' expected in result, got '{result}'"


def test_includeAnd_whenBooleanAndCondition():
    """Test _condition_to_name with boolean AND: must contain 'And'."""
    source = "x > 5 and y < 10"
    node = ast.parse(source, mode="eval").body
    result = _condition_to_name(node)
    assert "And" in result, f"Boolean AND condition must produce 'And' in name, got '{result}'"


def test_includeFalseOrVarName_whenNotCondition():
    """Test _condition_to_name with not: must reference the negated variable."""
    source = "not x"
    node = ast.parse(source, mode="eval").body
    result = _condition_to_name(node)
    assert len(result) > 0, "_condition_to_name must return a non-empty string for 'not x'"
    assert "False" in result or "X" in result, (
        f"'not x' must produce a name referencing 'False' or 'X', got '{result}'"
    )


def test_returnNone_whenInEmptyTupleCondition():
    """Test _condition_to_inputs with empty tuple: no element to pick, x key absent or None."""
    source = "x in ()"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int"}
    result = _condition_to_inputs(node, arg_types)
    assert isinstance(result, dict), "_condition_to_inputs must return a dict"
    # With empty tuple there is no element to pick, so x should not be set
    assert result.get("x") is None, (
        f"'x in ()' has no elements; x should not have a value, got '{result.get('x')}'"
    )


def test_returnEmptyList_whenRightSideIsNonConstant():
    """Test boundary cases when right value is not a constant: must return empty list."""
    source = "x > y"
    node = ast.parse(source, mode="eval").body
    arg_types = {"x": "int", "y": "int"}
    result = _boundary_cases_from_condition(node, arg_types, "ValueError")
    assert result == [], (
        f"Non-constant right side must produce no boundary cases, got {len(result)} cases"
    )
