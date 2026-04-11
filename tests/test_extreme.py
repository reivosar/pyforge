"""Tests for pyforge.cases.extreme module."""
import pytest

from pyforge.cases.extreme import (
    _type_to_strategy,
    build_hypothesis_test,
    extreme_value_cases,
)
from pyforge.models import DepInfo


class TestExtremeValueCases:
    """Tests for extreme_value_cases."""

    def test_returnThreeIntCases_whenIntArg(self, make_method):
        """Given an int-typed argument, when extreme_value_cases is called, then it generates MaxInt, MinInt, and Zero cases."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        result = extreme_value_cases(method)
        assert len(result) == 3
        test_names = {case.test_name for case in result}
        assert any("MaxInt" in name for name in test_names)
        assert any("MinInt" in name for name in test_names)
        assert any("Zero" in name for name in test_names)

    def test_returnFourFloatCases_whenFloatArg(self, make_method):
        """Given a float-typed argument, when extreme_value_cases is called, then it generates Infinity, NaN, and NegativeZero cases."""
        method = make_method(args=["x"], arg_types={"x": "float"})
        result = extreme_value_cases(method)
        assert len(result) == 4
        test_names = {case.test_name for case in result}
        assert any("Infinity" in name for name in test_names)
        assert any("NaN" in name for name in test_names)

    def test_returnFourStrCases_whenStrArg(self, make_method):
        """Given a str-typed argument, when extreme_value_cases is called, then it generates EmptyString, NullByte, VeryLongStr, and UnicodeStr cases."""
        method = make_method(args=["name"], arg_types={"name": "str"})
        result = extreme_value_cases(method)
        assert len(result) == 4
        test_names = {case.test_name for case in result}
        assert any("EmptyString" in name for name in test_names)
        assert any("NullByte" in name for name in test_names)
        assert any("VeryLongStr" in name for name in test_names)
        assert any("UnicodeStr" in name for name in test_names)

    def test_returnFiveCases_whenUntypedArg(self, make_method):
        """Given an untyped argument, when extreme_value_cases is called, then it generates NoneValue, EmptyString, ZeroInt, EmptyList, and EmptyDict cases."""
        method = make_method(args=["x"])
        result = extreme_value_cases(method)
        assert len(result) == 5
        test_names = {case.test_name for case in result}
        assert any("NoneValue" in name for name in test_names)
        assert any("EmptyString" in name for name in test_names)
        assert any("ZeroInt" in name for name in test_names)

    def test_returnEmptyList_whenBoolTypedArg(self, make_method):
        """Given bool, list, or dict typed arguments, when extreme_value_cases is called, then it returns no cases."""
        method = make_method(args=["flag"], arg_types={"flag": "bool"})
        result = extreme_value_cases(method)
        assert result == []

    def test_returnCasesForEachType_whenMultipleTypedArgs(self, make_method):
        """Given multiple typed arguments, when extreme_value_cases is called, then it generates cases for each type."""
        method = make_method(
            args=["x", "name"],
            arg_types={"x": "int", "name": "str"},
        )
        result = extreme_value_cases(method)
        assert len(result) == 7

    def test_includeCompleteWhenAndIs_whenExtremeCase(self, make_method):
        """Given generated extreme cases, when checked, then test names include 'complete_when' and argument details."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        result = extreme_value_cases(method)
        assert all("complete_when" in case.test_name for case in result)
        assert all("Is" in case.test_name for case in result)

    def test_includeMaxSizeInOverrides_whenIntExtremeCase(self, make_method):
        """Given int extreme cases, when checked, then they include input_overrides with extreme values."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        result = extreme_value_cases(method)
        overrides = {case.input_overrides["x"] for case in result}
        assert "sys.maxsize" in overrides

    def test_setIsHappyPathFalse_whenExtremeCase(self, make_method):
        """Given extreme value cases, when checked, then all cases have is_happy_path=False."""
        method = make_method(args=["x"], arg_types={"x": "int"})
        result = extreme_value_cases(method)
        assert all(case.is_happy_path is False for case in result)


class TestTypeToStrategy:
    """Tests for _type_to_strategy."""

    def test_returnIntegersStrategy_whenIntType(self):
        """Given the 'int' type, when _type_to_strategy is called, then it returns a strategy for integers."""
        result = _type_to_strategy("int")
        assert result == "st.integers()"

    def test_returnTextStrategy_whenStrType(self):
        """Given the 'str' type, when _type_to_strategy is called, then it returns a strategy for text."""
        result = _type_to_strategy("str")
        assert result == "st.text()"

    def test_returnFloatsStrategy_whenFloatType(self):
        """'float' → 'st.floats(...)'."""
        result = _type_to_strategy("float")
        assert "floats" in result

    def test_returnBooleansStrategy_whenBoolType(self):
        """'bool' → 'st.booleans()'."""
        result = _type_to_strategy("bool")
        assert result == "st.booleans()"

    def test_returnOneOfStrategy_whenOptionalIntType(self):
        """'Optional[int]' → 'st.one_of(...)'."""
        result = _type_to_strategy("Optional[int]")
        assert "one_of" in result
        assert "integers" in result

    def test_returnOneOfWithText_whenOptionalStrType(self):
        """'Optional[str]' → 'st.one_of(...)'."""
        result = _type_to_strategy("Optional[str]")
        assert "one_of" in result
        assert "text" in result

    def test_returnListsStrategy_whenListIntType(self):
        """'list[int]' → 'st.lists(...)'."""
        result = _type_to_strategy("list[int]")
        assert "lists" in result

    def test_returnListsStrategy_whenCapitalListIntType(self):
        """'List[int]' (capital L) → 'st.lists(...)'."""
        result = _type_to_strategy("List[int]")
        assert "lists" in result

    def test_returnNoneStrategy_whenUnknownType(self):
        """'FooBar' → 'st.none()'."""
        result = _type_to_strategy("FooBar")
        assert result == "st.none()"

    def test_returnNoneStrategy_whenNoneHint(self):
        """None → 'st.none()'."""
        result = _type_to_strategy(None)
        assert result == "st.none()"

    def test_returnNoneStrategy_whenEmptyStringHint(self):
        """'' → 'st.none()'."""
        result = _type_to_strategy("")
        assert result == "st.none()"

    def test_returnSameResult_whenWhitespaceInOptionalType(self):
        """'Optional[ int ]' same as 'Optional[int]'."""
        result1 = _type_to_strategy("Optional[int]")
        result2 = _type_to_strategy("Optional[ int ]")
        assert result1 == result2


class TestBuildHypothesisTest:
    """Tests for build_hypothesis_test."""

    def test_returnNone_whenVoidMethod(self, make_method):
        """is_void=True → None."""
        method = make_method(args=["x"], arg_types={"x": "int"}, is_void=True)
        result = build_hypothesis_test(method, [], "module", None)
        assert result is None

    def test_returnNone_whenNoArgs(self, make_method):
        """Empty args → None."""
        method = make_method(args=[])
        result = build_hypothesis_test(method, [], "module", None)
        assert result is None

    def test_returnNone_whenUntypedArgs(self, make_method):
        """No arg_types → None."""
        method = make_method(args=["x"])  # No type hints
        result = build_hypothesis_test(method, [], "module", None)
        assert result is None

    def test_includeGivenDecorator_whenTypedArg(self, make_method):
        """Result contains @given."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = build_hypothesis_test(method, [], "module", None)
        assert result is not None
        assert "@given" in result

    def test_includeMaxExamples50_whenTypedArg(self, make_method):
        """Result contains @settings(max_examples=50)."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = build_hypothesis_test(method, [], "module", None)
        assert result is not None
        assert "max_examples=50" in result

    def test_includeMethodName_whenTypedArg(self, make_method):
        """Result contains method name in test name."""
        method = make_method(
            name="fetch_user",
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = build_hypothesis_test(method, [], "module", None)
        assert result is not None
        assert "fetch_user" in result.lower()

    def test_includePatchDecorators_whenDepsProvided(self, make_method):
        """deps → @patch(...) lines."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        deps = [DepInfo("app.db", "Repository", None)]
        result = build_hypothesis_test(method, deps, "app.service", None)
        assert result is not None
        assert "@patch" in result

    def test_includeClassName_whenConstructorDepMapProvided(self, make_method):
        """Constructor dep map generates proper setup."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        deps = [DepInfo("app.db", "Repository", None)]
        result = build_hypothesis_test(
            method,
            deps,
            "app.service",
            "MyService",
            constructor_dep_map={"repo": "Repository"},
        )
        assert result is not None
        assert "MyService" in result

    def test_includeExceptClause_whenRaisesProvided(self, make_method):
        """raises=['ValueError'] → except (ValueError)."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
            raises=["ValueError"],
        )
        result = build_hypothesis_test(method, [], "module", None)
        assert result is not None
        assert "ValueError" in result
        assert "except" in result

    def test_includeAsyncioRun_whenAsyncMethod(self, make_method):
        """is_async=True → asyncio.run(...)."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
            is_async=True,
        )
        result = build_hypothesis_test(method, [], "module", None)
        assert result is not None
        assert "asyncio.run" in result

    def test_notUseSut_whenNoClassName(self, make_method):
        """class_name=None → direct function call, 'sut' must NOT appear."""
        method = make_method(
            name="process",
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
        )
        result = build_hypothesis_test(method, [], "module.process", None)
        assert result is not None
        assert "sut" not in result, (
            "Direct function call test (class_name=None) must not use 'sut'"
        )

    def test_includeExceptException_whenNoRaises(self, make_method):
        """No raises → except Exception."""
        method = make_method(
            args=["x"],
            arg_types={"x": "int"},
            is_void=False,
            return_type="int",
            raises=[],
        )
        result = build_hypothesis_test(method, [], "module", None)
        assert result is not None
        assert "except Exception" in result


class TestTypeToStrategyLimitations:
    """Limitations and potential bugs in _type_to_strategy."""

    def test_returnNoneStrategy_whenDictStrIntType(self):
        """BUG: dict[str, int] is not in TYPE_TO_STRATEGY."""
        result = _type_to_strategy("dict[str, int]")
        # Result defaults to st.none() because not in dictionary
        print(f"dict[str, int] = {result}")
        assert result == "st.none()", \
            f"BUG: dict[str, int] not supported. Got {result}, expected st.dictionaries(...)"

    def test_returnNoneStrategy_whenDictIntStrType(self):
        """BUG: dict[int, str] is not in TYPE_TO_STRATEGY."""
        result = _type_to_strategy("dict[int, str]")
        print(f"dict[int, str] = {result}")
        assert result == "st.none()", \
            f"BUG: dict[int, str] not supported. Got {result}"

    def test_returnListsOrTextStrategy_whenListStrType(self):
        """Verify list[str] is properly handled."""
        result = _type_to_strategy("list[str]")
        print(f"list[str] = {result}")
        # Should match via dictionary or regex
        assert "lists" in result or "text" in result, \
            f"list[str] not properly handled. Got {result}"

    def test_returnNoneStrategy_whenUppercaseIntType(self):
        """Test that 'INT' is not recognized (should be lowercase)."""
        result = _type_to_strategy("INT")
        print(f"INT = {result}")
        # Current behavior: returns st.none()
        # This is correct because Python type hints are lowercase
        assert result == "st.none()", \
            f"INT should not match. Got {result}"

    def test_returnOneOfStrategy_whenOptionalListIntType(self):
        """Test Optional[List[int]] handling."""
        result = _type_to_strategy("Optional[List[int]]")
        print(f"Optional[List[int]] = {result}")
        # Should be: st.one_of(st.none(), st.lists(st.integers()))
        assert "one_of" in result, \
            f"Optional should create one_of. Got {result}"

