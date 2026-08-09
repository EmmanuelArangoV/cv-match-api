from types import SimpleNamespace

import pytest

from src.api.v1.whatsapp_templates import (
    CreateWhatsAppTemplateRequest,
    _bindings_complete,
    _build_meta_payload,
    serialize_template,
)
from src.domain.shared.exceptions import BusinessRuleException
from src.infrastructure.messaging.whatsapp_client import (
    WhatsAppClient,
    template_bindings_are_valid,
)


def _request(**overrides) -> CreateWhatsAppTemplateRequest:
    values = {
        "name": "consentimiento_profiling_v3",
        "language": "es_CO",
        "body_text": "Hola {{1}}, ¿aceptas una entrevista para {{2}}?",
        "accept_button_text": "Sí, acepto",
        "reject_button_text": "No, gracias",
        "variable_bindings": {"1": "candidate_name", "2": "job_title"},
        "variable_examples": {"1": "Ada Lovelace", "2": "Backend senior"},
    }
    values.update(overrides)
    return CreateWhatsAppTemplateRequest(**values)


def test_build_meta_payload_keeps_content_and_local_bindings_separate() -> None:
    payload, bindings = _build_meta_payload(_request())

    assert payload["category"] == "UTILITY"
    assert payload["components"][0]["type"] == "BODY"
    assert payload["components"][0]["example"]["body_text"] == [
        ["Ada Lovelace", "Backend senior"]
    ]
    assert payload["components"][-1]["buttons"][0]["text"] == "Sí, acepto"
    assert bindings == {"BODY": {"1": "candidate_name", "2": "job_title"}}


@pytest.mark.parametrize(
    ("body_text", "bindings", "message"),
    [
        ("Hola {{2}}, esta variable empieza mal", {"2": "candidate_name"}, "consecutivas"),
        ("Hola {{1}}, dato inválido", {"1": "salary"}, "dato soportado"),
    ],
)
def test_build_meta_payload_rejects_unsafe_variable_contracts(
    body_text: str, bindings: dict[str, str], message: str
) -> None:
    with pytest.raises(BusinessRuleException, match=message):
        _build_meta_payload(_request(body_text=body_text, variable_bindings=bindings))


def test_send_payload_resolves_variables_in_positional_order() -> None:
    components = WhatsAppClient.build_template_components(
        {"BODY": {"2": "job_title", "1": "candidate_name"}},
        {"candidate_name": "Ada Lovelace", "job_title": "Backend senior"},
    )

    assert components == [
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Ada Lovelace"},
                {"type": "text", "text": "Backend senior"},
            ],
        }
    ]


def test_send_payload_rejects_missing_runtime_value() -> None:
    with pytest.raises(BusinessRuleException, match="job_title"):
        WhatsAppClient.build_template_components(
            {"BODY": {"1": "job_title"}},
            {"job_title": ""},
        )


def test_template_is_selectable_only_when_approved_enabled_and_mapped() -> None:
    template = SimpleNamespace(
        id="template-id",
        meta_template_id="meta-id",
        name="consentimiento",
        language="es_CO",
        category="UTILITY",
        status="APPROVED",
        components=[{"type": "BODY", "text": "Hola {{1}}"}],
        variable_bindings={"BODY": {"1": "candidate_name"}},
        rejection_reason=None,
        is_enabled=True,
        is_default=True,
        last_synced_at=None,
        created_at=SimpleNamespace(isoformat=lambda: "created"),
        updated_at=SimpleNamespace(isoformat=lambda: "updated"),
    )

    assert _bindings_complete(template)
    assert serialize_template(template)["is_selectable"] is True
    template.variable_bindings = {}
    assert serialize_template(template)["is_selectable"] is False


@pytest.mark.parametrize(
    "bindings",
    [
        {"BODY": {"1": "salary"}},
        {"BODY": {"1": "candidate_name", "2": "job_title"}},
        {"BODY": {}},
    ],
)
def test_template_bindings_reject_unknown_extra_or_missing_positions(bindings: dict) -> None:
    assert not template_bindings_are_valid(
        [{"type": "BODY", "text": "Hola {{1}}"}], bindings
    )
