# pyforge

100% static analysis test auto-generator for Python. AST-based branch coverage, type inference, and dependency injection detection. **Zero AI dependencies. Pure stdlib.**

Generate comprehensive pytest test suites from your Python source code using only static analysis—no external services, no hallucinations, no network calls.

---

## Two Usage Modes

pyforge can be used in two ways:

### 1. **Command-Line Interface (CLI)** — Standard Usage

```bash
pyforge src/mymodule.py
```

Generate tests directly from the terminal. Tests are written to disk. Perfect for local development and CI/CD pipelines.

**Commands:**
- `pyforge <file>` — Generate unit tests
- `pyforge <dir>` — Batch process entire directory
- `pyforge --api` — Generate API endpoint tests
- `pyforge --db-integration` — Generate database integration tests

### 2. **MCP Server** — IDE Integration

```bash
pyforge-mcp
```

Run pyforge as a background service for Claude Desktop, Cursor, or other MCP clients. Exposes 4 tools: `analyze_file`, `dry_run`, `generate_tests`, `run_coverage_check`.

Use this when you want to invoke test generation from within your IDE or AI assistant.

---

## Installation

### Basic Installation

```bash
pip install -e .
```

### With MCP Server Support

```bash
pip install "pyforge[mcp]"
```

### Development (with test dependencies)

```bash
pip install -e .
pip install pytest pytest-cov hypothesis pytest-asyncio
```

#### Optional: Database Integration Tests

```bash
# For SQLAlchemy support
pip install factory-boy sqlalchemy

# For PostgreSQL via testcontainers
pip install testcontainers psycopg2-binary

# For Django
pip install pytest-django
```

---

## Quick Start

```bash
# Generate tests for a single file (standard mode)
pyforge src/mymodule.py

# Preview output without writing
pyforge src/mymodule.py --dry-run

# Generate API endpoint tests (FastAPI / Flask)
pyforge src/api.py --api

# Batch process entire directory
pyforge src/
```

The generated test file is written to `tests/test_<filename>.py` by default.

---

## CLI Reference

### Full Flag List

| Flag | Default | Description |
|---|---|---|
| `target` | required | Python file or directory to process |
| `--mode {minimal,standard,exhaustive}` | `standard` | Test generation strategy |
| `--integration` | `False` | Write to `tests/integration/` instead of `tests/` |
| `--api` | `False` | Generate FastAPI / Flask HTTP endpoint tests |
| `--db-integration` | `False` | Append real-DB integration tests + generate `conftest.py` |
| `--coverage N` | `90` | Coverage threshold % (`COVERAGE_THRESHOLD` env var also works) |
| `--dry-run` | `False` | Print to stdout, don't write files, skip coverage check |
| `--execute-capture` | `False` | Import module and capture real return values (opt-in execution) |
| `-y, --yes` | `False` | Skip confirmation prompts (CI-safe) |

### Examples

```bash
# Minimal test generation (only explicit branches + happy path)
pyforge src/service.py --mode minimal

# Exhaustive testing with property tests
pyforge src/service.py --mode exhaustive

# Lower coverage threshold to 70%
pyforge src/service.py --coverage 70

# Override via environment variable
COVERAGE_THRESHOLD=80 pyforge src/service.py

# Batch process directory with confirmation suppression
pyforge src/ --yes

# Generate tests + integration DB fixtures
pyforge src/user_repo.py --db-integration

# Skip writing, just output to console
pyforge src/service.py --dry-run | head -50

# Capture real return values during test generation
pyforge src/utils.py --execute-capture
```

### Directory Processing

```bash
# Process all Python files in src/ recursively
pyforge src/
```

Each file gets its own test file in the same relative location under `tests/`.

---

## Test Generation Modes

| Mode | Strategies Included |
| --- | --- |
| `minimal` | Explicit raise/return branches + happy path only |
| `standard` *(default)* | minimal + boundary values, null combinations, default arg variants, full enum member enumeration |
| `exhaustive` | standard + pairwise parameter combinations, union type variants, extreme numeric/string values, Hypothesis property tests |

