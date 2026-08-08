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


def test_cost_migration_adds_auditability_and_idempotency() -> None:
    migration = _load_migration("f9b2c4d6e8a0_add_auditable_cost_tracking.py")
    added_columns: list[str] = []
    constraints: list[tuple[str, tuple[str, ...]]] = []
    migration.op = SimpleNamespace(
        add_column=lambda table, column: added_columns.append(column.name),
        alter_column=lambda *args, **kwargs: None,
        create_unique_constraint=lambda name, table, columns: constraints.append(
            (name, tuple(columns))
        ),
        execute=lambda statement: None,
    )

    migration.upgrade()

    assert {
        "provider",
        "tokens_cached",
        "currency",
        "cost_source",
        "external_reference",
        "cost_breakdown",
    }.issubset(added_columns)
    assert constraints == [
        ("uq_cost_logs_external_reference", ("external_reference",))
    ]


def test_luna_migration_activates_all_openai_workloads_and_feedback_prompt() -> None:
    migration = _load_migration("a1c3e5f7b9d2_activate_luna_and_voice_feedback.py")
    statements: list[object] = []
    migration.op = SimpleNamespace(execute=lambda statement: statements.append(statement))

    migration.upgrade()

    assert migration.down_revision == "f9b2c4d6e8a0"
    assert set(migration._MODEL_IDS) == {
        "CV_EXTRACTION",
        "CV_MATCH",
        "JD_ENHANCEMENT",
        "VOICE_PROFILING",
        "WHATSAPP_MESSAGE",
    }
    assert "retroalimentación breve" in migration._VOICE_PROMPT
    assert len(statements) == 8
