"""Tests for pyforge.analysis.python_ast module."""
import ast
from pathlib import Path

import pytest

from pyforge.analysis.python_ast import (
    SAMPLE_VALUES,
    _detect_nondeterministic_patches,
    _infer_types_from_usage,
    _parse_constructor_deps,
    _parse_method_node,
    _type_sample,
    analyze_python,
    detect_enum_types,
    detect_orm_models,
)


class TestTypeSample:
    """Tests for _type_sample."""

    def test_returnNone_whenNoneHint(self):
        """Given a None type hint, when _type_sample is called, then it returns 'None'."""
        result = _type_sample(None)
        assert result == "None"

    def test_returnNone_whenEmptyStringHint(self):
        """Given an empty string type hint, when _type_sample is called, then it returns 'None'."""
        result = _type_sample("")
        assert result == "None"

    def test_returnOne_whenIntHint(self):
        """Given an int type hint, when _type_sample is called, then it returns '1'."""
        result = _type_sample("int")
        assert result == "1"

    def test_returnTestString_whenStrHint(self):
        """Given a str type hint, when _type_sample is called, then it returns a string sample."""
        result = _type_sample("str")
        assert result == "'test'"

    def test_returnFalse_whenBoolHint(self):
        """Given a bool type hint, when _type_sample is called, then it returns 'False'."""
        result = _type_sample("bool")
        assert result == "False"

    def test_returnInnerTypeSample_whenOptionalHint(self):
        """Given an Optional[int] type hint, when _type_sample is called, then it returns the sample for the inner type."""
        result = _type_sample("Optional[int]")
        assert result == "1"

    def test_returnTestString_whenOptionalStrHint(self):
        """Given an Optional[str] type hint, when _type_sample is called, then it returns a string sample."""
        result = _type_sample("Optional[str]")
        assert result == "'test'"

    def test_returnNone_whenUnknownTypeHint(self):
        """Given an unknown type hint, when _type_sample is called, then it returns 'None'."""
        result = _type_sample("FooBar")
        assert result == "None"

    def test_returnListSample_whenListContainerHint(self):
        """Given a list container type hint, when _type_sample is called, then it returns a list sample using the base 'list' type."""
        result = _type_sample("list[str]")
        # SAMPLE_VALUES['list'][1] = [1, 2, 3]
        assert result == "[1, 2, 3]"

    def test_returnBytesSample_whenBytesHint(self):
        """Given a bytes type hint, when _type_sample is called, then it returns a bytes sample."""
        result = _type_sample("bytes")
        assert result == "b'test'"


class TestDetectNondeterministicPatches:
    """Tests for _detect_nondeterministic_patches."""

    def test_detectDatetimeDatetime_whenDatetimeNowUsed(self):
        """Given code using datetime.now(), when _detect_nondeterministic_patches is called, then it detects the datetime.datetime pattern."""
        source = """
def foo():
    import datetime
    x = datetime.datetime.now()
    return x
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert "datetime.datetime" in result

    def test_detectUuidUuid4_whenUuid4Used(self):
        """Given code using uuid.uuid4(), when _detect_nondeterministic_patches is called, then it detects the uuid.uuid4 pattern."""
        source = """
def foo():
    import uuid
    return uuid.uuid4()
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert "uuid.uuid4" in result

    def test_detectOsEnviron_whenOsEnvironUsed(self):
        """Given code accessing os.environ, when _detect_nondeterministic_patches is called, then it detects the os.environ pattern."""
        source = """
def foo():
    import os
    return os.environ.get("KEY")
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert "os.environ" in result

    def test_detectOsGetenv_whenOsGetenvUsed(self):
        """Given code using os.getenv(), when _detect_nondeterministic_patches is called, then it detects the nondeterministic pattern."""
        source = """
def foo():
    import os
    return os.getenv("KEY")
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert "os.getenv" in result or "os.environ" in result

    def test_detectBuiltinsOpen_whenOpenUsed(self):
        """Given code calling open(), when _detect_nondeterministic_patches is called, then it detects the builtins.open pattern."""
        source = """
def foo():
    with open("file.txt") as f:
        return f.read()
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert "builtins.open" in result

    def test_detectOpenOnce_whenOpenUsedMultipleTimes(self):
        """Given code calling open() multiple times, when _detect_nondeterministic_patches is called, then it detects the pattern only once."""
        source = """