**Mode Selection Guide:**
- **minimal**: Quick iteration, baseline coverage
- **standard**: Recommended for most projects; catches most bugs
- **exhaustive**: Critical business logic, security-sensitive code, maximum confidence

---

## Generated Tests: Features & Coverage

### Branch & Path Coverage

| Feature | What Gets Tested |
| --- | --- |
| **AST branch analysis** | `if/elif/else`, `try/except` — one test per execution path |
| **Boundary value tests** | Condition `x > N` generates tests at `x=N` (safe boundary) and `x=N+1` (fail case); chained `0 < x < 10` produces 4 test points |
| **`len()` boundary tests** | For `len(arg) > N`, generates string and list variants at N-1, N, N+1 |
| **Bool return inference** | Pattern `if condition: return False` → happy-path gets `assert result is True` |
| **Exception message matching** | `raise ValueError("field required")` → `pytest.raises(..., match=r"field required")` |

### Input Value Coverage

| Feature | What Gets Tested |
| --- | --- |
| **Null combinations** | Optional/untyped args set to `None` (generates one test per arg when 2+ args exist) |
| **Enum exhaustion** | Detects `Enum` subclasses — one test per member value |
| **Pairwise tests** | 3+ parameters → greedy minimum pair coverage (tests all 2-way combinations) |
| **Default argument variation** | One test with default value, one with non-default override |
| **Union type cases** | `Union[str, bytes]` → one test per concrete type member |
| **Integer extreme values** | `sys.maxsize`, `-(sys.maxsize+1)`, `0` |
| **Float special values** | `inf`, `-inf`, `nan`, `-0.0` |
| **String special values** | `""`, `"\x00"` (null byte), `"a"*10000` (long), unicode chars |
| **Untyped arg edge cases** | No type hint → auto-generates tests with `None`, `""`, `0`, `[]`, `{}` |
| **Loop inner boundaries** | Pattern `for item in items: if item > N:` → generates override `items=[N+1]` |
| **Opaque function conditions** | `if validate(x):` → generates type-sampled values for opaque functions |
| **Hypothesis property tests** | `@given` decorators with auto-mapped `hypothesis.strategies` |
| **Type inference from usage** | Infers types from comparisons (`x > 0` → `int`), method calls (`x.strip()` → `str`), arithmetic, iteration |

### Assertion Inference (Priority Chain)

Tests select assertions in this order:

1. **`pytest.raises(Exc, match=r"...")`** — for explicit raise branches
2. **`assert result is None`** — when return type is `None`
3. **`assert result is True / False`** — when method has bool return pattern
4. **`assert result == <captured>`** — when `--execute-capture` captured a real return value
5. **`assert result == <literal>`** — for direct literal returns like `return {"ok": True}`
6. **Dataclass field assertions** — when return type is a known dataclass
7. **`isinstance(result, TargetClass)`** — for typed returns
8. **`assert result is not None`** — fallback when type cannot be inferred

### Dependency Injection & Mocking

| Feature | Behavior |
| --- | --- |
| **Constructor DI detection** | Pattern `self.x = x` in `__init__` → generates `sut = ClassName(x=MagicMock())` |
| **Non-deterministic patches** | Auto-detects `datetime.now()`, `random.random()`, `uuid.uuid4()`, `os.environ` calls → auto-patches them |
| **DB framework mocks** | SQLAlchemy, Django ORM, psycopg2, pymongo, motor, redis, boto3 → appropriate mock setup |
| **Dependency call assertions** | `self.repo.save(user)` → generates `mock_repo.save.assert_called_once_with(user)` |
| **Local alias tracking** | `repo = self.repository; repo.delete(x)` → correctly tracks alias → `mock_repository.delete.assert_called_once_with(x)` |
| **Static/classmethod isolation** | Unused dependencies automatically excluded from `@patch` decorators |

### Incremental Test Updates

When you run pyforge on a file that already has a test file:
- Existing tests are preserved
- Only methods/classes without test coverage are added
- The tool warns which methods need tests

---

## API Tests (`--api`)

Generate HTTP endpoint tests for FastAPI and Flask applications.

