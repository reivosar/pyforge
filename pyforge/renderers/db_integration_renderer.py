"""DB integration test renderer — generates real-DB test classes and conftest.py fixtures."""
from __future__ import annotations

from pathlib import Path

from pyforge.analysis.python_ast import detect_orm_models
from pyforge.models import ClassInfo, DepInfo, OrmModelInfo, SourceInfo
from pyforge.renderers.pytest_renderer import _PYTHON_DB_MOCKS

# DB type priority order (same as _PYTHON_DB_MOCKS key order)
_DB_PREFIXES = list(_PYTHON_DB_MOCKS.keys())


# ── DB type detection ─────────────────────────────────────────────────────────

def detect_db_type(deps: list[DepInfo]) -> str | None:
    """Return the primary DB type string from external deps, or None."""
    for prefix in _DB_PREFIXES:
        if any(d.module.startswith(prefix) for d in deps):
            return prefix
    return None


# ── factory_boy factory generation ───────────────────────────────────────────

_FAKER_MAP = {
    "name": "name", "username": "user_name", "email": "email",
    "title": "sentence", "description": "text", "body": "text",
    "url": "url", "phone": "phone_number", "address": "address",
    "city": "city", "country": "country", "password": "password",
    "slug": "slug", "content": "text", "message": "text",
}
_PK_NAMES = {"id", "pk", "uuid", "guid"}


def _faker_for_attr(attr: str) -> str:
    for key, provider in _FAKER_MAP.items():
        if key in attr.lower():
            return f'factory.Faker("{provider}")'
    return 'factory.LazyFunction(lambda: "default")'


def _field_declaration(attr: str) -> str:
    lower = attr.lower()
    if lower in _PK_NAMES or lower.endswith("_id"):
        return "factory.Sequence(lambda n: n)"
    return _faker_for_attr(attr)


def generate_factory_boy_factories(
    orm_models: list[OrmModelInfo],
    module_path: str,
) -> list[str]:
    """Return lines of factory_boy factory class definitions."""
    if not orm_models:
        return []

    lines: list[str] = []
    for model in orm_models:
        factory_name = f"{model.class_name}Factory"
        if model.db_type == "sqlalchemy":
            lines += [
                f"class {factory_name}(factory.alchemy.SQLAlchemyModelFactory):",
                f"    class Meta:",
                f"        model = {model.class_name}",
                f"        sqlalchemy_session = None  # injected by db_session fixture",
                f"        sqlalchemy_session_persistence = 'flush'",
            ]
        elif model.db_type == "django":
            lines += [
                f"class {factory_name}(factory.django.DjangoModelFactory):",
                f"    class Meta:",
                f"        model = {model.class_name}",
            ]
        else:
            continue

        if model.column_attrs:
            lines.append("")
            for attr in model.column_attrs:
                lines.append(f"    {attr} = {_field_declaration(attr)}")
        lines.append("")
    return lines


# ── conftest.py generation ────────────────────────────────────────────────────

def _conftest_sqlalchemy(orm_models: list[OrmModelInfo], module_path: str) -> str:
    model_names = [m.class_name for m in orm_models]
    # deduplicate: Base may already be in model_names if the user defined their own Base
    seen: set[str] = set()
    import_names: list[str] = []
    for name in ["Base"] + model_names:
        if name not in seen:
            seen.add(name)
            import_names.append(name)
    imports = ", ".join(import_names)
    model_import_line = f"from {module_path} import {imports}  # adjust if models are elsewhere"

    factory_lines = generate_factory_boy_factories(orm_models, module_path)
    factory_block = "\n".join(factory_lines)

    get_factories_block = "\n".join([
        "def _get_all_factories():",
        '    """Return all SQLAlchemyModelFactory subclasses defined in this module."""',
        "    import inspect, sys",
        "    return [",
        "        cls for _, cls in inspect.getmembers(sys.modules[__name__], inspect.isclass)",
        "        if issubclass(cls, factory.alchemy.SQLAlchemyModelFactory)",
        "        and cls is not factory.alchemy.SQLAlchemyModelFactory",
        "    ]",
    ])

    return f'''\
"""
Real DB fixtures for integration tests (SQLAlchemy + SQLite in-memory).
Requires: pip install factory-boy sqlalchemy pytest
"""
from __future__ import annotations

import inspect
import sys

import factory
import factory.alchemy
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

{model_import_line}


@pytest.fixture(scope="session")
def db_engine():
    """SQLite in-memory engine — shared for the entire test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={{"check_same_thread": False}},
    )
    Base.metadata.create_all(engine)  # create all tables
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Session:
    """Transactional session — each test runs in a rolled-back transaction."""
    connection = db_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    # wire factory_boy factories to this session
    for factory_cls in _get_all_factories():
        factory_cls._meta.sqlalchemy_session = session

    yield session

    session.close()
    transaction.rollback()
    connection.close()


{get_factories_block}


# ── Factories ─────────────────────────────────────────────────────────────────

{factory_block}'''


def _conftest_psycopg2() -> str:
    return '''\
"""
Real PostgreSQL fixtures using testcontainers.
Requires: pip install testcontainers psycopg2-binary pytest
Docker must be running.
"""
from __future__ import annotations

import psycopg2
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:15-alpine") as pg:
        yield pg


@pytest.fixture(scope="function")
def pg_conn(pg_container):
    """Raw psycopg2 connection — rolled back after each test."""
    conn = psycopg2.connect(pg_container.get_connection_url())
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()
'''


def _conftest_django() -> str:
    return '''\
"""
Django integration test setup.
Requires: pip install pytest-django
Add to pytest.ini or pyproject.toml:
  [pytest]
  DJANGO_SETTINGS_MODULE = myproject.settings.test

pytest-django provides the `db` fixture automatically when
@pytest.mark.django_db is used — no additional conftest needed.
"""
'''


