import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

MIGRATIONS_DIR = Path(__file__).parents[1] / "alembic" / "versions"


def _load_migration(filename: str) -> ModuleType:
    path = MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ai_feedback_branch_does_not_mutate_whatsapp_conversation() -> None:
    migration = _load_migration("963559a48ef6_add_aifeedback_table.py")
    created_tables: list[str] = []
    migration.op = SimpleNamespace(
        create_table=lambda name, *args, **kwargs: created_tables.append(name),
    )

    migration.upgrade()

    assert created_tables == ["ai_feedback"]


def test_head_migration_repairs_missing_whatsapp_conversation() -> None:
    migration = _load_migration("e2f47d9c6a10_ensure_whatsapp_conversation_column.py")
    statements: list[str] = []
    migration.op = SimpleNamespace(execute=lambda statement: statements.append(str(statement)))

    migration.upgrade()

    assert len(statements) == 1
    assert "ADD COLUMN IF NOT EXISTS whatsapp_conversation JSONB" in statements[0]