### Supported Frameworks

| Framework | Detection | Generated Tests |
| --- | --- | --- |
| **FastAPI** | Loads OpenAPI schema dynamically; falls back to `@app.get/@app.post` AST parsing | 200 (success), 4xx (validation failures), 5xx (server errors) per endpoint |
| **Flask** | AST parsing of `@app.route(...)` decorators | 200 (success), 404 (not found) per route |

### How It Works

1. Try to dynamically load FastAPI OpenAPI schema via `importlib`
2. Extract endpoint paths, request bodies, response schemas, status codes
3. Generate test cases for each HTTP method/path combination
4. If OpenAPI unavailable, fall back to AST decorator parsing
5. If both fail, generate a failing stub test with clear error message

### Example

```bash
pyforge src/api.py --api
# Generates: tests/test_api.py with full HTTP endpoint coverage
```

---

## Database Integration Tests (`--db-integration`)

### When to Use

Use `--db-integration` when your code has database dependencies (SQLAlchemy, Django ORM, psycopg2, etc.) and you want real-database test fixtures.

```bash
pyforge src/user_repository.py --db-integration
```

### What Gets Generated

1. **Integration Test Class** — appended to existing test file
   - Real database connection (not mocked)
   - Transactional rollback between tests for isolation
   - factory_boy factories for ORM models

2. **conftest.py** — creates session/function-scoped fixtures
   - DB engine, session, connection pools
   - Backend-specific setup (SQLite, PostgreSQL, Django)

### Supported Backends

#### SQLAlchemy

```python
# Generated conftest.py fixture usage:
def test_save_user(db_session):
    # db_session is a real SQLAlchemy session
    # Automatically rolls back after test
    repo = UserRepository(db_session)
    user = repo.create_user("alice@example.com")
    assert user.id is not None
```

- **Engine**: SQLite in-memory database
- **Isolation**: function-scoped rollback via savepoints
- **Fixture**: `db_session` (function-scoped), `db_engine` (session-scoped)

#### PostgreSQL (psycopg2)

```bash
pip install testcontainers psycopg2-binary
```

- **Engine**: Testcontainers-managed PostgreSQL container
- **Isolation**: function-scoped rollback via transactions
- **Fixture**: `pg_container`, `pg_conn`
- **Lifecycle**: Container starts once per session, cleans up at end

#### Django

```python
# Generated conftest.py:
import pytest

@pytest.fixture
def django_db_setup():
    # Use pytest-django defaults
    pass
```

- **Fixture**: pytest-django `db` fixture
- **Isolation**: Django's transaction rollback per test
- **Usage**: Mark with `@pytest.mark.django_db`

### factory_boy Model Factories

Automatically generates factories for all detected ORM models:

```python
# For a SQLAlchemy model:
class User(Base):
    id: int
    email: str
    name: str
    created_at: datetime

# Generated factory:
class UserFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session = db_session  # injected from fixture

    id = factory.Sequence(lambda n: n)
    email = factory.Faker("email")
    name = factory.Faker("name")
    created_at = factory.LazyFunction(datetime.utcnow)
```

Fields are auto-mapped based on name:
- `email`, `user_email` → `factory.Faker("email")`
- `name`, `full_name` → `factory.Faker("name")`
- `created_at`, `updated_at` → `factory.LazyFunction(datetime.utcnow)`
- `id`, `pk` → `factory.Sequence(...)`
- Others → `factory.LazyFunction(lambda: "default")`

### Example: Full Integration Test Flow

```bash
# Before: src/user_service.py has UserRepository with SQLAlchemy
pyforge src/user_service.py --db-integration

# After: two files created/updated:
#   tests/test_user_service.py    (appended with TestUserServiceIntegration)
#   tests/conftest.py             (new, with db_session fixture)

# Running tests:
pytest tests/test_user_service.py::TestUserServiceIntegration -v
```

---

## MCP Server (`pyforge-mcp`)

Expose pyforge as a tool server for Claude Desktop, Cursor, or other MCP clients.

### Installation & Launch

```bash
pip install "pyforge[mcp]"
pyforge-mcp
```

