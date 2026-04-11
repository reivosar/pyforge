"""Tests to improve analyze_method_branches coverage."""
import ast
from pyforge.cases.branch import analyze_method_branches
from pyforge.models import MethodInfo


def test_returnBranchCasesIncludingEarlyReturn_whenEarlyReturnExists():
    """Test analyze_method_branches with early return."""
    source = """
def check(x):
    if x < 0:
        return False
    return True
"""
    tree = ast.parse(source)
    func_node = tree.body[0]
    
    method = MethodInfo(
        name="check",
        args=["x"],
        arg_types={"x": "int"},
        return_type="bool",
        is_void=False,
        is_public=True,
        ast_node=func_node,
    )
    result = analyze_method_branches(method)
    assert len(result) > 0
    # Should have both the early return case and happy path
    assert any(c.expected_return == "False" for c in result if not c.is_happy_path)


def test_returnMultipleExceptionCases_whenMultipleRaisesExist():
    """Test analyze_method_branches with multiple raise statements."""
    source = """
def process(x, y):
    if x < 0:
        raise ValueError("x negative")
    if y < 0:
        raise ValueError("y negative")
    return x + y
"""
    tree = ast.parse(source)
    func_node = tree.body[0]
    
    method = MethodInfo(
        name="process",
        args=["x", "y"],
        arg_types={"x": "int", "y": "int"},
        return_type="int",
        is_void=False,
        is_public=True,
        ast_node=func_node,
    )
    result = analyze_method_branches(method)
    # Should have cases for both ValueError raises and happy path
    assert len(result) >= 3
    exception_cases = [c for c in result if c.expected_exception == "ValueError"]
    assert len(exception_cases) >= 2


def test_returnCases_whenExceptHandlerExists():
    """Test analyze_method_branches with except handler."""
    source = """
def safe_divide(x, y):
    try:
        return x / y
    except ZeroDivisionError:
        raise ValueError("Cannot divide by zero")
"""
    tree = ast.parse(source)
    func_node = tree.body[0]
    
    method = MethodInfo(
        name="safe_divide",
        args=["x", "y"],
        arg_types={"x": "int", "y": "int"},
        return_type="float",
        is_void=False,
        is_public=True,
        ast_node=func_node,
    )
    result = analyze_method_branches(method)
    assert len(result) > 0


def test_returnAtLeastOneCase_whenLoopExists():
    """Test analyze_method_branches with loop."""
    source = """
def sum_list(items):
    total = 0
    for item in items:
        total += item
    return total
"""
    tree = ast.parse(source)
    func_node = tree.body[0]
    
    method = MethodInfo(
        name="sum_list",
        args=["items"],
        arg_types={"items": "list"},
        return_type="int",
        is_void=False,
        is_public=True,
        ast_node=func_node,
    )
    result = analyze_method_branches(method)
    assert len(result) > 0


def test_returnExceptionCases_whenComplexBooleanCondition():
    """Test analyze_method_branches with complex condition."""
    source = """
def validate(name, age, score):
    if not name or age < 0 or score > 100:
        raise ValueError("Invalid input")
    return True
"""
    tree = ast.parse(source)
    func_node = tree.body[0]
    
    method = MethodInfo(
        name="validate",
        args=["name", "age", "score"],
        arg_types={"name": "str", "age": "int", "score": "int"},
        return_type="bool",
        is_void=False,
        is_public=True,
        ast_node=func_node,
    )
    result = analyze_method_branches(method)
    # Should generate cases for the error condition
    exception_cases = [c for c in result if c.expected_exception is not None]
    assert len(exception_cases) > 0
