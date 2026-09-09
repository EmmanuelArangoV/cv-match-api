import pymupdf as fitz

from src.infrastructure.cv.pdf_renderer import extract_jd_highlight_terms, render_normalized_cv


def _profile() -> dict:
    return {
        "full_name": "Ada Lovelace",
        "email": "ada@example.com",
        "phone": "+57 300 123 4567",
        "location": "Medellín, Colombia",
        "linkedin_url": "https://linkedin.example/ada",
        "github_url": "https://github.example/ada",
        "title": "Backend Engineer",
        "professional_profile": (
            "Desarrolladora de Python y React con experiencia en APIs. "
            "Contacto: ada@example.com y +57 300 123 4567."
        ),
        "technical_skills": {
            "programming_languages": ["Python", "TypeScript"],
            "frameworks_and_libraries": ["React"],
            "cloud_and_devops": [],
            "databases": ["PostgreSQL"],
            "tools_and_platforms": [],
            "architectures_and_patterns": [],
            "other": [],
        },
        "experience": [
            {
                "company": "Example Co",
                "role": "Backend Engineer",
                "employment_type": "Full-time",
                "start_year": 2022,
                "is_current": True,
                "responsibilities": ["Construí APIs con Python y PostgreSQL."],
            }
        ],
    }


def test_extract_jd_highlight_terms_uses_explicit_skills_and_aliases() -> None:
    terms = extract_jd_highlight_terms(
        _profile(),
        "Buscamos experiencia con React.js, PostgreSQL y Python.",
    )

    assert terms == ["Python", "React", "PostgreSQL"]


def test_normalized_pdf_redacts_contact_data_and_localizes_sections() -> None:
    pdf_bytes = render_normalized_cv(
        _profile(), language="en", highlight_terms=["Python", "React", "PostgreSQL"]
    )
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    text = "".join(page.get_text() for page in document)

    assert document.page_count >= 1
    assert "PROFESSIONAL PROFILE" in text
    assert "TECHNICAL SKILLS" in text
    assert "ada@example.com" not in text
    assert "+57 300 123 4567" not in text
    assert "Medellín, Colombia" not in text
    assert "linkedin.example" not in text
    assert "github.example" not in text