Server listens on stdio and exposes 4 tools.

### Tools

| Tool | Input | Output | Use Case |
|---|---|---|---|
| `analyze_file` | file path | JSON: `{module_path, classes, methods, external_deps, api_framework}` | Understand code structure without generating tests |
| `dry_run` | file path, mode, coverage threshold | Plain text: generated test file | Preview tests before writing |
| `generate_tests` | file path, mode, coverage threshold | JSON: `{test_file, action, methods_added}` | Generate and write tests; action is `created`, `updated`, or `skipped` |
| `run_coverage_check` | file path, coverage threshold | JSON: `{status, threshold, uncovered_methods, output}` | Run coverage and list uncovered methods |

### Tool Details

#### `analyze_file(target: str)`

Parses Python file without generating tests. Returns JSON:

```json
{
  "module_path": "src/user_service.py",
  "class_name": "UserService",
  "classes": [
    {
      "name": "UserService",
      "methods": [
        {"name": "create_user", "args": ["email"], "return_type": "User"}
      ]
    }
  ],
  "external_deps": ["sqlalchemy", "pydantic"],
  "api_framework": null
}
```

#### `dry_run(target: str, mode: str = "standard", coverage: int = 90)`

Generates test file content without writing to disk:

```
Returns the full pytest source code as a string.
Use to preview before committing.
```

#### `generate_tests(target: str, mode: str = "standard", coverage: int = 90)`

Generates tests and writes to disk. Returns JSON:

```json
{
  "test_file": "tests/test_user_service.py",
  "action": "created",
  "methods_added": 12
}
```

Actions:
- `"created"` — new test file
- `"updated"` — appended to existing test file
- `"skipped"` — coverage already met

#### `run_coverage_check(target: str, threshold: int = 90)`

Runs pytest with coverage and returns JSON:

```json
{
  "status": "pass",
  "threshold": 90,
  "uncovered_methods": [],
  "output": "... pytest-cov output ..."
}
```

Or if coverage fails:

```json
{
  "status": "fail",
  "threshold": 90,
  "uncovered_methods": ["calculate_tax", "validate_email"],
  "output": "... pytest-cov output ..."
}
```

### Configuration

To use pyforge-mcp with Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "tools": {
    "pyforge": {
      "command": "pyforge-mcp"
    }
  }
}
```

---

## Python Library API

Use pyforge as a Python library to integrate into your own tools and scripts.

### Installation

```bash
pip install pyforge
```

### Core Functions

```python
from pyforge import (
    # Analysis
    analyze_python,
    detect_enum_types,
    project_root,
    
    # Generation
    generate_cases,
    generate_python_test_file,
    generate_api_tests,
    detect_api_framework,
    generate_db_integration_block,
    
    # Coverage
    run_coverage,
    resolve_test_path,
    resolve_api_test_path,
    find_uncovered_methods,
    parse_missing_lines,
    
    # Data types
    SourceInfo,
    ClassInfo,
    MethodInfo,
    BranchCase,
    DepInfo,
    OrmModelInfo,
)
```

### Function Reference

| Function | Signature | Purpose |
|---|---|---|
| `analyze_python(target: Path, root: Path)` | → `SourceInfo` | Parse Python file: classes, methods, types, dependencies |
| `detect_enum_types(target: Path)` | → `dict[str, list[str]]` | Find all Enum subclasses and their members |
| `project_root(path: Path)` | → `Path` | Locate project root (git, pyproject.toml, setup.py) |
| `generate_cases(method: MethodInfo, src_info: SourceInfo, mode: str, enum_types: dict)` | → `list[BranchCase]` | Generate test cases from method analysis |
| `generate_python_test_file(target, root, src_info, coverage, mode, execute_capture)` | → `str` | Generate pytest file as string (no disk write) |
| `generate_api_tests(source: str, framework: str, module_path: str, source_path: Path)` | → `str` | Generate API endpoint tests |
| `detect_api_framework(source: str)` | → `str \| None` | Return `"fastapi"`, `"flask"`, or `None` |
| `generate_db_integration_block(target, root, src_info)` | → `tuple[str, str]` | Return `(test_class, conftest_content)` |
| `run_coverage(test_path: Path, root: Path, threshold: int, target: Path)` | → `tuple[bool, str]` | Run pytest --cov; return (success, stdout) |
| `resolve_test_path(target, root, integration)` | → `Path` | Compute output test file path |
| `resolve_api_test_path(target, root)` | → `Path` | Compute API test file path |
| `find_uncovered_methods(src_info, test_file)` | → `list[MethodInfo]` | Return methods not yet tested |
| `parse_missing_lines(stdout: str, rel_path: str)` | → `set[int]` | Extract uncovered line numbers from coverage output |

### Data Types Reference

| Type | Key Fields | Purpose |
|---|---|---|
| `SourceInfo` | `lang`, `class_name`, `methods`, `all_classes`, `external_deps`, `module_path` | Parsed file contents |
| `ClassInfo` | `name`, `methods`, `constructor_dep_map` | Parsed class |
| `MethodInfo` | `name`, `args`, `arg_types`, `return_type`, `is_void`, `is_async`, `raises` | Parsed method signature |
| `BranchCase` | `test_name`, `input_overrides`, `expected_exception`, `expected_return`, `is_happy_path` | Single test case spec |
| `DepInfo` | `module`, `name`, `alias` | External dependency |
| `OrmModelInfo` | `class_name`, `db_type`, `column_attrs` | Detected ORM model |

### Code Examples

#### Example 1: Analyze a File

```python
from pathlib import Path
from pyforge import analyze_python, project_root

