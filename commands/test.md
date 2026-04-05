# /test — Auto Test Generator (Python · pytest · 90%+ coverage)

Generate a complete, high-coverage pytest test file for the specified Python source file.

> **Language support**: Python only (`.py` files). AST-based branch analysis, type inference, and DI detection.

## Usage

```
/test <file.py>                          # unit tests, standard mode
/test <file.py> --integration            # integration tests (tests/integration/)
/test <file.py> --api                    # API endpoint tests (FastAPI / Flask)
/test <file.py> --mode minimal           # branches + happy path only
/test <file.py> --mode exhaustive        # all strategies (pairwise, extreme, hypothesis…)
/test <file.py> --execute-capture        # [opt-in] capture real return values for exact assertions
COVERAGE_THRESHOLD=80 /test <file.py>   # override coverage threshold
```

## Test generation modes

| Mode | Strategies |
|------|-----------|
| `minimal` | explicit raise/return branches + happy path |
| `standard` (default) | + boundary values, null combos, default args, enum exhaustion |
| `exhaustive` | + pairwise, union types, extreme values, Hypothesis property tests |

## What this does

**Unit mode (default)**
1. Parse Python AST to extract methods, branches, type hints, and external deps
2. Generate tests with ALL external deps mocked, targeting ≥90% coverage
3. Assertion inference: literal returns, bool return patterns, dataclass fields, dep call args
4. Call Claude only for void/side-effect methods (`TODO:CLAUDE_FILL` bodies)
5. Run coverage — retry with Claude if threshold not met
6. If test file already exists, detect uncovered methods and append only those

**Integration mode (`--integration`)**
Tests written to `tests/integration/`. No mocks — real services required.

**API mode (`--api`)**
Detects FastAPI / Flask routes and generates status-code tests (200/201/404/422/401/500).

**`--execute-capture`**
Imports and executes the module to capture actual return values for exact assertions.
⚠️ WARNING: triggers module-level code (DB connections, env vars, decorators). Use with care.

## Arguments

- `$ARGUMENTS` — path to the `.py` source file (required)

## Execution

!COVERAGE_THRESHOLD=90 ~/.claude/scripts/test-generator.sh $ARGUMENTS