def generate_conftest(
    db_type: str,
    orm_models: list[OrmModelInfo],
    module_path: str,
) -> str:
    """Return conftest.py content string for the given DB type."""
    if db_type == "sqlalchemy":
        return _conftest_sqlalchemy(orm_models, module_path)
    if db_type == "psycopg2":
        return _conftest_psycopg2()
    if db_type == "django.db":
        return _conftest_django()
    # fallback: SQLAlchemy-style stub
    return _conftest_sqlalchemy(orm_models, module_path)


# ── integration test class generation ────────────────────────────────────────

def _session_fixture_name(db_type: str) -> str:
    if db_type == "psycopg2":
        return "pg_conn"
    if db_type == "django.db":
        return "db"
    return "db_session"


def _generate_method_tests(
    cls: ClassInfo,
    db_type: str,
    orm_models: list[OrmModelInfo],
    fixture: str,
) -> list[str]:
    lines: list[str] = []
    # prefer models that have column attrs for the primary factory
    entity_models = [m for m in orm_models if m.column_attrs] or orm_models
    model_names = [m.class_name for m in orm_models]
    primary_model = entity_models[0].class_name if entity_models else None
    primary_factory = f"{primary_model}Factory" if primary_model else None

    for method in cls.methods:
        test_name = f"test_{method.name}"

        # happy path
        lines += [
            f"    def {test_name}(self, {fixture}):",
        ]
        if primary_factory and db_type == "sqlalchemy":
            lines += [
                f"        # Arrange",
                f"        instance = {primary_factory}()",
            ]
        else:
            lines += [
                f"        # Arrange",
            ]

        # build constructor args from constructor_dep_map
        ctor_args = ", ".join(
            f"{attr}={fixture}" for attr in cls.constructor_dep_map
        ) if cls.constructor_dep_map else fixture
        lines += [
            f"        sut = {cls.name}({ctor_args})",
            f"",
            f"        # When",
        ]

        # build call args
        call_args = ", ".join(
            f"{arg}=None" for arg in method.args
        ) if method.args else ""
        if method.is_async:
            lines += [
                f"        import asyncio",
                f"        result = asyncio.run(sut.{method.name}({call_args}))",
            ]
        else:
            lines += [
                f"        result = sut.{method.name}({call_args})",
            ]

        # assertion
        if method.is_void:
            if primary_model and db_type == "sqlalchemy":
                lines += [
                    f"",
                    f"        # Then",
                    f"        assert {fixture}.query({primary_model}).count() >= 0  # verify DB state",
                ]
            else:
                lines += [
                    f"",
                    f"        # Then",
                    f"        pass  # assert side effects via {fixture}",
                ]
        else:
            lines += [
                f"",
                f"        # Then",
                f"        assert result is not None",
            ]

        lines.append("")

    return lines


def generate_integration_test_class(
    cls: ClassInfo,
    db_type: str,
    orm_models: list[OrmModelInfo],
    module_path: str,
) -> str:
    """Return TestXxxIntegration class source string."""
    fixture = _session_fixture_name(db_type)
    model_names = [m.class_name for m in orm_models]
    model_import = ""
    if model_names:
        model_import = f"from {module_path} import {', '.join(model_names)}\n"

    factory_lines = generate_factory_boy_factories(orm_models, module_path)
    factory_block = "\n".join(factory_lines)

    method_lines = _generate_method_tests(cls, db_type, orm_models, fixture)
    method_block = "\n".join(method_lines)

    django_marker = ""
    if db_type == "django.db":
        django_marker = "\n@pytest.mark.django_db"

    class_lines = [
        f"# ── DB Integration Tests ─────────────────────────────────────────────────────",
        f"# Requires: pip install factory-boy {'sqlalchemy pytest' if db_type == 'sqlalchemy' else 'pytest'}",
        f"",
        f"import factory",
        f"import factory.alchemy" if db_type == "sqlalchemy" else "import factory.django",
        f"import pytest",
    ]
    if model_import:
        class_lines.append(model_import.rstrip())
    class_lines += [
        f"",
        factory_block.rstrip(),
        f"",
        django_marker.lstrip("\n") if django_marker else "",
        f"class Test{cls.name}Integration:",
        f'    """Integration tests using real DB — fixtures provided by conftest.py."""',
        f"",
        method_block.rstrip(),
    ]

    return "\n".join(line for line in class_lines if line is not None)


# ── top-level entry point ─────────────────────────────────────────────────────

def generate_db_integration_block(
    target: Path,
    root: Path,
    info_: SourceInfo,
) -> tuple[str, str]:
    """Return (integration_test_block, conftest_content).

    Returns ("", "") if no DB dependencies are detected.
    """
    db_type = detect_db_type(info_.external_deps)
    if not db_type:
        return "", ""

    raw_models = detect_orm_models(target)
    # Filter out abstract base classes (no columns, name ends in "Base" or is "Base")
    orm_models = [
        m for m in raw_models
        if m.column_attrs or not (m.class_name == "Base" or m.class_name.endswith("Base"))
    ]
    orm_model_names = {m.class_name for m in raw_models}  # use raw for service-class exclusion

    # Pick first class that is not itself an ORM model
    service_classes = [c for c in info_.all_classes if c.name not in orm_model_names]
    if not service_classes:
        return "", ""

    cls = service_classes[0]
    conftest = generate_conftest(db_type, orm_models, info_.module_path)
    integration_block = generate_integration_test_class(
        cls, db_type, orm_models, info_.module_path
    )
    return integration_block, conftest
