"""Tests for pyforge.models dataclasses."""
import pytest

from pyforge.models import (
    BranchCase,
    ClassInfo,
    DepInfo,
    MethodInfo,
    OrmModelInfo,
    SourceInfo,
)


class TestBranchCase:
    """Tests for BranchCase dataclass."""

    def test_storeAllFields_whenConstructedWithRequiredFields(self):
        """Given required fields, when BranchCase is constructed, then it stores all provided fields."""
        case = BranchCase(
            test_name="raiseValueError_whenUserIdIsNegative",
            input_overrides={"user_id": "-1"},
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception="ValueError",
            expected_return=None,
            is_happy_path=False,
        )
        assert case.test_name == "raiseValueError_whenUserIdIsNegative"
        assert case.input_overrides == {"user_id": "-1"}
        assert case.expected_exception == "ValueError"
        assert case.is_happy_path is False

    def test_defaultToNone_whenExceptionMatchNotProvided(self):
        """Given a BranchCase without expected_exception_match, when constructed, then expected_exception_match defaults to None."""
        case = BranchCase(
            test_name="test",
            input_overrides={},
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception=None,
            expected_return=None,
            is_happy_path=True,
        )
        assert case.expected_exception_match is None

    def test_storeExceptionMatch_whenExceptionMatchProvided(self):
        """Given an expected_exception_match value, when BranchCase is constructed, then it stores the value."""
        case = BranchCase(
            test_name="test",
            input_overrides={},
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception="ValueError",
            expected_return=None,
            is_happy_path=False,
            expected_exception_match=r"must be positive",
        )
        assert case.expected_exception_match == r"must be positive"

    def test_returnTrue_whenTwoIdenticalBranchCasesCompared(self):
        """Given two identical BranchCases, when compared, then they are equal."""
        case1 = BranchCase(
            test_name="test",
            input_overrides={"x": "1"},
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception=None,
            expected_return="2",
            is_happy_path=True,
        )
        case2 = BranchCase(
            test_name="test",
            input_overrides={"x": "1"},
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception=None,
            expected_return="2",
            is_happy_path=True,
        )
        assert case1 == case2

    def test_returnFalse_whenBranchCasesHaveDifferentTestNames(self):
        """Given two BranchCases with different test_names, when compared, then they are not equal."""
        case1 = BranchCase(
            test_name="test1",
            input_overrides={},
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception=None,
            expected_return=None,
            is_happy_path=True,
        )
        case2 = BranchCase(
            test_name="test2",
            input_overrides={},
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception=None,
            expected_return=None,
            is_happy_path=True,
        )
        assert case1 != case2

    def test_reflectMutation_whenInputOverridesDictMutated(self):
        """Given a mutable dict passed as input_overrides, when mutated after construction, then the stored overrides reflect the mutation."""
        original_dict = {"x": "1"}
        case = BranchCase(
            test_name="test",
            input_overrides=original_dict,
            mock_side_effect=None,
            mock_return_override=None,
            expected_exception=None,
            expected_return=None,
            is_happy_path=True,
        )
        original_dict["y"] = "2"
        # Dataclass stores the reference, so mutation is visible
        assert case.input_overrides == {"x": "1", "y": "2"}


class TestMethodInfo:
    """Tests for MethodInfo dataclass."""

    def test_storeAllFieldsWithCorrectDefaults_whenConstructed(self):
        """Given required fields, when MethodInfo is constructed, then it stores all provided fields with correct defaults."""
        method = MethodInfo(
            name="foo",
            args=["x", "y"],
            arg_types={"x": "int", "y": "str"},
            return_type="bool",
            is_void=False,
            is_public=True,
        )
        assert method.name == "foo"
        assert method.args == ["x", "y"]
        assert method.is_async is False
        assert method.is_static is False
        assert method.is_classmethod is False

    def test_defaultToEmptyList_whenRaisesNotProvided(self):
        """Given a MethodInfo without raises, when constructed, then raises defaults to an empty list."""
        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )
        assert method.raises == []

    def test_defaultToEmptyDict_whenArgDefaultsNotProvided(self):
        """Given a MethodInfo without arg_defaults, when constructed, then arg_defaults defaults to an empty dictionary."""
        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )
        assert method.arg_defaults == {}

    def test_defaultToEmptyList_whenNondeterministicPatchesNotProvided(self):
        """Given a MethodInfo without nondeterministic_patches, when constructed, then nondeterministic_patches defaults to an empty list."""
        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )
        assert method.nondeterministic_patches == []

    def test_returnEqual_whenAstNodesDiffer(self):
        """Given two MethodInfos with different ast_nodes, when compared, then they are equal because ast_node is excluded."""
        import ast as ast_module
        node1 = ast_module.parse("x = 1").body[0]
        node2 = ast_module.parse("y = 2").body[0]

        method1 = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
            ast_node=node1,
        )
        method2 = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
            ast_node=node2,
        )
        # Even with different ast_nodes, they should be equal
        assert method1 == method2

    def test_excludeAstNodeFromRepr_whenReprCalled(self):
        """Test that ast_node is excluded from repr."""
        import ast as ast_module
        node = ast_module.parse("x = 1").body[0]

        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
            ast_node=node,
        )
        # Repr should not contain ast node
        repr_str = repr(method)
        assert "ast_node" not in repr_str

    def test_storeIsAsyncTrue_whenIsAsyncProvided(self):
        """Test that is_async flag is stored correctly."""
        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
            is_async=True,
        )
        assert method.is_async is True

    def test_storeIsStaticAndIsClassmethodIndependently_whenFlagsProvided(self):
        """Test that is_static and is_classmethod flags are stored independently."""
        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
            is_static=True,
        )
        assert method.is_static is True
        assert method.is_classmethod is False

        method2 = MethodInfo(
            name="bar",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
            is_classmethod=True,
        )
        assert method2.is_static is False
        assert method2.is_classmethod is True


