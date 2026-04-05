"""Branch-based test case extraction from Python AST."""
from __future__ import annotations

import ast
import re

from pyforge.models import BranchCase, MethodInfo


_MAX_TEST_NAME = 80


def _numeric_const(node: ast.expr) -> int | float | None:
    """Extract a numeric value from Constant or UnaryOp(USub, Constant)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if (isinstance(node, ast.UnaryOp) and
            isinstance(node.op, ast.USub) and
            isinstance(node.operand, ast.Constant) and
            isinstance(node.operand.value, (int, float))):
        return -node.operand.value
    return None


def _is_numeric_node(node: ast.expr) -> bool:
    return _numeric_const(node) is not None


def _truncate_test_name(name: str) -> str:
    """Trim test names that exceed _MAX_TEST_NAME characters."""
    if len(name) <= _MAX_TEST_NAME:
        return name
    parts = name.split("_when", 1)
    if len(parts) == 2:
        prefix, condition = parts
        budget = _MAX_TEST_NAME - len(prefix) - 5
        return f"{prefix}_when{condition[:max(budget, 8)]}"
    return name[:_MAX_TEST_NAME]


def _camel(s: str) -> str:
    return "".join(w.capitalize() for w in re.split(r"[_\s]+", s) if w)


def _attr_to_name(node: ast.expr) -> str:
    """Flatten an attribute chain (self.x.y) to a clean name, stripping 'self_'."""
    raw = ast.unparse(node).replace(".", "_")
    raw = re.sub(r"^self_", "", raw)
    return raw


def _condition_to_name(cond: ast.expr) -> str:
    """Convert AST condition to a CamelCase when-clause name."""
    if isinstance(cond, ast.BoolOp):
        joiner = "And" if isinstance(cond.op, ast.And) else "Or"
        parts = [_condition_to_name(v) for v in cond.values]
        return joiner.join(parts[:2])

    # isinstance(x, T)
    if (isinstance(cond, ast.Call) and
            isinstance(cond.func, ast.Name) and
            cond.func.id == "isinstance" and len(cond.args) == 2):
        arg_s = _attr_to_name(cond.args[0])
        type_s = ast.unparse(cond.args[1]).split(".")[-1]
        return f"{_camel(arg_s)}Is{_camel(type_s)}"

    # x in collection  /  x not in collection
    if isinstance(cond, ast.Compare) and len(cond.ops) == 1:
        left, op, right = cond.left, cond.ops[0], cond.comparators[0]
        left_s = _attr_to_name(left)

        if isinstance(op, ast.In):
            coll_s = _camel(re.sub(r"[^a-zA-Z0-9]", "_", ast.unparse(right)[:24]))
            return f"{_camel(left_s)}In{coll_s}"
        if isinstance(op, ast.NotIn):
            coll_s = _camel(re.sub(r"[^a-zA-Z0-9]", "_", ast.unparse(right)[:24]))
            return f"{_camel(left_s)}NotIn{coll_s}"

        if isinstance(right, ast.Constant) and right.value is None:
            if isinstance(op, ast.Is):    return f"{_camel(left_s)}IsNone"
            if isinstance(op, ast.IsNot): return f"{_camel(left_s)}IsNotNone"

        if isinstance(right, ast.Constant):
            v = right.value
            op_map = {
                ast.LtE: "IsZeroOrNegative" if v == 0 else f"IsLtEq{v}",
                ast.Lt:  "IsNegative"        if v == 0 else f"IsLt{v}",
                ast.GtE: "IsZeroOrPositive"  if v == 0 else f"IsGtEq{v}",
                ast.Gt:  "IsPositive"         if v == 0 else f"IsGt{v}",
                ast.Eq:  "IsEmpty" if v in ("", [], {}) else f"IsEq{v}",
                ast.NotEq: f"IsNot{v}",
            }
            suffix = op_map.get(type(op), "")
            if suffix:
                return f"{_camel(left_s)}{suffix}"

    # chained: const op name op const  e.g. 0 < x < 10  →  XBetween0And10
    if isinstance(cond, ast.Compare) and len(cond.ops) >= 2:
        # pattern: numeric op var op numeric
        if _is_numeric_node(cond.left):
            subject_s = _attr_to_name(cond.comparators[0]) or ast.unparse(cond.comparators[0])
            lo_val = _numeric_const(cond.left)
            hi_val = _numeric_const(cond.comparators[-1])
            lo_s = str(lo_val).replace("-", "Minus")
            hi_s = str(hi_val).replace("-", "Minus") if hi_val is not None else ast.unparse(cond.comparators[-1])
        else:
            subject_s = _attr_to_name(cond.left) or ast.unparse(cond.left)
            lo_s = ast.unparse(cond.comparators[0])
            hi_s = ast.unparse(cond.comparators[-1]) if len(cond.comparators) > 1 else lo_s
        return f"{_camel(subject_s)}Between{_camel(lo_s)}And{_camel(hi_s)}"

    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        inner_cond = cond.operand
        # not (lo < x < hi)  →  XOutOfRangeLoToHi
        if isinstance(inner_cond, ast.Compare) and len(inner_cond.ops) >= 2 and _is_numeric_node(inner_cond.left):
            subject_s = _attr_to_name(inner_cond.comparators[0]) or ast.unparse(inner_cond.comparators[0])
            lo_val = _numeric_const(inner_cond.left)
            hi_val = _numeric_const(inner_cond.comparators[-1])
            lo_s = str(lo_val).replace("-", "Minus")
            hi_s = str(hi_val).replace("-", "Minus") if hi_val is not None else ""
            return f"{_camel(subject_s)}OutOfRange{lo_s}To{hi_s}"
        inner = ast.unparse(inner_cond).replace("self.", "")
        return f"{_camel(re.sub(r'[^a-zA-Z0-9]', '_', inner))}IsFalse"

    if (isinstance(cond, ast.Compare) and
            isinstance(cond.left, ast.Call) and
            isinstance(cond.left.func, ast.Name) and
            cond.left.func.id == "len"):
        arg_s = ast.unparse(cond.left.args[0]).replace("self.", "") if cond.left.args else "arg"
        return f"{_camel(arg_s)}IsEmpty"

    raw = ast.unparse(cond)
    return _camel(re.sub(r"[^a-zA-Z0-9]", "_", raw))


def _arg_name_from_node(node: ast.expr) -> str | None:
    """Return the local variable name if node is a bare Name. Ignores self.attr chains."""
    if isinstance(node, ast.Name):
        return node.id
    return None


def _condition_to_inputs(cond: ast.expr, arg_types: dict[str, str]) -> dict[str, str]:
    """Derive concrete input overrides that TRIGGER the condition."""
    inputs: dict[str, str] = {}

    if isinstance(cond, ast.BoolOp):
        for value in cond.values:
            inputs.update(_condition_to_inputs(value, arg_types))
        return inputs

    # isinstance(x, T) — supply a value of the matching type
    if (isinstance(cond, ast.Call) and
            isinstance(cond.func, ast.Name) and
            cond.func.id == "isinstance" and len(cond.args) == 2):
        arg = _arg_name_from_node(cond.args[0])
        if arg and arg in arg_types:
            type_s = ast.unparse(cond.args[1]).split(".")[-1].strip("()")
            from pyforge.analysis.python_ast import _type_sample
            inputs[arg] = _type_sample(type_s)
        return inputs

    if isinstance(cond, ast.Compare):
        left, ops, comparators = cond.left, cond.ops, cond.comparators

        # chained: const op name op const  e.g. 0 < x < 10  →  trigger with mid-point
        if len(ops) >= 2 and _is_numeric_node(left) and _is_numeric_node(comparators[-1]):
            arg = _arg_name_from_node(comparators[0])
            if arg:
                lo = _numeric_const(left)
                hi = _numeric_const(comparators[-1])
                if lo is not None and hi is not None:
                    mid_val = (lo + hi) // 2 if isinstance(lo, int) and isinstance(hi, int) else (lo + hi) / 2
                    inputs[arg] = repr(mid_val)
            return inputs

        if len(ops) == 1:
            op, right = ops[0], comparators[0]
            arg = _arg_name_from_node(left)

            # x in [a, b, c]  →  use first element
            if isinstance(op, ast.In) and arg:
                if isinstance(right, (ast.List, ast.Tuple, ast.Set)) and right.elts:
                    inputs[arg] = ast.unparse(right.elts[0])
                elif isinstance(right, ast.Constant) and isinstance(right.value, str):
                    inputs[arg] = repr(right.value[0]) if right.value else '""'
                return inputs

            # x not in [a, b, c]  →  use a sentinel value not in the collection
            if isinstance(op, ast.NotIn) and arg:
                hint = arg_types.get(arg, "")
                if "str" in hint.lower():
                    inputs[arg] = '"__not_in_value__"'
                elif "int" in hint.lower():
                    inputs[arg] = "-99999"
                else:
                    inputs[arg] = "None"
                return inputs

            if arg:
                if isinstance(right, ast.Constant):
                    v = right.value
                    if isinstance(op, ast.LtE) and v == 0:        inputs[arg] = "-1"
                    elif isinstance(op, ast.Lt) and v == 0:        inputs[arg] = "-1"
                    elif isinstance(op, ast.Eq) and v == 0:        inputs[arg] = "0"
                    elif isinstance(op, ast.Eq) and v == "":       inputs[arg] = '""'
                    elif isinstance(op, ast.Gt) and isinstance(v, (int, float)):
                        inputs[arg] = repr(v + 1)
                    elif isinstance(op, ast.GtE) and isinstance(v, (int, float)):
                        inputs[arg] = repr(v)
                    elif isinstance(op, ast.Lt) and isinstance(v, (int, float)):
                        inputs[arg] = repr(v - 1)
                    elif isinstance(op, ast.LtE) and isinstance(v, (int, float)):
                        inputs[arg] = repr(v)
                    elif isinstance(op, ast.NotEq) and isinstance(v, (int, float)):
                        inputs[arg] = repr(v + 1)
                if isinstance(right, ast.Constant) and right.value is None:
                    if isinstance(op, ast.Is): inputs[arg] = "None"

    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        inner_cond = cond.operand
        # not (lo < x < hi)  →  use lo (out-of-range below)
        if isinstance(inner_cond, ast.Compare) and len(inner_cond.ops) >= 2 and _is_numeric_node(inner_cond.left):
            arg = _arg_name_from_node(inner_cond.comparators[0])
            lo = _numeric_const(inner_cond.left)
            if arg and lo is not None:
                inputs[arg] = repr(lo)
        elif isinstance(inner_cond, ast.Name):
            arg = inner_cond.id
            hint = arg_types.get(arg, "")
            if "list" in hint.lower(): inputs[arg] = "[]"
            elif "dict" in hint.lower(): inputs[arg] = "{}"
            elif "str" in hint.lower(): inputs[arg] = '""'
            else: inputs[arg] = "[]"

    # opaque call: if validate(x): → supply a type-sample for each Name arg
    if isinstance(cond, ast.Call):
        from pyforge.analysis.python_ast import _type_sample
        for a in cond.args:
            arg = _arg_name_from_node(a)
            if arg and arg in arg_types:
                inputs[arg] = _type_sample(arg_types[arg])
        return inputs

    if (isinstance(cond, ast.Compare) and
            isinstance(cond.left, ast.Call) and
            isinstance(cond.left.func, ast.Name) and
            cond.left.func.id == "len" and
            cond.left.args and isinstance(cond.left.args[0], ast.Name)):
        if isinstance(cond.ops[0], ast.Eq):
            inputs[cond.left.args[0].id] = "[]"

    return inputs


def _boundary_cases_from_condition(
    cond: ast.expr,
    arg_types: dict[str, str],
    exc_name: str | None,
) -> list[BranchCase]:
    """Generate boundary BranchCases for numeric and length conditions."""
    cases: list[BranchCase] = []

    # not (lo < x < hi)  →  unwrap and treat as chained
    if isinstance(cond, ast.UnaryOp) and isinstance(cond.op, ast.Not):
        return _boundary_cases_from_condition(cond.operand, arg_types, exc_name)

    if not isinstance(cond, ast.Compare):
        return cases

    # chained: const op arg op const  e.g. 0 < x < 10  or  -5 <= score <= 100
    if len(cond.ops) >= 2 and _is_numeric_node(cond.left) and _is_numeric_node(cond.comparators[-1]):
        mid_node = cond.comparators[0]
        arg = _arg_name_from_node(mid_node)
        if arg:
            lo = _numeric_const(cond.left)
            hi = _numeric_const(cond.comparators[-1])
            if lo is not None and hi is not None and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                # boundary: lo itself (fail), lo+1 (pass), hi-1 (pass), hi itself (fail)
                boundary_pairs: list[tuple[int | float, bool]] = [
                    (lo, False),
                    (lo + (1 if isinstance(lo, int) else 0.001), True),
                    (hi - (1 if isinstance(hi, int) else 0.001), True),
                    (hi, False),
                ]
                for val, triggers in boundary_pairs:
                    label = f"AtBoundary{repr(val)}".replace("-", "Minus").replace(".", "Dot").replace("'", "")
                    if triggers:
                        pass  # happy region, no extra case needed
                    elif exc_name:
                        cases.append(BranchCase(
                            test_name=_truncate_test_name(f"raise{exc_name}_when{_camel(arg)}Is{label}"),
                            input_overrides={arg: repr(val)},
                            mock_side_effect=None, mock_return_override=None,
                            expected_exception=exc_name, expected_return=None,
                            is_happy_path=False,
                        ))
        return cases

    if len(cond.ops) != 1:
        return cases

    left, op, right = cond.left, cond.ops[0], cond.comparators[0]

    # numeric: arg op N
    if (isinstance(left, ast.Name) and
            isinstance(right, ast.Constant) and
            isinstance(right.value, (int, float))):
        arg, N = left.id, right.value
        pairs: list[tuple[int | float, bool]] = []
        if   isinstance(op, ast.Gt):  pairs = [(N, False), (N + 1, True)]
        elif isinstance(op, ast.GtE): pairs = [(N - 1, False), (N, True)]
        elif isinstance(op, ast.Lt):  pairs = [(N, False), (N - 1, True)]
        elif isinstance(op, ast.LtE): pairs = [(N + 1, False), (N, True)]

        for val, triggers in pairs:
            label = f"AtBoundary{val}".replace("-", "Minus").replace(".", "Dot")
            if triggers and exc_name:
                cases.append(BranchCase(
                    test_name=_truncate_test_name(f"raise{exc_name}_when{_camel(arg)}Is{label}"),
                    input_overrides={arg: repr(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=exc_name, expected_return=None,
                    is_happy_path=False,
                ))
            elif not triggers:
                cases.append(BranchCase(
                    test_name=_truncate_test_name(f"notRaise_when{_camel(arg)}IsOnSafeSide{label}"),
                    input_overrides={arg: repr(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=None, expected_return=None,
                    is_happy_path=False,
                ))

    # len(arg) op N
    if (isinstance(left, ast.Call) and
            isinstance(left.func, ast.Name) and
            left.func.id == "len" and
            left.args and isinstance(left.args[0], ast.Name) and
            isinstance(right, ast.Constant) and isinstance(right.value, int) and
            right.value > 0):
        arg, N = left.args[0].id, right.value
        hint = arg_types.get(arg, "")
        is_str = "str" in hint.lower()

        def make_len_val(n: int) -> str:
            n = max(0, n)
            return f'"{"a" * n}"' if is_str else f'[0] * {n}'

        pairs_len: list[tuple[int, bool]] = []
        if   isinstance(op, ast.Gt):  pairs_len = [(N, False), (N + 1, True)]
        elif isinstance(op, ast.GtE): pairs_len = [(max(0, N - 1), False), (N, True)]
        elif isinstance(op, ast.Lt):  pairs_len = [(N, False), (max(0, N - 1), True)]
        elif isinstance(op, ast.LtE): pairs_len = [(N + 1, False), (N, True)]
        elif isinstance(op, ast.Eq):  pairs_len = [(max(0, N - 1), False), (N, True), (N + 1, False)]

        for val, triggers in pairs_len:
            label = f"LengthIs{val}"
            if triggers and exc_name:
                cases.append(BranchCase(
                    test_name=_truncate_test_name(f"raise{exc_name}_when{_camel(arg)}{label}"),
                    input_overrides={arg: make_len_val(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=exc_name, expected_return=None,
                    is_happy_path=False,
                ))
            elif not triggers:
                cases.append(BranchCase(
                    test_name=_truncate_test_name(f"notRaise_when{_camel(arg)}{label}"),
                    input_overrides={arg: make_len_val(val)},
                    mock_side_effect=None, mock_return_override=None,
                    expected_exception=None, expected_return=None,
                    is_happy_path=False,
                ))

    return cases


def _exc_short(node: ast.expr | None) -> str:
    if node is None: return "Exception"
    if isinstance(node, ast.Call): return ast.unparse(node.func).split(".")[-1]
    return ast.unparse(node).split(".")[-1]


def _infer_bool_return_for_happy_path(cases: list[BranchCase]) -> str | None:
    """Infer happy-path bool return from branch return patterns."""
    non_happy_returns = {
        b.expected_return for b in cases
        if not b.is_happy_path and b.expected_return in ("True", "False")
    }
    if non_happy_returns == {"False"}:
        return "True"
    if non_happy_returns == {"True"}:
        return "False"
    return None


def analyze_method_branches(method: MethodInfo) -> list[BranchCase]:
    """
    Walk a method's AST and produce one BranchCase per distinct execution path:
      - each `if cond: raise X`         → exception case
      - each `if cond: return Y`         → early-return case
      - each `except E: raise X`         → dependency-failure case
      - always appends the happy path    → normal return case
    """
    if method.ast_node is None:
        return [BranchCase("", {}, None, None, None, None, True)]

    node: ast.FunctionDef = method.ast_node
    cases: list[BranchCase] = []

    def _lift_loop_overrides(
        raw: dict[str, str],
        loop_vars: dict[str, str],
    ) -> dict[str, str]:
        """Rewrite loop-var keys into their source iterable arg keys.

        e.g. raw={item: "5"}, loop_vars={item: "items"} → {items: "[5]"}
        Only rewrites when the iterable name is a known method arg.
        """
        result: dict[str, str] = {}
        for k, v in raw.items():
            if k in loop_vars and loop_vars[k] in method.arg_types or loop_vars.get(k) in method.args:
                result[loop_vars[k]] = f"[{v}]"
            else:
                result[k] = v
        return result

    def walk(stmts: list[ast.stmt], loop_vars: dict[str, str] | None = None) -> None:
        lv: dict[str, str] = loop_vars or {}
        for stmt in stmts:
            if isinstance(stmt, ast.If):
                cond = stmt.test
                when_name = _condition_to_name(cond)
                inputs = _lift_loop_overrides(
                    _condition_to_inputs(cond, method.arg_types), lv
                )

                for child in stmt.body:
                    if isinstance(child, ast.Raise):
                        exc = _exc_short(child.exc)
                        exc_msg = None
                        if isinstance(child.exc, ast.Call) and child.exc.args:
                            first = child.exc.args[0]
                            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                                import re as _re
                                exc_msg = _re.escape(first.value[:60])
                        cases.append(BranchCase(
                            test_name=_truncate_test_name(f"raise{exc}_when{when_name}"),
                            input_overrides=inputs,
                            mock_side_effect=None,
                            mock_return_override=None,
                            expected_exception=exc,
                            expected_return=None,
                            is_happy_path=False,
                            expected_exception_match=exc_msg,
                        ))
                        cases.extend(
                            _boundary_cases_from_condition(cond, method.arg_types, exc)
                        )
                    elif isinstance(child, ast.Return) and child.value is not None:
                        ret_s = ast.unparse(child.value)
                        ret_label = "None" if ret_s == "None" else _camel(
                            re.sub(r"[^a-zA-Z0-9]", "_", ret_s[:24])
                        )
                        cases.append(BranchCase(
                            test_name=_truncate_test_name(f"return{ret_label}_when{when_name}"),
                            input_overrides=inputs,
                            mock_side_effect=None,
                            mock_return_override="None" if ret_s == "None" else None,
                            expected_exception=None,
                            expected_return=ret_s,
                            is_happy_path=False,
                        ))

                # Recurse into nested statements in the if-body (nested ifs, loops, with)
                walk([c for c in stmt.body if not isinstance(c, (ast.Raise, ast.Return))], lv)

                if stmt.orelse:
                    walk(stmt.orelse, lv)

            elif isinstance(stmt, ast.Try):
                for handler in stmt.handlers:
                    caught = ast.unparse(handler.type) if handler.type else "Exception"
                    caught_short = caught.split(".")[-1]
                    for child in handler.body:
                        if isinstance(child, ast.Raise):
                            raised = _exc_short(child.exc) if child.exc else caught_short
                            cases.append(BranchCase(
                                test_name=_truncate_test_name(
                                    f"raise{raised}_whenDependencyRaises{caught_short}"
                                ),
                                input_overrides={},
                                mock_side_effect=caught_short,
                                mock_return_override=None,
                                expected_exception=raised,
                                expected_return=None,
                                is_happy_path=False,
                            ))
                # Recurse into try-body for nested control flow
                walk(stmt.body, lv)

            elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                # Track loop variable → iterable source for inner-condition lifting
                new_lv = dict(lv)
                if (isinstance(stmt.target, ast.Name)
                        and isinstance(stmt.iter, ast.Name)
                        and stmt.iter.id in method.args):
                    new_lv[stmt.target.id] = stmt.iter.id
                walk(stmt.body, new_lv)

            elif isinstance(stmt, ast.While):
                walk(stmt.body, lv)

            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                walk(stmt.body, lv)

    walk(node.body)

    happy_return = _infer_bool_return_for_happy_path(cases)
    cases.append(BranchCase(
        test_name="",
        input_overrides={},
        mock_side_effect=None,
        mock_return_override=None,
        expected_exception=None,
        expected_return=happy_return,
        is_happy_path=True,
    ))

    return cases