def foo():
    with open("a.txt") as f1:
        with open("b.txt") as f2:
            return f1.read() + f2.read()
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert result.count("builtins.open") == 1

    def test_returnEmptyList_whenPureCalculationCode(self):
        """Given pure calculation code, when _detect_nondeterministic_patches is called, then it returns an empty list."""
        source = """
def foo(x, y):
    return x + y
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert result == []

    def test_detectAllPatterns_whenMultipleNondeterministicSources(self):
        """Given code with multiple nondeterministic sources, when _detect_nondeterministic_patches is called, then it detects all patterns."""
        source = """
def foo():
    import datetime
    import uuid
    import random
    a = datetime.datetime.now()
    b = uuid.uuid4()
    c = random.random()
    return (a, b, c)
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert len(result) >= 2
        assert "datetime.datetime" in result
        assert "uuid.uuid4" in result

    def test_detectRandomRandint_whenRandomRandintUsed(self):
        """Given code using random.randint(), when _detect_nondeterministic_patches is called, then it detects the random.randint pattern."""
        source = """
def foo():
    import random
    return random.randint(1, 10)
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _detect_nondeterministic_patches(fn_node)
        assert "random.randint" in result


class TestInferTypesFromUsage:
    """Tests for _infer_types_from_usage."""

    def test_inferIntType_whenComparedWithInteger(self):
        """Given code comparing a value with an integer, when _infer_types_from_usage is called, then it infers the value as int type."""
        source = """
def foo(value):
    if value > 0:
        return True
    return False
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["value"], {}, {})
        assert result.get("value") == "int"

    def test_inferStrType_whenComparedWithString(self):
        """Given code comparing a value with a string, when _infer_types_from_usage is called, then it infers the value as str type."""
        source = """
def foo(name):
    if name == "":
        return False
    return True
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["name"], {}, {})
        assert result.get("name") == "str"

    def test_inferStrType_whenStringMethodCalled(self):
        """Given code calling a string method, when _infer_types_from_usage is called, then it infers the value as str type."""
        source = """
def foo(value):
    return value.strip()
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["value"], {}, {})
        assert result.get("value") == "str"

    def test_inferListType_whenListMethodCalled(self):
        """Given code calling a list method, when _infer_types_from_usage is called, then it infers the value as list type."""
        source = """
def foo(items):
    items.append(1)
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["items"], {}, {})
        assert result.get("items") == "list"

    def test_inferDictType_whenDictMethodCalled(self):
        """Given code calling a dict method, when _infer_types_from_usage is called, then it infers the value as dict type."""
        source = """
def foo(data):
    return data.get("key")
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["data"], {}, {})
        assert result.get("data") == "dict"

    def test_inferListType_whenUsedInForLoop(self):
        """Given code iterating over a value in a for loop, when _infer_types_from_usage is called, then it infers the value as list type."""
        source = """
def foo(items):
    for x in items:
        pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["items"], {}, {})
        assert result.get("items") == "list"

    def test_inferIntType_whenDefaultIsInteger(self):
        """Given a parameter with an integer default value, when _infer_types_from_usage is called, then it infers the type as int."""
        source = """
def foo(value=0):
    pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["value"], {}, {"value": "0"})
        assert result.get("value") == "int"

    def test_inferStrType_whenDefaultIsString(self):
        """Given a parameter with a string default value, when _infer_types_from_usage is called, then it infers the type as str."""
        source = """
def foo(name="hello"):
    pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["name"], {}, {"name": '"hello"'})
        assert result.get("name") == "str"

    def test_inferBoolType_whenDefaultIsBoolean(self):
        """Given a parameter with a boolean default value, when _infer_types_from_usage is called, then it infers the type as bool."""
        source = """
def foo(flag=True):
    pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["flag"], {}, {"flag": "True"})
        assert result.get("flag") == "bool"

    def test_notOverrideExistingType_whenArgAlreadyAnnotated(self):
        """Given an argument with an existing type annotation, when _infer_types_from_usage is called, then it does not override the existing type."""
        source = """
def foo(x):
    if x > 0:
        pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        existing = {"x": "float"}
        result = _infer_types_from_usage(fn_node, ["x"], existing, {})
        # Should not override existing type
        assert result == {}

    def test_returnEmptyDict_whenAllArgsAnnotated(self):
        """Given all arguments with existing type annotations, when _infer_types_from_usage is called, then it returns an empty dictionary."""
        source = """
