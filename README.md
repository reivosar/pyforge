# test-code-generator

Claude Code `/test` slash command — automatically generates test code for a specified source file.  
Static analysis first. Claude is only used for void/side-effect method bodies and coverage retry.

---

## Installation

```bash
cp scripts/test-generator.py scripts/test-generator.sh ~/.claude/scripts/
cp commands/test.md ~/.claude/commands/
chmod +x ~/.claude/scripts/test-generator.sh
```

---

## Usage

```
/test <file_path>               # unit tests (external deps mocked)
/test <file_path> --integration # integration tests (real services)
/test <file_path> --api         # API/HTTP endpoint tests
```

---

## What Gets Generated

### Branch & Path Coverage
| Feature | Description |
|---|---|
| AST branch analysis (Python) | `if/elif/else`, `try/except` → one test per execution path |
| Regex branch analysis (TS/Go/Java) | `throw` / `return null` / `catch-rethrow` patterns |
| Boundary value tests | `x > N` → x=N (safe side) + x=N+1 (raises side); `len` boundaries too |

### Input Value Coverage
| Feature | Description |
|---|---|
| Null combinations | One test per `Optional`/untyped arg set to `None` (2+ args only) |
| Enum exhaustion | Detects `Enum` subclasses in file → one test per member |
| Pairwise tests | 3+ args → greedy minimum pair coverage |
| Default argument variation | Test with explicit default + non-default alternate value |
| Union type cases | `Union[str, bytes]` → one test per concrete member type |
| Int extreme values | `sys.maxsize` / `-(sys.maxsize+1)` / `0` |
| Float special values | `inf` / `-inf` / `nan` / `-0.0` |
| String special values | `""` / `"\x00"` / `"a"*10000` / `"日本語テスト"` (unicode) |
| Hypothesis property tests | `@given` + type hint → strategy auto-mapping (`st.integers()` etc.) |

### Code Structure Support
| Feature | Description |
|---|---|
| Multi-class files | Generates a separate `TestXxx:` class per source class |
| async/await | `async def` → `@pytest.mark.asyncio` + `await` on every call |
| staticmethod / classmethod | Calls as `ClassName.method()` — no instance needed |
| Constructor DI | Detects `self.x = x` in `__init__` → `sut = Cls(x=MagicMock())` |

### Dependencies & External Resources
| Feature | Description |
|---|---|
| Non-deterministic mock injection | AST scan detects `datetime.now` / `random.random` / `uuid.uuid4` / `os.environ` / `open` → auto `@patch` |
| DB framework mocks | SQLAlchemy / Django ORM / psycopg2 / pymongo / motor / redis / boto3 / TypeORM / Prisma / mongoose / GORM etc. |
| Execute & capture | Actually runs the function with mocked deps → captures return value as expected value (Python only) |

### API Tests (`--api`)
| Framework | Generated patterns |
|---|---|
| FastAPI / Flask / Express / NestJS / Gin / Spring | 200/201, 404, 422, 401, 500 per endpoint |

---

## Test Naming Convention

```
<Result>_when<Condition>
```

Examples:
- `raiseValueError_whenUserIdIsZeroOrNegative`
- `returnDict_whenGetUserCalledWithValidArgs`
- `complete_whenStatusIsACTIVE`
- `complete_whenQueryIsNullByte`
- `complete_pairwiseComb1_UserIdStatusName`

---

## Test Structure

Every test uses `# When` / `# Then` comments:

```python
def raiseValueError_whenUserIdIsZeroOrNegative(self):
    # When / Then
    with pytest.raises(ValueError):
        sut.get_user(user_id=-1)
```

```python
@pytest.mark.asyncio
async def returnDict_whenGetUserCalledWithValidArgs(self):
    # When
    result = await sut.get_user(user_id=1)

    # Then
    assert result is not None
```

```python
@patch('datetime.datetime')
def returnStr_whenTimeBasedCalledWithValidArgs(self, mock_datetime_datetime):
    mock_datetime_datetime.return_value = MagicMock()

    # When
    result = sut.time_based()

    # Then
    assert result is not None
```

---

## Language Support

| Language | Test Framework | Analysis |
|---|---|---|
| Python | pytest | Full AST |
| TypeScript / JavaScript | jest / vitest / mocha | regex |
| Go | testing | regex |
| Java | JUnit5 / JUnit4 | regex |
| Ruby | RSpec / minitest | regex |

---

## Coverage

Default threshold: 90%. If not met, Claude adds tests for missing branches.

```bash
COVERAGE_THRESHOLD=80 /test path/to/file.py  # override threshold
```

---

## Python Dependencies

```bash
pip install pytest pytest-cov hypothesis pytest-asyncio
```
