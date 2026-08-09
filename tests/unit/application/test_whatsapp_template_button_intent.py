from types import SimpleNamespace

from src.application.candidate.whatsapp_message_usecase import _resolve_button_intent


def _process_with_buttons(accept: str, reject: str) -> SimpleNamespace:
    return SimpleNamespace(
        whatsapp_template=SimpleNamespace(
            components=[
                {
                    "type": "BUTTONS",
                    "buttons": [
                        {"type": "QUICK_REPLY", "text": accept},
                        {"type": "QUICK_REPLY", "text": reject},
                    ],
                }
            ]
        )
    )


def test_template_button_labels_define_accept_and_reject_intents() -> None:
    process = _process_with_buttons("Claro, continuar", "Prefiero no seguir")

    assert _resolve_button_intent("Claro, continuar", process) == "ACCEPTED"
    assert _resolve_button_intent("prefiero no seguir", process) == "REJECTED"


def test_unknown_button_stays_available_for_ai_classification() -> None:
    process = _process_with_buttons("Aceptar", "Rechazar")

    assert _resolve_button_intent("Tengo una pregunta", process) is None
