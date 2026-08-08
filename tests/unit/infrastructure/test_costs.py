from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.infrastructure.costs import (
    calculate_elevenlabs_cost,
    calculate_meta_whatsapp_cost,
    calculate_openai_cost,
    calculate_r2_cost,
    calculate_twilio_cost,
    extract_elevenlabs_llm_usage,
    extract_openai_usage,
    has_openai_pricing,
)


def test_gpt4o_uses_current_standard_token_rates() -> None:
    cost = calculate_openai_cost("gpt-4o", 815, 316)

    assert cost.amount_usd == Decimal("0.005197500")
    assert cost.source == "openai_rate_card"


def test_openai_cached_tokens_use_discounted_rate() -> None:
    cost = calculate_openai_cost("gpt-4o", 1_000_000, 100_000, 400_000)

    assert cost.amount_usd == Decimal("3.000000000")


def test_luna_tracks_cached_writes_and_reasoning_with_verified_rates() -> None:
    cost = calculate_openai_cost(
        "gpt-5.6-luna",
        1_000_000,
        200_000,
        cached_input_tokens=300_000,
        cache_write_tokens=100_000,
        reasoning_tokens=50_000,
    )

    assert cost.amount_usd == Decimal("0.391000000")
    assert cost.breakdown["reasoning_tokens"] == 50_000
    assert cost.breakdown["pricing_verified_at"] == "2026-08-08"
    assert cost.breakdown["pricing_source_url"].endswith("/models/gpt-5.6-luna")
    assert has_openai_pricing("gpt-5.6-luna") is True


def test_openai_usage_extracts_all_billable_token_categories() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=123,
            completion_tokens=45,
            prompt_tokens_details=SimpleNamespace(
                cached_tokens=20,
                cache_write_tokens=10,
            ),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=12),
        )
    )

    assert extract_openai_usage(response) == (123, 45, 20, 10, 12)


def test_unknown_openai_model_is_not_silently_priced_as_gpt4o() -> None:
    with pytest.raises(ValueError, match="No hay tarifa configurada"):
        calculate_openai_cost("modelo-inventado", 100, 20)
    assert has_openai_pricing("modelo-inventado") is False


def test_embedding_cost_is_preserved_below_six_decimals() -> None:
    cost = calculate_openai_cost("text-embedding-3-small", 1_000)

    assert cost.amount_usd == Decimal("0.000020000")


def test_elevenlabs_prefers_provider_reported_fiat_cost() -> None:
    cost = calculate_elevenlabs_cost(
        {
            "cost": 169,
            "cost_fiat": 0.03693241815642374,
            "charging": {"platform_price": 0.036360718, "llm_price": 0.0005717},
        }
    )

    assert cost.amount_usd == Decimal("0.036932418")
    assert cost.source == "elevenlabs_reported"


def test_elevenlabs_llm_usage_does_not_double_count_initiated_generation() -> None:
    model_usage = {
        "gemini-2.5-flash-lite": {
            "input": {"tokens": 5457},
            "input_cache_read": {"tokens": 12},
            "output_total": {"tokens": 65},
        }
    }
    metadata = {
        "charging": {
            "llm_usage": {
                "irreversible_generation": {"model_usage": model_usage},
                "initiated_generation": {"model_usage": model_usage},
            }
        }
    }

    assert extract_elevenlabs_llm_usage(metadata) == (
        5457,
        65,
        12,
        ["gemini-2.5-flash-lite"],
    )


def test_twilio_combines_reported_connectivity_amd_and_media_stream() -> None:
    cost = calculate_twilio_cost(
        39,
        "-0.03770",
        amd_used=True,
        media_stream_used=True,
    )

    assert cost.amount_usd == Decimal("0.049600000")
    assert cost.breakdown["billed_minutes"] == 1


def test_r2_tracks_gross_rate_card_separately_from_free_tier() -> None:
    cost = calculate_r2_cost(
        bytes_stored=1024**3,
        class_a_operations=1,
        class_b_operations=1,
    )

    assert cost.amount_usd == Decimal("0.015004860")
    assert cost.breakdown["free_tier_applied"] is False


def test_meta_colombia_utility_template_uses_per_message_rate() -> None:
    cost = calculate_meta_whatsapp_cost(country="CO", category="utility")

    assert cost.amount_usd == Decimal("0.000800000")
