"""
Genera un PDF normalizado en formato BBLABS a partir del normalized_cv JSON.
Usa PyMuPDF Story (HTML → PDF) disponible desde pymupdf>=1.21.
"""
from __future__ import annotations

import html as _html
import io

import pymupdf as fitz  # PyMuPDF >= 1.24


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
body {
    font-family: sans-serif;
    font-size: 10pt;
    color: #1a1a1a;
    line-height: 1.45;
}
h1 {
    font-size: 26pt;
    font-weight: bold;
    margin: 0 0 3pt 0;
    color: #000000;
}
.cv-title {
    font-size: 11pt;
    color: #333333;
    margin: 0 0 2pt 0;
}
.cv-contact {
    font-size: 9pt;
    color: #555555;
    margin: 0 0 10pt 0;
}
.section-label {
    font-size: 8pt;
    font-weight: bold;
    background-color: #FFE000;
    color: #000000;
    padding: 1pt 4pt;
    margin: 0 0 12pt 0;
}
h2 {
    font-size: 11pt;
    font-weight: bold;
    color: #000000;
    margin: 14pt 0 0 0;
}
hr {
    margin: 2pt 0 6pt 0;
    border: none;
    border-top: 0.5pt solid #1a1a1a;
}
p {
    margin: 0 0 5pt 0;
}
ul {
    margin: 2pt 0 6pt 0;
    padding-left: 14pt;
}
li {
    margin-bottom: 2pt;
    font-size: 10pt;
}
.company-name {
    font-weight: bold;
    font-size: 10pt;
    margin: 8pt 0 1pt 0;
}
.role-name {
    font-size: 10pt;
    font-style: italic;
    margin: 0 0 2pt 0;
}
.meta-line {
    font-size: 9pt;
    color: #666666;
    margin: 0 0 3pt 0;
}
.skill-group-name {
    font-weight: bold;
    font-size: 10pt;
    margin: 6pt 0 2pt 0;
}
.skill-list {
    font-size: 10pt;
    margin: 0 0 4pt 0;
    color: #333333;
}
"""


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

def _e(text: str) -> str:
    """Escapa caracteres HTML."""
    return _html.escape(str(text)) if text else ""


def _contact_line(cv: dict) -> str:
    parts = []
    if cv.get("location"):
        parts.append(_e(cv["location"]))
    if cv.get("phone"):
        parts.append(_e(cv["phone"]))
    if cv.get("email"):
        parts.append(_e(cv["email"]))
    if cv.get("linkedin_url"):
        parts.append("LinkedIn")
    if cv.get("github_url"):
        parts.append("GitHub")
    return " &nbsp;|&nbsp; ".join(parts)


def _section_education(edu_list: list[dict]) -> str:
    if not edu_list:
        return ""
    items = ""
    for edu in edu_list:
        degree = _e(edu.get("degree", ""))
        institution = _e(edu.get("institution", ""))
        year = edu.get("year")
        year_str = f", {year}" if year else ""
        items += f"<p>{degree}, {institution}{year_str}.</p>"
    return f"<h2>EDUCATION</h2><hr>{items}"


def _section_experience(exp_list: list[dict]) -> str:
    if not exp_list:
        return ""
    body = ""
    for exp in exp_list:
        company = _e(exp.get("company", ""))
        role = _e(exp.get("role", ""))
        emp_type = _e(exp.get("employment_type", ""))
        start = exp.get("start_year")
        end = exp.get("end_year")
        is_current = exp.get("is_current", False)
        responsibilities = exp.get("responsibilities", [])

        period = ""
        if start and end and not is_current:
            period = f"{start} – {end}"
        elif start and is_current:
            period = f"{start} – Present"
        elif start:
            period = str(start)

        meta_parts = [p for p in [emp_type, period] if p]
        meta = " &nbsp;·&nbsp; ".join(meta_parts)

        body += f'<p class="company-name">{company}</p>'
        body += f'<p class="role-name">{role}</p>'
        if meta:
            body += f'<p class="meta-line">{meta}</p>'
        if responsibilities:
            items = "".join(f"<li>{_e(r)}</li>" for r in responsibilities)
            body += f"<ul>{items}</ul>"

    return f"<h2>PROFESSIONAL EXPERIENCE</h2><hr>{body}"


def _section_certifications(certs: list[dict]) -> str:
    if not certs:
        return ""
    items = ""
    for c in certs:
        title = _e(c.get("title", ""))
        institution = _e(c.get("institution") or "")
        year = c.get("year")
        parts = [p for p in [institution, str(year) if year else ""] if p]
        suffix = f", {', '.join(parts)}" if parts else ""
        items += f"<li>{title}{suffix}</li>"
    return f"<h2>CERTIFICATIONS</h2><hr><ul>{items}</ul>"


def _section_languages(langs: list[dict]) -> str:
    if not langs:
        return ""
    items = ""
    for lang in langs:
        language = _e(lang.get("language", ""))
        level = _e(lang.get("level_original") or lang.get("level_cefr", ""))
        level_str = f" – {level}" if level else ""
        items += f"<li>{language}{level_str}</li>"
    return f"<h2>LANGUAGES</h2><hr><ul>{items}</ul>"


def _section_skills(skills: dict) -> str:
    if not skills:
        return ""

    _labels = {
        "programming_languages": "Programming Languages",
        "frameworks_and_libraries": "Frameworks & Libraries",
        "cloud_and_devops": "Cloud & DevOps",
        "databases": "Databases",
        "tools_and_platforms": "Tools & Platforms",
        "architectures_and_patterns": "Architecture & Patterns",
        "other": "Other",
    }

    body = ""
    for key, label in _labels.items():
        items = skills.get(key, [])
        if not items:
            continue
        values = " &nbsp;·&nbsp; ".join(_e(s) for s in items)
        body += f'<p class="skill-group-name">{label}</p>'
        body += f'<p class="skill-list">{values}</p>'

    if not body:
        return ""
    return f"<h2>TECHNICAL SKILLS</h2><hr>{body}"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_normalized_cv(normalized_cv: dict) -> bytes:
    """
    Recibe el normalized_cv dict y devuelve los bytes del PDF en estilo BBLABS.
    """
    full_name = _e(normalized_cv.get("full_name", "Candidate"))
    title = _e(normalized_cv.get("title", ""))
    profile = _e(normalized_cv.get("professional_profile", ""))
    years_exp = normalized_cv.get("years_of_experience")

    contact = _contact_line(normalized_cv)

    years_str = ""
    if years_exp is not None:
        years_str = f"<p class=\"meta-line\">{years_exp} years of professional experience</p>"

    sections = "".join([
        _section_education(normalized_cv.get("education", [])),
        _section_experience(normalized_cv.get("experience", [])),
        _section_certifications(normalized_cv.get("certifications", [])),
        _section_languages(normalized_cv.get("languages", [])),
        _section_skills(normalized_cv.get("technical_skills", {})),
    ])

    html_body = f"""
<html>
<head></head>
<body>
<p class="section-label">RIWI MATCH</p>
<h1>{full_name}</h1>
<p class="cv-title">{title}</p>
<p class="cv-contact">{contact}</p>
<h2>PROFESSIONAL PROFILE</h2><hr>
<p>{profile}</p>
{years_str}
{sections}
</body>
</html>
"""

    buf = io.BytesIO()
    story = fitz.Story(html=html_body, user_css=_CSS)
    writer = fitz.DocumentWriter(buf)

    mediabox = fitz.paper_rect("a4")
    # Márgenes: izquierda=60, arriba=60, derecha=60, abajo=60 (puntos)
    where = fitz.Rect(60, 60, mediabox.width - 60, mediabox.height - 60)

    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()

    writer.close()
    buf.seek(0)
    return buf.read()
