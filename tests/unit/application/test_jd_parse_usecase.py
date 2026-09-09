from src.application.hiring_process.jd_parse_usecase import _plain_text_jd


def test_enhanced_jd_is_normalized_to_plain_text() -> None:
    markdown_jd = """# Sobre el cargo

**Construirás** productos con `Python`.

- Diseñar APIs.
- Colaborar con el equipo.

Consulta [nuestra web](https://example.com).
---
"""

    assert _plain_text_jd(markdown_jd) == (
        "Sobre el cargo\n\n"
        "Construirás productos con Python.\n\n"
        "Diseñar APIs.\n"
        "Colaborar con el equipo.\n\n"
        "Consulta nuestra web."
    )


def test_enhanced_jd_falls_back_cleanly_for_non_string_values() -> None:
    assert _plain_text_jd(None) == ""