target = Path("src/user_service.py").resolve()
root = project_root(target)
info = analyze_python(target, root)

print(f"Classes: {[c.name for c in info.all_classes]}")
print(f"Methods: {[m.name for m in info.methods]}")
print(f"Dependencies: {[d.name for d in info.external_deps]}")
```

#### Example 2: Generate Test File Content

```python
from pyforge import analyze_python, generate_python_test_file, project_root

target = Path("src/utils.py").resolve()
root = project_root(target)
info = analyze_python(target, root)

test_code = generate_python_test_file(
    target=target,
    root=root,
    info_=info,
    coverage=80,
    mode="exhaustive",
    execute_capture=False,
)

print(test_code)
```

#### Example 3: Run Coverage Check

```python
from pyforge import run_coverage, resolve_test_path, analyze_python, project_root

target = Path("src/service.py").resolve()
root = project_root(target)
test_path = resolve_test_path(target, root, integration=False)

success, output = run_coverage(test_path, root, threshold=90, target=target)

if not success:
    print("Coverage below threshold:")
    print(output)
```

#### Example 4: Find Uncovered Methods

```python
from pyforge import analyze_python, find_uncovered_methods, project_root

target = Path("src/models.py").resolve()
root = project_root(target)
info = analyze_python(target, root)

uncovered = find_uncovered_methods(info, Path("tests/test_models.py"))
print(f"Missing tests for: {[m.name for m in uncovered]}")
```

---

## Test Naming Convention

Generated test names follow the pattern:

```
<Result>_when<Condition>
```

### Examples

- `raiseValueError_whenEmailIsEmpty`
- `returnUser_whenGetUserCalledWithValidId`
- `complete_whenStatusChanged`
- `deleteTodo_pairwiseComb1_UserIdStatusPriority`

Names are automatically truncated to 80 characters. Multi-word conditions are concatenated without spaces.

---

## Coverage

### Threshold

Default threshold is **90%**. If generated test coverage falls below this, pyforge will:
1. Print warning to console
2. List uncovered methods by name
3. Suggest running with `--mode exhaustive` for more tests

### Override Threshold

```bash
# Via flag
pyforge src/service.py --coverage 75

# Via environment variable
COVERAGE_THRESHOLD=75 pyforge src/service.py

