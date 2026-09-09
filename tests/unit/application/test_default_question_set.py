from src.application.profiling.default_question_set import (
    DEFAULT_FIRST_CONTACT_QUESTION_SET_NAME,
    DEFAULT_FIRST_CONTACT_QUESTIONS,
)
from src.infrastructure.db.models import QuestionType


def test_default_first_contact_question_set_has_the_six_expected_questions() -> None:
    assert DEFAULT_FIRST_CONTACT_QUESTION_SET_NAME.startswith(
        "PROFILING TELEFÓNICO DE PRIMER ACERCAMIENTO"
    )
    assert [question.type for question in DEFAULT_FIRST_CONTACT_QUESTIONS] == [
        QuestionType.YES_NO,
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.OPEN,
        QuestionType.MULTIPLE_CHOICE,
        QuestionType.YES_NO,
    ]
    assert len(DEFAULT_FIRST_CONTACT_QUESTIONS) == 6
    assert DEFAULT_FIRST_CONTACT_QUESTIONS[0].is_critical is True
    assert "datos personales" in DEFAULT_FIRST_CONTACT_QUESTIONS[0].text
    assert "expectativa salarial" in DEFAULT_FIRST_CONTACT_QUESTIONS[3].text