class TestDepInfo:
    """Tests for DepInfo dataclass."""

    def test_storeAllFields_whenDepInfoConstructed(self):
        """Test DepInfo construction with all fields."""
        dep = DepInfo(module="app.db", name="TodoRepository", alias="repo")
        assert dep.module == "app.db"
        assert dep.name == "TodoRepository"
        assert dep.alias == "repo"

    def test_allowNoneAlias_whenAliasIsNone(self):
        """Test that alias can be None."""
        dep = DepInfo(module="app.db", name="TodoRepository", alias=None)
        assert dep.alias is None

    def test_returnEqual_whenTwoIdenticalDepInfosCompared(self):
        """Test that two equal DepInfos are equal."""
        dep1 = DepInfo(module="app.db", name="TodoRepository", alias="repo")
        dep2 = DepInfo(module="app.db", name="TodoRepository", alias="repo")
        assert dep1 == dep2


class TestClassInfo:
    """Tests for ClassInfo dataclass."""

    def test_storeNameAndEmptyCollections_whenConstructedWithEmptyCollections(self):
        """Test ClassInfo construction with empty collections."""
        cls = ClassInfo(name="MyClass", methods=[], constructor_dep_map={})
        assert cls.name == "MyClass"
        assert cls.methods == []
        assert cls.constructor_dep_map == {}

    def test_storeMethodsAndDepMap_whenConstructedWithAll(self):
        """Test ClassInfo with methods and dependency map."""
        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )
        cls = ClassInfo(
            name="MyClass",
            methods=[method],
            constructor_dep_map={"repo": "TodoRepository"},
        )
        assert cls.name == "MyClass"
        assert len(cls.methods) == 1
        assert cls.constructor_dep_map == {"repo": "TodoRepository"}


class TestOrmModelInfo:
    """Tests for OrmModelInfo dataclass."""

    def test_storeSqlalchemyDbType_whenSqlalchemyModel(self):
        """Test OrmModelInfo for SQLAlchemy model."""
        orm = OrmModelInfo(
            class_name="Todo",
            db_type="sqlalchemy",
            column_attrs=["id", "title", "description"],
        )
        assert orm.class_name == "Todo"
        assert orm.db_type == "sqlalchemy"
        assert orm.column_attrs == ["id", "title", "description"]

    def test_storeDjangoDbType_whenDjangoModel(self):
        """Test OrmModelInfo for Django model."""
        orm = OrmModelInfo(
            class_name="User",
            db_type="django",
            column_attrs=["id", "username", "email"],
        )
        assert orm.db_type == "django"

    def test_storeEmptyColumnAttrs_whenNoColumns(self):
        """Test OrmModelInfo with empty column_attrs."""
        orm = OrmModelInfo(
            class_name="Model",
            db_type="sqlalchemy",
            column_attrs=[],
        )
        assert orm.column_attrs == []


class TestSourceInfo:
    """Tests for SourceInfo dataclass."""

    def test_storeRequiredFields_whenConstructedWithMinimum(self):
        """Test SourceInfo construction with required fields."""
        source = SourceInfo(
            lang="python",
            class_name="MyClass",
            methods=[],
            external_deps=[],
            module_path="app.service",
        )
        assert source.lang == "python"
        assert source.class_name == "MyClass"
        assert source.methods == []
        assert source.external_deps == []

    def test_provideEmptyDefaults_whenOptionalFieldsOmitted(self):
        """Test that SourceInfo has correct defaults."""
        source = SourceInfo(
            lang="python",
            class_name=None,
            methods=[],
            external_deps=[],
            module_path="module",
        )
        assert source.constructor_dep_map == {}
        assert source.all_classes == []
        assert source.module_level_methods == []

    def test_storeAllFields_whenConstructedWithAllArgs(self):
        """Test SourceInfo with all fields populated."""
        method = MethodInfo(
            name="foo",
            args=[],
            arg_types={},
            return_type=None,
            is_void=True,
            is_public=True,
        )
        cls = ClassInfo(
            name="MyClass",
            methods=[method],
            constructor_dep_map={"repo": "Repo"},
        )
        dep = DepInfo(module="sqlalchemy", name="Session", alias="session")

        source = SourceInfo(
            lang="python",
            class_name="MyClass",
            methods=[method],
            external_deps=[dep],
            module_path="app.service",
            constructor_dep_map={"repo": "Repo"},
            all_classes=[cls],
            module_level_methods=[method],
        )
        assert source.class_name == "MyClass"
        assert len(source.all_classes) == 1
        assert len(source.module_level_methods) == 1