# Flag takes precedence over env var
```

### Coverage File Locations

Generated test files are placed at:
- Default: `tests/test_<filename>.py`
- With `--integration`: `tests/integration/test_<filename>.py`

---

## Project Structure

```
pyforge/
├── __init__.py                      # Public library API re-exports
├── __main__.py                      # python -m pyforge entry point
├── cli.py                           # CLI orchestration and argument parsing
├── models.py                        # BranchCase, MethodInfo, ClassInfo, SourceInfo, DepInfo, OrmModelInfo
├── coverage.py                      # run_coverage, resolve_test_path, find_uncovered_methods
├── analysis/
│   └── python_ast.py               # Full AST analysis, type inference, ORM/Enum detection
├── cases/
│   ├── __init__.py                 # generate_cases() dispatcher + TIER_GENERATORS
│   ├── branch.py                   # analyze_method_branches() → BranchCase per path
│   ├── combinatorial.py            # null, enum, pairwise, defaults, union type generators
│   └── extreme.py                  # extreme values, Hypothesis property tests
├── renderers/
│   ├── pytest_renderer.py          # generate_python_test_file() → complete pytest module
│   ├── api_renderer.py             # FastAPI/Flask HTTP test generation
│   └── db_integration_renderer.py  # Real DB fixtures + conftest.py + factory_boy
├── runtime/
│   └── capture.py                  # try_execute_and_capture() — live execution (opt-in)
└── mcp_server.py                   # Optional MCP server with 4 exposed tools
```

---

## Dependencies

### Core Runtime

```
pytest
pytest-cov
```

### For Advanced Features

```
# Type inference and Hypothesis property tests
hypothesis
pytest-asyncio

# Database integration tests
factory-boy
sqlalchemy
testcontainers  # For PostgreSQL via Docker
psycopg2-binary  # PostgreSQL driver
pytest-django    # Django ORM support

# MCP server
mcp >= 1.0
```

### Installation Commands

**All in one (full-featured):**
```bash
pip install pytest pytest-cov hypothesis pytest-asyncio factory-boy sqlalchemy testcontainers psycopg2-binary pytest-django "mcp>=1.0"
```

**Per-use-case:**

```bash
# Just the basics
pip install pytest pytest-cov

# Add advanced strategies
pip install hypothesis pytest-asyncio

# Add database testing
pip install factory-boy sqlalchemy

# PostgreSQL container support
pip install testcontainers psycopg2-binary

# Django support
pip install pytest-django

# MCP server
pip install "mcp>=1.0"
```

---

## Troubleshooting

### "Coverage below 90%"

Run with `--mode exhaustive` for more comprehensive tests:

```bash
pyforge src/service.py --mode exhaustive
```

Or lower the threshold:

```bash
pyforge src/service.py --coverage 75
```

### "No tests generated"

Check that:
1. File has at least one class or function
2. Functions/methods have at least one branch or condition
3. Try `--mode exhaustive` to generate more cases

### "AttributeError: module has no attribute"

When using `--execute-capture`, ensure:
1. Module has no unresolved imports
2. Dependencies are installed
3. Consider using `-y` to skip interactive confirmation

### "testcontainers not found"

For PostgreSQL integration tests:

```bash
pip install testcontainers psycopg2-binary
```

---

## Examples

See `/examples/todo_app/` for a complete FastAPI + SQLAlchemy reference application with:
- ORM models (`models.py`)
- Async repository layer (`repository.py`)
- Business logic service (`service.py`)
- FastAPI endpoints with dependency injection (`api.py`)

Generate tests for this example:

```bash
# Unit tests with mocks
pyforge examples/todo_app/app/service.py

# API endpoint tests
pyforge examples/todo_app/app/api.py --api

# Database integration tests
pyforge examples/todo_app/app/repository.py --db-integration
```

---

## Contributing

Contributions welcome! The test suite covers:
- AST analysis (`tests/test_python_ast.py`)
- Branch analysis (`tests/test_branch.py`)
- Case generation (`tests/test_combinatorial.py`, `tests/test_extreme.py`)
- Rendering (`tests/test_pytest_renderer.py`)
- Coverage utilities (`tests/test_coverage_utils.py`)
- End-to-end integration (`tests/integration/`)

Run all tests:

```bash
pytest tests/ -v
```

---

## License

See LICENSE file.