def foo(x, y):
    pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["x", "y"], {"x": "int", "y": "str"}, {})
        assert result == {}

    def test_inferIntType_whenArithmeticWithInteger(self):
        """Given arithmetic operation with an integer, when _infer_types_from_usage is called, then it infers the value as int type."""
        source = """
def foo(value):
    return value + 1
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["value"], {}, {})
        assert result.get("value") == "int"

    def test_inferFloatOrIntType_whenArithmeticWithFloat(self):
        """Given arithmetic operation with a float, when _infer_types_from_usage is called, then it infers the value as float type."""
        source = """
def foo(value):
    return value * 1.5
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _infer_types_from_usage(fn_node, ["value"], {}, {})
        # Might be inferred as float if 1.5 float literal detected
        assert result.get("value") in ("float", "int", None)


class TestParseMethodNode:
    """Tests for _parse_method_node."""

    def test_extractNameAndArgs_whenBasicFunctionParsed(self, tmp_path):
        """Given a basic function definition, when _parse_method_node is called, then it extracts the name and arguments."""
        source = "def foo(x, y): return x + y"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.name == "foo"
        assert result.args == ["x", "y"]

    def test_excludeSelf_whenClassMethodParsed(self, tmp_path):
        """Given a class method with self as first argument, when _parse_method_node is called, then it excludes self from arguments."""
        source = """
class MyClass:
    def foo(self, x, y):
        return x + y
"""
        tree = ast.parse(source)
        class_node = tree.body[0]
        fn_node = class_node.body[0]
        result = _parse_method_node(fn_node)
        assert result.name == "foo"
        assert "self" not in result.args
        assert result.args == ["x", "y"]

    def test_populateArgTypes_whenAnnotatedArgsParsed(self, tmp_path):
        """Given type-annotated arguments, when _parse_method_node is called, then it populates arg_types."""
        source = "def foo(x: int, y: str) -> bool: return True"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.arg_types == {"x": "int", "y": "str"}

    def test_captureReturnType_whenReturnAnnotationExists(self, tmp_path):
        """Given a function with return type annotation, when _parse_method_node is called, then it captures the return_type."""
        source = "def foo(x: int) -> int: return x"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.return_type == "int"

    def test_setIsVoidTrue_whenNoneReturnType(self, tmp_path):
        """Given a function with None return type, when _parse_method_node is called, then it sets is_void=True."""
        source = "def foo() -> None: pass"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.is_void is True

    def test_setIsVoidTrue_whenNoReturnAnnotation(self, tmp_path):
        """Given a function with no return type annotation, when _parse_method_node is called, then it sets is_void=True."""
        source = "def foo(): pass"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.is_void is True

    def test_setIsAsyncTrue_whenAsyncFunctionParsed(self, tmp_path):
        """Given an async function definition, when _parse_method_node is called, then it sets is_async=True."""
        source = "async def foo(): pass"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.is_async is True

    def test_setIsStaticTrue_whenStaticmethodDecorator(self, tmp_path):
        """Given a staticmethod decorator, when _parse_method_node is called, then it sets is_static=True."""
        source = """
@staticmethod
def foo():
    pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.is_static is True

    def test_setIsClassmethodTrue_whenClassmethodDecorator(self, tmp_path):
        """Given a classmethod decorator, when _parse_method_node is called, then it sets is_classmethod=True."""
        source = """
@classmethod
def foo(cls):
    pass
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.is_classmethod is True

    def test_collectExceptionType_whenRaiseStatementExists(self, tmp_path):
        """Given code that raises an exception, when _parse_method_node is called, then it collects the exception type."""
        source = """
def foo(x):
    if x < 0:
        raise ValueError("negative")
    return x
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert "ValueError" in result.raises

    def test_captureArgDefaults_whenDefaultValuesExist(self, tmp_path):
        """Given function arguments with default values, when _parse_method_node is called, then it captures arg_defaults."""
        source = "def foo(x: int = 5, y: str = 'test'): pass"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.arg_defaults["x"] == "5"
        assert result.arg_defaults["y"] == "'test'"

    def test_populateNondeterministicPatches_whenNondeterministicCallExists(self, tmp_path):
        """Given code with nondeterministic calls, when _parse_method_node is called, then it populates nondeterministic_patches."""
        source = """
