"""Renderiza CVs anonimizados en las plantillas de Blackbird Labs."""

from __future__ import annotations

import html as _html
import io
import json
import re
from collections.abc import Iterable
from typing import Any

import pymupdf as fitz  # PyMuPDF >= 1.24

from src.infrastructure.cv.blackbird_assets import BLACKBIRD_LOCKUP_PNG, BLACKBIRD_MARK_PNG

_CSS = """
body { font-family: sans-serif; font-size: 9.2pt; color: #161616; line-height: 1.36; }
h1 { font-size: 23pt; font-weight: bold; letter-spacing: -0.45pt; margin: 0 0 2pt 0; }
.cv-title { font-size: 10.5pt; margin: 0 0 17pt 0; color: #282828; }
h2 { font-size: 10pt; font-weight: bold; letter-spacing: 0.25pt; margin: 13pt 0 3pt 0; }
hr { margin: 0 0 6pt 0; border: none; border-top: 0.7pt solid #111; }
p { margin: 0 0 4pt 0; }
ul { margin: 2pt 0 6pt 0; padding-left: 13pt; }
li { margin-bottom: 2pt; }
.skill-group { font-weight: bold; margin: 5pt 0 1pt 0; }
.skill-list { margin: 0 0 3pt 0; }
.experience-company { font-weight: bold; font-size: 10pt; margin: 8pt 0 0 0; }
.experience-role { font-style: italic; margin: 0 0 1pt 0; }
.experience-meta { color: #4b4b4b; font-size: 8.5pt; margin: 0 0 2pt 0; }
"""

_LABELS = {
    "es": {
        "profile": "PERFIL PROFESIONAL",
        "skills": "HABILIDADES TÉCNICAS",
        "education": "FORMACIÓN ACADÉMICA",
        "certifications": "CERTIFICACIONES",
        "languages": "IDIOMAS",
        "experience": "EXPERIENCIA PROFESIONAL",
        "present": "Actualidad",
        "programming_languages": "Lenguajes de programación",
        "frameworks_and_libraries": "Frameworks y librerías",
        "cloud_and_devops": "Cloud y DevOps",
        "databases": "Bases de datos",
        "tools_and_platforms": "Herramientas y plataformas",
        "architectures_and_patterns": "Arquitecturas y patrones",
        "other": "Otros",
    },
    "en": {
        "profile": "PROFESSIONAL PROFILE",
        "skills": "TECHNICAL SKILLS",
        "education": "EDUCATION",
        "certifications": "CERTIFICATIONS",
        "languages": "LANGUAGES",
        "experience": "PROFESSIONAL EXPERIENCE",
        "present": "Present",
        "programming_languages": "Programming Languages",
        "frameworks_and_libraries": "Frameworks & Libraries",
        "cloud_and_devops": "Cloud & DevOps",
        "databases": "Databases",
        "tools_and_platforms": "Tools & Platforms",
        "architectures_and_patterns": "Architecture & Patterns",
        "other": "Other",
    },
}
_SKILL_KEYS = tuple(
    key
    for key in _LABELS["en"]
    if key
    not in {
        "profile",
        "skills",
        "education",
        "certifications",
        "languages",
        "experience",
        "present",
    }
)
_SKILL_ALIASES = {
    "javascript": ("javascript", "js"),
    "typescript": ("typescript", "ts"),
    "react": ("react", "react.js", "reactjs"),
    "node.js": ("node.js", "nodejs", "node"),
    "postgresql": ("postgresql", "postgres", "postgre"),
    "python": ("python",),
    "c#": ("c#", "csharp"),
}
_CONTACT_FIELD_NAMES = {"email", "phone", "location", "linkedin_url", "github_url"}
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", flags=re.IGNORECASE)
_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_MISSING_VALUES = {
    "unknown",
    "unknow",
    "not specified",
    "not available",
    "n/a",
    "na",
    "none",
    "null",
    "desconocido",
    "no especificado",
    "no disponible",
}


def _e(value: object) -> str:
    return _html.escape(str(value)) if value not in (None, "") else ""


