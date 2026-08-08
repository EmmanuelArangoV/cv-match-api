#!/usr/bin/env python3
"""Auditoría de solo lectura sobre CostLog, sin exponer secretos."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select

BACKEND_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(BACKEND_ROOT))

from src.infrastructure.db.database import _SyncSession, sync_engine  # noqa: E402
from src.infrastructure.db.models import CostLog  # noqa: E402

sync_engine.echo = False


def _decimal(value: Any) -> str:
    return str(value if isinstance(value, Decimal) else Decimal(str(value or 0)))


def _base_filters(process_id: uuid.UUID | None, since: datetime | None) -> list[Any]:
    filters: list[Any] = []
    if process_id:
        filters.append(CostLog.process_id == process_id)
    if since:
        filters.append(CostLog.created_at >= since)
    return filters


def audit(process_id: uuid.UUID | None, since: datetime | None) -> dict[str, Any]:
    filters = _base_filters(process_id, since)
    with _SyncSession() as db:
        totals = db.execute(
            select(
                func.count(CostLog.id),
                func.coalesce(func.sum(CostLog.estimated_cost), 0),
                func.coalesce(func.sum(CostLog.tokens_input), 0),
                func.coalesce(func.sum(CostLog.tokens_cached), 0),
                func.coalesce(func.sum(CostLog.tokens_output), 0),
            ).where(*filters)
        ).one()

        grouped_rows = db.execute(
            select(
                CostLog.operation_type,
                CostLog.provider,
                CostLog.model_used,
                CostLog.cost_source,
                func.count(CostLog.id),
                func.coalesce(func.sum(CostLog.estimated_cost), 0),
            )
            .where(*filters)
            .group_by(
                CostLog.operation_type,
                CostLog.provider,
                CostLog.model_used,
                CostLog.cost_source,
            )
            .order_by(CostLog.operation_type, CostLog.provider, CostLog.model_used)
        ).all()

        checks = db.execute(
            select(
                func.sum(case((CostLog.cost_source == "legacy_estimate", 1), else_=0)),
                func.sum(case((CostLog.provider.is_(None), 1), else_=0)),
                func.sum(case((CostLog.external_reference.is_(None), 1), else_=0)),
                func.sum(case((CostLog.process_id.is_(None), 1), else_=0)),
                func.sum(case((CostLog.candidate_id.is_(None), 1), else_=0)),
                func.sum(case((CostLog.currency != "USD", 1), else_=0)),
                func.sum(case((CostLog.estimated_cost < 0, 1), else_=0)),
                func.sum(
                    case(
                        (
                            (CostLog.tokens_input < 0)
                            | (CostLog.tokens_cached < 0)
                            | (CostLog.tokens_output < 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                func.sum(case((CostLog.cost_breakdown == {}, 1), else_=0)),
            ).where(*filters)
        ).one()

        duplicate_refs = db.execute(
            select(CostLog.external_reference, func.count(CostLog.id))
            .where(*filters, CostLog.external_reference.is_not(None))
            .group_by(CostLog.external_reference)
            .having(func.count(CostLog.id) > 1)
        ).all()

    names = (
        "legacy_estimate",
        "provider_missing",
        "external_reference_missing",
        "process_missing",
        "candidate_missing",
        "non_usd",
        "negative_cost",
        "negative_tokens",
        "empty_breakdown",
    )
    return {
        "scope": {
            "process_id": str(process_id) if process_id else None,
            "since": since.isoformat() if since else None,
        },
        "totals": {
            "rows": totals[0],
            "cost_usd": _decimal(totals[1]),
            "tokens_input": totals[2],
            "tokens_cached": totals[3],
            "tokens_output": totals[4],
        },
        "integrity": {name: int(value or 0) for name, value in zip(names, checks, strict=True)},
        "duplicate_external_references": [
            {"external_reference": ref, "rows": count} for ref, count in duplicate_refs
        ],
        "groups": [
            {
                "operation_type": operation,
                "provider": provider,
                "model": model,
                "cost_source": source,
                "rows": rows,
                "cost_usd": _decimal(cost),
            }
            for operation, provider, model, source, rows, cost in grouped_rows
        ],
    }


def _parse_since(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audita CostLog sin modificar la base de datos.")
    parser.add_argument("--process-id", type=uuid.UUID)
    parser.add_argument("--since", type=_parse_since, help="Fecha ISO-8601, por ejemplo 2026-08-08")
    parser.add_argument("--json", action="store_true", help="Emite JSON legible por máquina")
    args = parser.parse_args()
    report = audit(args.process_id, args.since)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    print(f"Filas: {report['totals']['rows']} | Total USD: {report['totals']['cost_usd']}")
    print("Integridad:")
    for name, count in report["integrity"].items():
        print(f"  {name}: {count}")
    print(f"  duplicate_external_references: {len(report['duplicate_external_references'])}")
    print("Grupos:")
    for group in report["groups"]:
        print(
            f"  {group['operation_type']} | {group['provider']} | {group['model']} | "
            f"{group['cost_source']} | {group['rows']} | USD {group['cost_usd']}"
        )


if __name__ == "__main__":
    main()
