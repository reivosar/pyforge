# test-code-generator

Claude Code `/test` slash command — automatically generates pytest test files for Python source code.  
Static analysis first. Claude is only used for void/side-effect method bodies and coverage retry.

> **Python only.** Full AST-based analysis: branch coverage, type inference, DI detection.

---

## Installation

```bash
cp scripts/test-generator.py scripts/test-generator.sh ~/.claude/scripts/
cp -r scripts/tgen ~/.claude/scripts/
cp commands/test.md ~/.claude/commands/
chmod +x ~/.claude/scripts/test-generator.sh
```

---

## Usage

```bash
/test <file.py>                          # unit tests, standard mode
/test <file.py> --integration            # integration tests (tests/integration/)
/test <file.py> --api                    # API endpoint tests (FastAPI / Flask)
/test <file.py> --mode minimal           # branches + happy path only
/test <file.py> --mode exhaustive        # all strategies
/test <file.py> --execute-capture        # opt-in: capture real return values
COVERAGE_THRESHOLD=80 /test <file.py>   # override coverage threshold
```

---

## Test Generation Modes

| Mode | Strategies |
|------|-----------|
| `minimal` | explicit raise/return branches + happy path |
| `standard` *(default)* | + boundary values, null combos, default args, enum exhaustion |
| `exhaustive` | + pairwise, union types, extreme values, Hypothesis property tests |

---

## What Gets Generated

### Branch & Path Coverage
| Feature | Description |
|---|---|
| AST branch analysis | `if/elif/else`, `try/except` → one test per execution path |
| Boundary value tests | `x > N` → x=N (safe) + x=N+1 (fail); chained `0 < x < 10` → 4 boundary points |
| `len` boundary tests | `len(arg) > N` → string/list variants at N−1, N, N+1 |
| Bool return inference | `if cond: return False` pattern → happy-path gets `assert result is True` |
| Exception message matching | `raise ValueError("msg")` → `pytest.raises(..., match=r"msg")` |

### Input Value Coverage
| Feature | Description |
|---|---|
| Null combinations | One test per `Optional`/untyped arg set to `None` (2+ args) |
| Enum exhaustion | Detects `Enum` subclasses → one test per member |
| Pairwise tests | 3+ args → greedy minimum pair coverage (3 values per arg) |
| Default argument variation | Test with explicit default + non-default alternate |
| Union type cases | `Union[str, bytes]` → one test per concrete member |
| Int extreme values | `sys.maxsize` / `-(sys.maxsize+1)` / `0` |
| Float special values | `inf` / `-inf` / `nan` / `-0.0` |
| String special values | `""` / `"\x00"` / `"a"*10000` / unicode |
| Untyped arg edge values | No type hint → `None` / `""` / `0` / `[]` / `{}` |
| Loop-inner boundary lift | `for item in items: if item > N:` → `items=[N+1]` input override |
| Opaque condition inputs | `if validate(x):` → type-sample value for each Name arg |
| Hypothesis property tests | `@given` + type hints → auto strategy mapping |

### Assertion Inference (priority chain)
1. `pytest.raises(Exc, match=r"...")` for explicit raise branches (message extracted from AST)
2. `assert result is None` when return is `None`
3. `assert result is True/False` for bool return patterns
4. `assert result == <captured>` when `--execute-capture` is used
5. `assert result == <literal>` for `return {"ok": True}` / `return 0` patterns
6. Dataclass field assertions when return type matches a local class
7. `isinstance(result, X)` for known return types
8. `assert result is not None  # TODO:CLAUDE_FILL verify exact value` fallback

### Dependency Injection
| Feature | Description |
|---|---|
| Constructor DI detection | `self.x = x` in `__init__` → `sut = Cls(x=MagicMock())` |
| Non-deterministic patches | `datetime.now` / `random.random` / `uuid.uuid4` / `os.environ` → auto `@patch` |
| DB framework mocks | SQLAlchemy, Django ORM, psycopg2, pymongo, motor, redis, boto3 |
| Dep call assertions | `self.dep.save(user)` → `mock_dep.save.assert_called_once_with(user)` |
| Static/classmethod isolation | Deps unused by static methods are excluded from `@patch` decorators |

### API Tests (`--api`)
| Framework | Generated patterns |
|---|---|
| FastAPI / Flask | 200/201, 404, 422, 401 per endpoint |

---

## Test Naming Convention

```
<Result>_when<Condition>
```

Examples:
- `raiseValueError_whenUserIdIsZeroOrNegative`
- `returnUser_whenGetUserCalledWithValidArgs`
- `complete_whenStatusIsACTIVE`
- `complete_pairwiseComb1_UserIdStatusName`

Names are automatically truncated to 80 characters.

---

## Project Structure

```
scripts/
├── test-generator.py       # thin CLI orchestrator (~200 lines)
├── test-generator.sh       # bash wrapper
└── tgen/
    ├── models.py            # BranchCase, MethodInfo, ClassInfo, SourceInfo
    ├── analysis/
    │   └── python_ast.py    # AST analysis, detect_lang, project_root
    ├── cases/
    │   ├── branch.py        # analyze_method_branches, boundary cases
    │   ├── combinatorial.py # null, enum, pairwise, defaults, union
    │   ├── extreme.py       # extreme values, Hypothesis tests
    │   └── __init__.py      # generate_cases() + TIER_GENERATORS
    ├── renderers/
    │   ├── pytest_renderer.py  # generate_python_test_file
    │   └── api_renderer.py     # FastAPI/Flask API test generation
    ├── runtime/
    │   └── capture.py       # opt-in execute-and-capture
    └── coverage.py          # run_coverage, resolve_test_path
```

---

## Coverage

Default threshold: 90%. If not met, Claude adds tests for missing branches.

```bash
COVERAGE_THRESHOLD=80 /test path/to/file.py
```

---

## Python Dependencies

```bash
pip install pytest pytest-cov hypothesis pytest-asyncio
```
