# /test — Auto Test Generator (90%+ coverage)

Generate a complete, high-coverage test file for the specified source file.

## Usage

```
/test <file_path>               # unit tests (external deps mocked)
/test <file_path> --integration # integration tests (real services)
/test <file_path> --api         # API/HTTP endpoint tests
```

## What this does

**Unit mode (default)**
1. Detect language and test framework automatically
2. Analyze existing tests to match coding style
3. Generate tests with ALL external deps mocked, targeting ≥90% coverage
4. Run coverage — retry with targeted additions if threshold not met
5. If test file already exists, detect new uncovered methods and append only those

**Integration mode (--integration)**
1. Detect integration test libraries already in the project (Testcontainers, supertest, etc.)
2. Generate tests that hit REAL external services — no mocks
3. Include setup/teardown for data isolation per test
4. Output includes instructions for required env vars and how to run

## Arguments

- `$ARGUMENTS` — path to the source file to test (required)

## Execution

!COVERAGE_THRESHOLD=90 ~/.claude/scripts/test-generator.sh $ARGUMENTS