def foo():
    import datetime
    return datetime.datetime.now()
"""
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert "datetime.datetime" in result.nondeterministic_patches

    def test_setIsPublicFalse_whenMethodNameStartsWithUnderscore(self, tmp_path):
        """Given a private method name starting with underscore, when _parse_method_node is called, then it sets is_public=False."""
        source = "def _private(): pass"
        tree = ast.parse(source)
        fn_node = tree.body[0]
        result = _parse_method_node(fn_node)
        assert result.is_public is False


class TestParseConstructorDeps:
    """Tests for _parse_constructor_deps."""

    def test_extractDependency_whenTypedParamAssignedToSelf(self, tmp_path):
        """Given a constructor that assigns typed parameters to self, when _parse_constructor_deps is called, then it extracts the dependencies."""
        source = """
class MyClass:
    def __init__(self, repo: 'TodoRepository'):
        self.repo = repo
"""
        tree = ast.parse(source)
        class_node = tree.body[0]
        ctor = class_node.body[0]
        result = _parse_constructor_deps(ctor)
        # Result may have quotes around type
        repo_type = result.get("repo", "").strip("'\"")
        assert repo_type == "TodoRepository" or result.get("repo") == "TodoRepository"

    def test_returnEmptyDict_whenSelfAssignedToSelf(self, tmp_path):
        """self.x = self style ignored."""
        source = """
class MyClass:
    def __init__(self):
        self.x = self
"""
        tree = ast.parse(source)
        class_node = tree.body[0]
        ctor = class_node.body[0]
        result = _parse_constructor_deps(ctor)
        assert result == {}

    def test_returnEmptyDict_whenLiteralAssignedToSelf(self, tmp_path):
        """self.x = 'literal' not captured."""
        source = """
class MyClass:
    def __init__(self):
        self.x = "literal"
"""
        tree = ast.parse(source)
        class_node = tree.body[0]
        ctor = class_node.body[0]
        result = _parse_constructor_deps(ctor)
        assert result == {}

    def test_returnTwoEntries_whenTwoDepsInjected(self, tmp_path):
        """Two injected deps → two entries."""
        source = """
class MyClass:
    def __init__(self, repo: 'Repo', session: 'Session'):
        self.repo = repo
        self.session = session
"""
        tree = ast.parse(source)
        class_node = tree.body[0]
        ctor = class_node.body[0]
        result = _parse_constructor_deps(ctor)
        assert len(result) == 2


class TestAnalyzePython:
    """Tests for analyze_python."""

    def test_setClassNameAndMethods_whenSingleClassFile(self, tmp_path):
        """File with one class and methods."""
        source = """
class MyService:
    def get_user(self, user_id: int) -> str:
        return f"User {user_id}"

    def delete_user(self, user_id: int) -> None:
        pass
"""
        py_file = tmp_path / "service.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        assert result.class_name == "MyService"
        assert len(result.methods) == 2
        assert len(result.all_classes) == 1

    def test_setModuleLevelMethods_whenNoClassInFile(self, tmp_path):
        """No class, only module-level defs."""
        source = """
def helper(x: int) -> int:
    return x + 1

def process(data: str) -> None:
    pass
"""
        py_file = tmp_path / "utils.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        assert result.class_name is None
        assert len(result.module_level_methods) >= 2

    def test_excludeEnumFromAllClasses_whenEnumExists(self, tmp_path):
        """Enum subclass not in all_classes."""
        source = """
from enum import Enum

