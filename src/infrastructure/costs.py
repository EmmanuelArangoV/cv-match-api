"""Cálculo y persistencia idempotente de costos variables del pipeline.

``estimated_cost`` conserva el nombre histórico de la columna, pero cada fila indica
si el valor vino del proveedor o de una tarifa pública mediante ``cost_source``.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Insert

from src.infrastructure.db.models import CostLog

_USD_QUANTUM = Decimal("0.000000001")
_ONE_MILLION = Decimal(1_000_000)

# Tarifas estándar por 1M tokens: entrada, entrada cacheada, salida y escritura
# de cache. Un modelo desconocido nunca hereda silenciosamente otro precio.
_OPENAI_TOKEN_RATES: dict[str, tuple[Decimal, Decimal, Decimal, Decimal]] = {
    "gpt-5.6-luna": (
        Decimal("0.20"),
        Decimal("0.02"),
        Decimal("1.20"),
        Decimal("0.25"),
    ),
    "gpt-4o": (Decimal("2.50"), Decimal("1.25"), Decimal("10.00"), Decimal("2.50")),
    "gpt-4o-2024-08-06": (
        Decimal("2.50"),
        Decimal("1.25"),
        Decimal("10.00"),
        Decimal("2.50"),
    ),
    "gpt-4o-2024-11-20": (
        Decimal("2.50"),
        Decimal("1.25"),
        Decimal("10.00"),
        Decimal("2.50"),
    ),
    "text-embedding-3-small": (
        Decimal("0.02"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.02"),
    ),
}

_OPENAI_PRICING_SOURCES = {
    "gpt-5.6-luna": "https://developers.openai.com/api/docs/models/gpt-5.6-luna",
    "gpt-4o": "https://developers.openai.com/api/docs/pricing",
    "gpt-4o-2024-08-06": "https://developers.openai.com/api/docs/pricing",
    "gpt-4o-2024-11-20": "https://developers.openai.com/api/docs/pricing",
    "text-embedding-3-small": "https://developers.openai.com/api/docs/pricing",
}
_OPENAI_PRICING_VERIFIED_AT = "2026-08-08"

_TWILIO_CO_MOBILE_PER_MINUTE = Decimal("0.0377")
_TWILIO_AMD_PER_CALL = Decimal("0.0075")
_TWILIO_MEDIA_STREAM_PER_MINUTE = Decimal("0.0044")

_R2_CLASS_A_PER_REQUEST = Decimal("4.50") / _ONE_MILLION
_R2_CLASS_B_PER_REQUEST = Decimal("0.36") / _ONE_MILLION
_R2_STORAGE_PER_GB_MONTH = Decimal("0.015")
_META_CO_UTILITY_TEMPLATE_PER_MESSAGE = Decimal("0.0008")


@dataclass(frozen=True)
class CostCalculation:
    amount_usd: Decimal
    source: str
    breakdown: dict[str, Any]


def _money(value: Decimal) -> Decimal:
    return value.quantize(_USD_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_openai_cost(
    model: str,
    input_tokens: int,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> CostCalculation:
    """Calcula costo estándar y falla explícitamente si el modelo no tiene tarifa."""
    if model not in _OPENAI_TOKEN_RATES:
        raise ValueError(f"No hay tarifa configurada para el modelo {model}")
    if min(
        input_tokens,
        output_tokens,
        cached_input_tokens,
        cache_write_tokens,
        reasoning_tokens,
    ) < 0:
        raise ValueError("Los tokens no pueden ser negativos")
    if cached_input_tokens + cache_write_tokens > input_tokens:
        raise ValueError(
            "Los tokens cacheados y escritos no pueden superar los tokens de entrada"
        )
    if reasoning_tokens > output_tokens:
        raise ValueError("Los tokens de razonamiento no pueden superar los tokens de salida")

    input_rate, cached_rate, output_rate, cache_write_rate = _OPENAI_TOKEN_RATES[model]
    uncached = input_tokens - cached_input_tokens - cache_write_tokens
    amount = (
        (Decimal(uncached) * input_rate)
        + (Decimal(cached_input_tokens) * cached_rate)
        + (Decimal(cache_write_tokens) * cache_write_rate)
        + (Decimal(output_tokens) * output_rate)
    ) / _ONE_MILLION
    return CostCalculation(
        amount_usd=_money(amount),
        source="openai_rate_card",
        breakdown={
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "cache_write_tokens": cache_write_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "input_usd_per_million": float(input_rate),
            "cached_input_usd_per_million": float(cached_rate),
            "cache_write_usd_per_million": float(cache_write_rate),
            "output_usd_per_million": float(output_rate),
            "pricing_source_url": _OPENAI_PRICING_SOURCES[model],
            "pricing_verified_at": _OPENAI_PRICING_VERIFIED_AT,
        },
    )


def has_openai_pricing(model: str) -> bool:
    return model in _OPENAI_TOKEN_RATES


def extract_openai_usage(response: Any) -> tuple[int, int, int, int, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0, 0, 0, 0
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = (
        int(getattr(prompt_details, "cached_tokens", 0) or 0) if prompt_details else 0
    )
    cache_write_tokens = (
        int(getattr(prompt_details, "cache_write_tokens", 0) or 0)
        if prompt_details
        else 0
    )
    completion_details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = (
        int(getattr(completion_details, "reasoning_tokens", 0) or 0)
        if completion_details
        else 0
    )
    return (
        input_tokens,
        output_tokens,
        cached_tokens,
        cache_write_tokens,
        reasoning_tokens,
    )


def calculate_elevenlabs_cost(metadata: dict[str, Any]) -> CostCalculation:
    """Prioriza el costo fiat que ElevenLabs ya calculó para la conversación."""
    charging = metadata.get("charging") or {}
    cost_fiat = metadata.get("cost_fiat")
    if cost_fiat is not None:
        amount = Decimal(str(cost_fiat))
        source = "elevenlabs_reported"
    else:
        # Compatibilidad con webhooks antiguos que solo incluían créditos.
        credits = Decimal(str(metadata.get("cost", 0) or 0))
        amount = (credits / Decimal(400)) * Decimal("0.09")
        source = "elevenlabs_credits_fallback"

    platform_usage = charging.get("platform_usage") or {}
    category_usage = platform_usage.get("category_usage") or {}
    return CostCalculation(
        amount_usd=_money(amount),
        source=source,
        breakdown={
            "credits": metadata.get("cost", 0) or 0,
            "cost_fiat": float(cost_fiat) if cost_fiat is not None else None,
            "platform_price": charging.get("platform_price"),
            "llm_price": charging.get("llm_price"),
            "call_charge_credits": charging.get("call_charge"),
            "llm_charge_credits": charging.get("llm_charge"),
            "category_usage": category_usage,
        },
    )


def extract_elevenlabs_llm_usage(metadata: dict[str, Any]) -> tuple[int, int, int, list[str]]:
    charging = metadata.get("charging") or {}
    llm_usage = charging.get("llm_usage") or {}
    generation = llm_usage.get("irreversible_generation") or llm_usage.get(
        "initiated_generation"
    ) or {}
    models = generation.get("model_usage") or {}
    input_tokens = cached_tokens = output_tokens = 0
    for usage in models.values():
        input_tokens += int((usage.get("input") or {}).get("tokens", 0) or 0)
        cached_tokens += int((usage.get("input_cache_read") or {}).get("tokens", 0) or 0)
        output_tokens += int((usage.get("output_total") or {}).get("tokens", 0) or 0)
    return input_tokens, output_tokens, cached_tokens, sorted(models)


def calculate_twilio_cost(
    duration_s: int,
    connectivity_cost_usd: str | float | Decimal | None,
    *,
    amd_used: bool,
    media_stream_used: bool,
) -> CostCalculation:
    billed_minutes = math.ceil(max(duration_s, 0) / 60) if duration_s else 0
    if connectivity_cost_usd is None:
        connectivity = Decimal(billed_minutes) * _TWILIO_CO_MOBILE_PER_MINUTE
        connectivity_source = "colombia_mobile_rate_card"
    else:
        connectivity = abs(Decimal(str(connectivity_cost_usd)))
        connectivity_source = "twilio_call_resource"
    amd = _TWILIO_AMD_PER_CALL if amd_used else Decimal(0)
    media = (
        Decimal(billed_minutes) * _TWILIO_MEDIA_STREAM_PER_MINUTE
        if media_stream_used
        else Decimal(0)
    )
    return CostCalculation(
        amount_usd=_money(connectivity + amd + media),
        source=(
            "twilio_reported_plus_rate_card"
            if connectivity_cost_usd is not None
            else "twilio_rate_card"
        ),
        breakdown={
            "duration_s": duration_s,
            "billed_minutes": billed_minutes,
            "connectivity_usd": float(connectivity),
            "connectivity_source": connectivity_source,
            "amd_usd": float(amd),
            "media_stream_usd": float(media),
        },
    )


def calculate_r2_cost(
    *, bytes_stored: int = 0, class_a_operations: int = 0, class_b_operations: int = 0
) -> CostCalculation:
    storage_gb_month = Decimal(max(bytes_stored, 0)) / Decimal(1024**3)
    amount = (
        Decimal(max(class_a_operations, 0)) * _R2_CLASS_A_PER_REQUEST
        + Decimal(max(class_b_operations, 0)) * _R2_CLASS_B_PER_REQUEST
        + storage_gb_month * _R2_STORAGE_PER_GB_MONTH
    )
    return CostCalculation(
        amount_usd=_money(amount),
        source="cloudflare_r2_rate_card_gross",
        breakdown={
            "bytes_stored": bytes_stored,
            "class_a_operations": class_a_operations,
            "class_b_operations": class_b_operations,
            "free_tier_applied": False,
        },
    )


def calculate_meta_whatsapp_cost(*, country: str, category: str) -> CostCalculation:
    """Tarifa de lista para la plantilla utility usada por el flujo colombiano."""
    if country.upper() != "CO" or category.lower() != "utility":
        raise ValueError(f"No hay tarifa Meta configurada para {country}/{category}")
    return CostCalculation(
        amount_usd=_money(_META_CO_UTILITY_TEMPLATE_PER_MESSAGE),
        source="meta_colombia_utility_rate_card",
        breakdown={
            "country": "CO",
            "category": "utility",
            "price_per_delivered_template": float(_META_CO_UTILITY_TEMPLATE_PER_MESSAGE),
        },
    )

def _cost_insert_statement(**values: Any) -> Insert:
    values.setdefault("id", uuid.uuid4())
    values.setdefault("currency", "USD")
    values.setdefault("cost_breakdown", {})
    statement = insert(CostLog).values(**values)
    if values.get("external_reference"):
        statement = statement.on_conflict_do_nothing(index_elements=["external_reference"])
    return statement


def record_cost_sync(db: Session, **values: Any) -> bool:
    result = db.execute(_cost_insert_statement(**values))
    return bool(getattr(result, "rowcount", 0))


async def record_cost_async(db: AsyncSession, **values: Any) -> bool:
    result = await db.execute(_cost_insert_statement(**values))
    return bool(getattr(result, "rowcount", 0))
