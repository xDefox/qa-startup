"""Фильтры представления: русские формы слов."""

from webscope.webapp.presentation import ru_plural

FORMS = ("проверка", "проверки", "проверок")


def test_ru_plural_singular():
    assert ru_plural(1, *FORMS) == "проверка"
    assert ru_plural(21, *FORMS) == "проверка"
    assert ru_plural(101, *FORMS) == "проверка"


def test_ru_plural_few():
    assert ru_plural(2, *FORMS) == "проверки"
    assert ru_plural(4, *FORMS) == "проверки"
    assert ru_plural(23, *FORMS) == "проверки"


def test_ru_plural_many():
    assert ru_plural(0, *FORMS) == "проверок"
    assert ru_plural(5, *FORMS) == "проверок"
    assert ru_plural(11, *FORMS) == "проверок"
    assert ru_plural(12, *FORMS) == "проверок"
    assert ru_plural(14, *FORMS) == "проверок"
    assert ru_plural(36, *FORMS) == "проверок"


def test_ru_plural_survives_bad_input():
    assert ru_plural("n/a", *FORMS) == "проверок"