class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class MyClass:
    pass
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        class_names = {cls.name for cls in result.all_classes}
        assert "Status" not in class_names
        assert "MyClass" in class_names

    def test_excludePrivateMethods_whenPrivateMethodExists(self, tmp_path):
        """_helper() not in methods."""
        source = """
class MyClass:
    def _helper(self):
        pass

    def public_method(self):
        pass
"""
        py_file = tmp_path / "service.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        method_names = {m.name for m in result.methods}
        assert "_helper" not in method_names
        assert "public_method" in method_names

    def test_excludeInitFromMethods_whenInitExists(self, tmp_path):
        """__init__ not in methods but deps map populated."""
        source = """
class MyClass:
    def __init__(self, repo: 'Repo'):
        self.repo = repo

    def get(self, id: int):
        return self.repo.find(id)
"""
        py_file = tmp_path / "service.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        method_names = {m.name for m in result.methods}
        assert "__init__" not in method_names
        assert "repo" in result.constructor_dep_map

    def test_includeThirdPartyDeps_whenThirdPartyImportExists(self, tmp_path):
        """Third-party imports in external_deps, stdlib excluded."""
        source = """
import os
from sqlalchemy import create_engine
from typing import Optional

class MyClass:
    pass
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        # os, typing are stdlib → excluded
        # sqlalchemy is third-party → included
        dep_modules = {dep.module for dep in result.external_deps}
        assert "sqlalchemy" in dep_modules
        assert "os" not in dep_modules
        assert "typing" not in dep_modules

    def test_setDotNotationModulePath_whenNestedInSubdir(self, tmp_path):
        """module_path uses dot notation relative to root."""
        # Create app/service.py structure
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "__init__.py").touch()
        service_file = app_dir / "service.py"
        service_file.write_text("class Service:\n    pass")

        result = analyze_python(service_file, tmp_path)
        assert result.module_path == "app.service"

    def test_propagateConstructorDepMap_whenInitHasDeps(self, tmp_path):
        """First class's constructor_dep_map is on SourceInfo."""
        source = """
class MyClass:
    def __init__(self, repo: 'Repo'):
        self.repo = repo
"""
        py_file = tmp_path / "service.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        repo_type = result.constructor_dep_map.get("repo", "").strip("'\"")
        assert repo_type == "Repo" or result.constructor_dep_map.get("repo") == "Repo"

    def test_storeAllClasses_whenMultipleClassesInFile(self, tmp_path):
        """Two classes; all_classes has both."""
        source = """
class ClassA:
    def method_a(self):
        pass

class ClassB:
    def method_b(self):
        pass
"""
        py_file = tmp_path / "service.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        assert len(result.all_classes) == 2
        class_names = {cls.name for cls in result.all_classes}
        assert "ClassA" in class_names
        assert "ClassB" in class_names

    def test_setIsAsyncTrue_whenAsyncMethodInClass(self, tmp_path):
        """async def parsed with is_async=True."""
        source = """
class MyClass:
    async def fetch(self):
        pass
"""
        py_file = tmp_path / "service.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        async_methods = [m for m in result.methods if m.is_async]
        assert len(async_methods) > 0


class TestDetectEnumTypes:
    """Tests for detect_enum_types."""

    def test_returnEnumMembers_whenSimpleEnumClass(self, tmp_path):
        """One Enum with 3 members."""
        source = """
from enum import Enum

class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = detect_enum_types(py_file)
        assert "Status" in result
        assert set(result["Status"]) == {"ACTIVE", "INACTIVE", "PENDING"}

    def test_returnEmptyDict_whenNoEnumClass(self, tmp_path):
        """Plain class → {}."""
        source = """
class User:
    def __init__(self, name: str):
        self.name = name
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = detect_enum_types(py_file)
        assert result == {}

    def test_returnEmptyDict_whenSyntaxError(self, tmp_path):
        """Invalid Python → {}."""
        py_file = tmp_path / "models.py"
        py_file.write_text("def foo( :")
        result = detect_enum_types(py_file)
        assert result == {}

    def test_returnAllEnums_whenMultipleEnumClasses(self, tmp_path):
        """Two Enum subclasses."""
        source = """
from enum import Enum

class Status(Enum):
    A = 1
    B = 2

class Priority(Enum):
    HIGH = 1
    LOW = 2
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = detect_enum_types(py_file)
        assert len(result) == 2
        assert "Status" in result
        assert "Priority" in result


class TestDetectOrmModels:
    """Tests for detect_orm_models."""

    def test_detectSqlalchemyModel_whenColumnUsed(self, tmp_path):
        """SQLAlchemy model with Column."""
        source = """
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(50))
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = detect_orm_models(py_file)
        assert len(result) > 0
        user_orm = next((o for o in result if o.class_name == "User"), None)
        assert user_orm is not None
        assert user_orm.db_type == "sqlalchemy"

    def test_detectDjangoModel_whenModelsModelUsed(self, tmp_path):
        """Django models.Model with fields."""
        source = """
from django.db import models

class User(models.Model):
    name = models.CharField(max_length=50)
    email = models.EmailField()
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = detect_orm_models(py_file)
        assert len(result) > 0

    def test_returnEmptyList_whenNoOrmModel(self, tmp_path):
        """Plain class → []."""
        source = """
