from src.application.profiling.default_question_set import (
    DEFAULT_FIRST_CONTACT_QUESTION_SET_NAME,
    DEFAULT_FIRST_CONTACT_QUESTIONS,
)
from src.infrastructure.db.models import QuestionType


def test_default_first_contact_question_set_has_the_expected_humanized_questions() -> None:
    assert DEFAULT_FIRST_CONTACT_QUESTION_SET_NAME.startswith(
        "PROFILING TELEFÓNICO DE PRIMER ACERCAMIENTO"
    )
    assert [question.type for question in DEFAULT_FIRST_CONTACT_QUESTIONS] == [
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.CLOSED,
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.OPEN,
    ]
    assert len(DEFAULT_FIRST_CONTACT_QUESTIONS) == 5
    assert all(
        "datos personales" not in question.text for question in DEFAULT_FIRST_CONTACT_QUESTIONS
    )
    assert "expectativa salarial" in DEFAULT_FIRST_CONTACT_QUESTIONS[2].text
    assert "indefinida" not in DEFAULT_FIRST_CONTACT_QUESTIONS[2].text
    assert "contractor" not in DEFAULT_FIRST_CONTACT_QUESTIONS[2].text
    assert "compromiso personal" in DEFAULT_FIRST_CONTACT_QUESTIONS[4].text
