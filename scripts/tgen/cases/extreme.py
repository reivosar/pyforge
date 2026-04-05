"""Extreme value and Hypothesis property-based test case generators."""
from __future__ import annotations

import re

from tgen.cases.branch import _camel
from tgen.analysis.python_ast import _type_sample
from tgen.models import BranchCase, DepInfo, MethodInfo


# ── extreme value constants ───────────────────────────────────────────────────

_INT_EXTREMES: list[tuple[str, str]] = [
    ("sys.maxsize",         "MaxInt"),
    ("-(sys.maxsize + 1)",  "MinInt"),
    ("0",                   "Zero"),
]
_FLOAT_EXTREMES: list[tuple[str, str]] = [
    ("float('inf')",  "PosInfinity"),
    ("float('-inf')", "NegInfinity"),
    ("float('nan')",  "NaN"),
    ("-0.0",          "NegativeZero"),
]
_STR_EXTREMES: list[tuple[str, str]] = [
    ('""',             "EmptyString"),
    ('"\\x00"',        "NullByte"),
    ('"a" * 10000',    "VeryLongStr"),
    ('"日本語テスト"', "UnicodeStr"),
]

# For args with no type hint: try canonical edge values across common types
_UNTYPED_EXTREMES: list[tuple[str, str]] = [
    ("None",  "NoneValue"),
    ('""',    "EmptyString"),
    ("0",     "ZeroInt"),
    ("[]",    "EmptyList"),
    ("{}",    "EmptyDict"),
]


def extreme_value_cases(method: MethodInfo) -> list[BranchCase]:
    """
    For int/float/str typed args, generate tests at extreme/special values.
    For untyped args, generate None/empty/zero edge cases.
    """
    cases: list[BranchCase] = []
    for arg in method.args:
        hint = method.arg_types.get(arg, "").split("[")[0].strip()
        if hint == "int":
            extremes = _INT_EXTREMES
        elif hint == "float":
            extremes = _FLOAT_EXTREMES
        elif hint == "str":
            extremes = _STR_EXTREMES
        elif not hint:
            extremes = _UNTYPED_EXTREMES
        else:
            continue
        for val, label in extremes:
            cases.append(BranchCase(
                test_name=f"complete_when{_camel(arg)}Is{label}",
                input_overrides={arg: val},
                mock_side_effect=None, mock_return_override=None,
                expected_exception=None, expected_return=None,
                is_happy_path=False,
            ))
    return cases


# ── Hypothesis integration ────────────────────────────────────────────────────

TYPE_TO_STRATEGY: dict[str, str] = {
    "int":           "st.integers()",
    "float":         "st.floats(allow_nan=False, allow_infinity=False)",
    "str":           "st.text()",
    "bool":          "st.booleans()",
    "bytes":         "st.binary()",
    "list":          "st.lists(st.integers())",
    "list[int]":     "st.lists(st.integers())",
    "list[str]":     "st.lists(st.text())",
    "list[float]":   "st.lists(st.floats(allow_nan=False))",
    "dict":          "st.dictionaries(st.text(), st.text())",
    "dict[str,str]": "st.dictionaries(st.text(), st.text())",
    "Optional[int]": "st.one_of(st.none(), st.integers())",
    "Optional[str]": "st.one_of(st.none(), st.text())",
    "Optional[float]": "st.one_of(st.none(), st.floats(allow_nan=False))",
    "EmailStr":      "st.emails()",
    "HttpUrl":       'st.just("https://example.com")',
    "UUID":          "st.uuids().map(str)",
    "date":          "st.dates()",
    "datetime":      "st.datetimes()",
    "Decimal":       "st.decimals(allow_nan=False, allow_infinity=False)",
}


def _type_to_strategy(type_hint: str | None) -> str:
    if not type_hint:
        return "st.none()"
    norm = re.sub(r"\s+", "", type_hint)
    if norm in TYPE_TO_STRATEGY:
        return TYPE_TO_STRATEGY[norm]
    m = re.match(r"Optional\[(.+)\]", norm)
    if m:
        inner = _type_to_strategy(m.group(1))
        return f"st.one_of(st.none(), {inner})"
    m = re.match(r"[Ll]ist\[(.+)\]", norm)
    if m:
        inner = _type_to_strategy(m.group(1))
        return f"st.lists({inner})"
    return "st.none()"


def build_hypothesis_test(
    method: MethodInfo,
    deps: list[DepInfo],
    module_path: str,
    class_name: str | None,
    constructor_dep_map: dict[str, str] | None = None,
) -> str | None:
    """
    Return a @given-based property test for the method, or None if
    type hints are insufficient to generate strategies.
    """
    if not method.args or method.is_void:
        return None
    typed = {a: method.arg_types[a] for a in method.args if a in method.arg_types}
    if not typed:
        return None

    patch_decorators = [f"@patch('{module_path}.{dep.name}')" for dep in deps]
    mock_args = [f"mock_{dep.name.lower()}" for dep in deps]

    given_kwargs = ", ".join(
        f"{arg}={_type_to_strategy(method.arg_types.get(arg))}"
        for arg in method.args
    )
    all_args = ["self"] + mock_args + list(method.args)
    test_name = f"neverRaiseUnexpectedException_when{_camel(method.name)}CalledWithAnyInput"

    lines: list[str] = []
    lines.append(f"    @given({given_kwargs})")
    for d in patch_decorators:
        lines.append(f"    {d}")
    lines.append(f"    @settings(max_examples=50)")
    lines.append(f"    def {test_name}({', '.join(all_args)}):")
    for mock_arg in mock_args:
        lines.append(f"        {mock_arg}.return_value = MagicMock()")
    if class_name:
        ctor_map = constructor_dep_map or {}
        if ctor_map:
            dep_type_to_mock = {dep.name: ma for dep, ma in zip(deps, mock_args)}
            ctor_kwargs = ", ".join(
                f"{attr}={dep_type_to_mock.get(t, 'MagicMock()')}"
                for attr, t in ctor_map.items()
            )
            lines.append(f"        sut = {class_name}({ctor_kwargs})")
        else:
            lines.append(f"        sut = {class_name}()")
            for dep, mock_arg in zip(deps, mock_args):
                attr = dep.alias or dep.name.lower()
                lines.append(f"        sut.{attr} = {mock_arg}.return_value")

    call_args = ", ".join(f"{a}={a}" for a in method.args)
    expected_excs = ", ".join(method.raises) if method.raises else "Exception"
    aw = "await " if method.is_async else ""
    lines.append(f"        # When — property: must never raise unexpected exceptions")
    lines.append(f"        try:")
    if class_name:
        lines.append(f"            {aw}sut.{method.name}({call_args})")
    else:
        lines.append(f"            {aw}{method.name}({call_args})")
    if method.raises:
        lines.append(f"        except ({expected_excs}):")
        lines.append(f"            pass  # expected exceptions are acceptable")
    lines.append(f"        except Exception as e:")
    lines.append(f"            raise AssertionError(f'Unexpected exception: {{type(e).__name__}}: {{e}}')")

    return "\n".join(lines)