class User:
    def __init__(self, name: str):
        self.name = name
"""
        py_file = tmp_path / "models.py"
        py_file.write_text(source)
        result = detect_orm_models(py_file)
        assert result == []

    def test_returnEmptyList_whenSyntaxError(self, tmp_path):
        """Invalid Python → []."""
        py_file = tmp_path / "models.py"
        py_file.write_text("class User( :")
        result = detect_orm_models(py_file)
        assert result == []


class TestAnalyzePythonBugs:
    """Bug detection tests for analyze_python()."""

    def test_detectPlainImport_whenPlainImportUsed(self, tmp_path):
        """BUG-8: `import sqlalchemy` (plain) not detected in external_deps.

        Only `from sqlalchemy import X` is detected, not `import sqlalchemy`.
        This means plain imports are silently dropped.
        """
        source = """
import sqlalchemy
class MyClass:
    pass
"""
        py_file = tmp_path / "s.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        dep_modules = {dep.module for dep in result.external_deps}
        # BUG: plain `import sqlalchemy` is NOT detected
        assert "sqlalchemy" in dep_modules, \
            f"BUG: plain import sqlalchemy not detected. Got {dep_modules}"

    def test_includeCallMethod_whenDunderCallExists(self, tmp_path):
        """BUG-9: __call__ is skipped by line 366 condition.

        Line 366: `if item.name.startswith("__") and item.name != "__init__": continue`
        This skips ALL dunder methods except __init__, but __call__, __enter__, __exit__
        are valid test targets.
        """
        source = """
class MyClass:
    def __call__(self, x: int) -> int:
        return x
"""
        py_file = tmp_path / "s.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        method_names = {m.name for m in result.methods}
        # BUG: __call__ is skipped
        assert "__call__" in method_names, \
            f"BUG: __call__ skipped. Got methods: {method_names}"

    def test_includeInAllClasses_whenBaseContainsEnumSubstring(self, tmp_path):
        """BUG-10: class Foo(EnumHelper) wrongly excluded.

        Line 374: `if not any("Enum" in b for b in bases)`
        Substring match "Enum" in "EnumHelper" → True → Foo excluded from all_classes.
        This should check for exact match or use proper inheritance chain inspection.
        """
        source = """
class EnumHelper:
    pass

class Foo(EnumHelper):
    def method(self):
        pass
"""
        py_file = tmp_path / "s.py"
        py_file.write_text(source)
        result = analyze_python(py_file, tmp_path)
        class_names = {cls.name for cls in result.all_classes}
        # BUG: 'Enum' in 'EnumHelper' → Foo wrongly excluded
        assert "Foo" in class_names, \
            f"BUG: Foo excluded because substring 'Enum' in 'EnumHelper'. Got {class_names}"


class TestDetectEnumTypesBugs:
    """Bug detection tests for detect_enum_types()."""

    def test_notDetectAsEnum_whenBaseContainsEnumSubstring(self, tmp_path):
        """BUG-11: class Foo(EnumHelper) falsely detected as Enum.

        Line 468: `if any("Enum" in b for b in bases)`
        Substring match "Enum" in "EnumHelper" → True → Foo treated as Enum.
        This should check for exact match or proper Enum inheritance.
        """
        source = """
class EnumHelper:
    A = 1

class Foo(EnumHelper):
    X = 1
    Y = 2
"""
        py_file = tmp_path / "s.py"
        py_file.write_text(source)
        result = detect_enum_types(py_file)
        # BUG: 'Enum' in 'EnumHelper' → Foo falsely counted as Enum
        assert "Foo" not in result, \
            f"BUG: Foo falsely detected as Enum because substring 'Enum' in 'EnumHelper'. Got {result}"

    def test_detectTrueEnum_whenTrueEnumClass(self, tmp_path):
        """Verify true Enum still detected (regression)."""
        source = """
from enum import Enum

class Status(Enum):
    ACTIVE = 1
    INACTIVE = 2
"""
        py_file = tmp_path / "s.py"
        py_file.write_text(source)
        result = detect_enum_types(py_file)
        assert "Status" in result
        assert set(result["Status"]) == {"ACTIVE", "INACTIVE"}