def _redact_contact_text(value: str, location: str | None) -> str:
    redacted = _EMAIL_PATTERN.sub("", value)
    redacted = _URL_PATTERN.sub("", redacted)
    redacted = _PHONE_PATTERN.sub("", redacted)
    if location:
        redacted = re.sub(re.escape(location), "", redacted, flags=re.IGNORECASE)
    redacted = re.sub(
        r"\b(?:contacto|contact|teléfono|telefono|phone|email|ubicación|ubicacion|location)\s*:?\s*",
        "",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(r"\s*,\s*(?:,\s*)+", " ", redacted)
    redacted = re.sub(r"\s*,\s*([.])", r"\1", redacted)
    redacted = re.sub(r"\.{2,}", ".", redacted)
    return re.sub(r"\s{2,}", " ", redacted).strip()


def _sanitize_for_public_cv(value: Any, location: str | None = None) -> Any:
    """Elimina campos de contacto y sus apariciones accidentales en texto libre."""
    if isinstance(value, str):
        return _redact_contact_text(value, location)
    if isinstance(value, list):
        return [_sanitize_for_public_cv(item, location) for item in value]
    if isinstance(value, dict):
        return {
            key: _sanitize_for_public_cv(item, location)
            for key, item in value.items()
            if key not in _CONTACT_FIELD_NAMES
        }
    return value


def _omit_missing_values(value: Any) -> Any:
    """Quita placeholders de extracción para no presentarlos como datos del CV."""
    if isinstance(value, str):
        return "" if value.strip().casefold() in _MISSING_VALUES else value
    if isinstance(value, list):
        cleaned_items = [_omit_missing_values(item) for item in value]
        return [item for item in cleaned_items if item not in (None, "", [], {})]
    if isinstance(value, dict):
        cleaned_fields = {key: _omit_missing_values(item) for key, item in value.items()}
        return {
            key: item for key, item in cleaned_fields.items() if item not in (None, "", [], {})
        }
    return value


def _highlight(text: object, highlight_terms: Iterable[str]) -> str:
    """Escapa el texto y destaca solo términos concretos del stack del JD."""
    value = str(text or "")
    terms = sorted(
        {term.strip() for term in highlight_terms if term and term.strip()}, key=len, reverse=True
    )
    if not value or not terms:
        return _e(value)
    pattern = "|".join(re.escape(term) for term in terms)
    # No usar ``\\b``: tecnologías como C#, .NET o Node.js incluyen puntuación.
    matcher = re.compile(rf"(?<!\w)({pattern})(?!\w)", flags=re.IGNORECASE)
    cursor = 0
    chunks: list[str] = []
    for match in matcher.finditer(value):
        chunks.append(_e(value[cursor : match.start()]))
        chunks.append(f"<b>{_e(match.group(0))}</b>")
        cursor = match.end()
    chunks.append(_e(value[cursor:]))
    return "".join(chunks)


def _contains_term(text: str, term: str) -> bool:
    return bool(
        re.search(
            rf"(?<!\w){re.escape(term)}(?!\w)",
            text,
            flags=re.IGNORECASE,
        )
    )


def extract_jd_highlight_terms(
    profile: dict[str, Any], jd_text: str, structured_jd: dict[str, Any] | None = None
) -> list[str]:
    """Devuelve tecnologías del candidato mencionadas explícitamente por el JD.

    Es deliberadamente determinista: no inventa una relación entre dos tecnologías;
    considera únicamente el nombre de la habilidad y alias habituales de producto.
    """
    searchable = " ".join((jd_text or "", json.dumps(structured_jd or {}, ensure_ascii=False)))
    skills = profile.get("technical_skills") or {}
    terms: list[str] = []
    for key in _SKILL_KEYS:
        for raw_skill in skills.get(key) or []:
            skill = str(raw_skill).strip()
            if not skill:
                continue
            aliases = (skill, *_SKILL_ALIASES.get(skill.casefold(), ()))
            if any(_contains_term(searchable, alias) for alias in aliases):
                terms.append(skill)
    return list(dict.fromkeys(terms))


def _heading(label: str) -> str:
    return f"<h2>{_e(label)}</h2><hr>"


def _section_education(
    items: list[dict[str, Any]], labels: dict[str, str], terms: Iterable[str]
) -> str:
    if not items:
        return ""
    body = []
    for item in items:
        pieces = [
            _highlight(item.get("degree", ""), terms),
            _highlight(item.get("institution", ""), terms),
        ]
        if item.get("year"):
            pieces.append(_e(item["year"]))
        if any(pieces):
            body.append(f"<p>{' · '.join(piece for piece in pieces if piece)}</p>")
    return _heading(labels["education"]) + "".join(body)


def _section_skills(skills: dict[str, Any], labels: dict[str, str], terms: Iterable[str]) -> str:
    body: list[str] = []
    for key in _SKILL_KEYS:
        values = skills.get(key) or []
        if not values:
            continue
        rendered_values = " · ".join(_highlight(value, terms) for value in values)
        body.append(
            f'<p class="skill-group">{_e(labels[key])}</p>'
            f'<p class="skill-list">{rendered_values}</p>'
        )
    return _heading(labels["skills"]) + "".join(body) if body else ""


def _section_certifications(
    items: list[dict[str, Any]], labels: dict[str, str], terms: Iterable[str]
) -> str:
    if not items:
        return ""
    body: list[str] = []
    for item in items:
        pieces = [
            _highlight(item.get("title", ""), terms),
            _highlight(item.get("institution", ""), terms),
        ]
        if item.get("year"):
            pieces.append(_e(item["year"]))
        if any(pieces):
            body.append(f"<p>{' · '.join(piece for piece in pieces if piece)}</p>")
    return _heading(labels["certifications"]) + "".join(body)


def _section_languages(items: list[dict[str, Any]], labels: dict[str, str]) -> str:
    if not items:
        return ""
    body = []
    for item in items:
        language = _e(item.get("language", ""))
        level = _e(item.get("level_original") or item.get("level_cefr", ""))
        if language:
            body.append(f"<p>{language}{f' · {level}' if level else ''}</p>")
    return _heading(labels["languages"]) + "".join(body) if body else ""


def _section_experience(
    items: list[dict[str, Any]], labels: dict[str, str], terms: Iterable[str]
) -> str:
    if not items:
        return ""
    body: list[str] = []
    for item in items:
        start, end = item.get("start_year"), item.get("end_year")
        if start and item.get("is_current"):
            period = f"{_e(start)} – {labels['present']}"
        elif start and end:
            period = f"{_e(start)} – {_e(end)}"
        else:
            period = _e(start or end)
        meta = " · ".join(part for part in (_e(item.get("employment_type", "")), period) if part)
        company = _highlight(item.get("company", ""), terms)
        role = _highlight(item.get("role", ""), terms)
        responsibilities = item.get("responsibilities") or []
        if not any((company, role, meta, responsibilities)):
            continue
        if company:
            body.append(f'<p class="experience-company">{company}</p>')
        if role:
            body.append(f'<p class="experience-role">{role}</p>')
        if meta:
            body.append(f'<p class="experience-meta">{meta}</p>')
        if responsibilities:
            body.append(
                "<ul>"
                + "".join(f"<li>{_highlight(value, terms)}</li>" for value in responsibilities)
                + "</ul>"
            )
    return _heading(labels["experience"]) + "".join(body)


def _add_branding(pdf_bytes: bytes) -> bytes:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")  # type: ignore[no-untyped-call]
    for page_number in range(document.page_count):
        page = document[page_number]
        page.insert_image(
            fitz.Rect(page.rect.width - 134, 35, page.rect.width - 55, 102),  # type: ignore[no-untyped-call]
            stream=BLACKBIRD_MARK_PNG,
            overlay=True,
        )
        page.insert_image(
            fitz.Rect(55, page.rect.height - 58, 170, page.rect.height - 36),  # type: ignore[no-untyped-call]
            stream=BLACKBIRD_LOCKUP_PNG,
            overlay=True,
        )
    output = document.tobytes(garbage=4, deflate=True)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return bytes(output)


def render_normalized_cv(
    normalized_cv: dict[str, Any],
    *,
    language: str = "es",
    highlight_terms: Iterable[str] = (),
) -> bytes:
    """Genera un CV sin datos de contacto, en español o inglés.

    ``normalized_cv`` puede contener identidad para el resto del sistema, pero esta
    representación nunca renderiza correo, teléfono, ubicación ni enlaces públicos.
    """
    locale = "en" if language == "en" else "es"
    labels = _LABELS[locale]
    public_cv = _omit_missing_values(
        _sanitize_for_public_cv(normalized_cv, normalized_cv.get("location"))
    )
    full_name = _e(public_cv.get("full_name", ""))
    title = _highlight(public_cv.get("title", ""), highlight_terms)
    profile = _highlight(public_cv.get("professional_profile", ""), highlight_terms)
    sections = "".join(
        (
            _section_skills(public_cv.get("technical_skills") or {}, labels, highlight_terms),
            _section_education(public_cv.get("education") or [], labels, highlight_terms),
            _section_certifications(public_cv.get("certifications") or [], labels, highlight_terms),
            _section_languages(public_cv.get("languages") or [], labels),
            _section_experience(public_cv.get("experience") or [], labels, highlight_terms),
        )
    )
    header = f"<h1>{full_name}</h1>" if full_name else ""
    if title:
        header += f'<p class="cv-title">{title}</p>'
    profile_section = f'{_heading(labels["profile"])}<p>{profile}</p>' if profile else ""
    body = f"""<html><body>
{header}{profile_section}{sections}
</body></html>"""
    buffer = io.BytesIO()
    story = fitz.Story(html=body, user_css=_CSS)
    writer = fitz.DocumentWriter(buffer)
    mediabox = fitz.paper_rect("a4")
    # El área superior queda libre para la marca; el pie queda libre para el lockup.
    where = fitz.Rect(55, 122, mediabox.width - 55, mediabox.height - 76)
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return _add_branding(buffer.getvalue())
