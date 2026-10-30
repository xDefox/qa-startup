"""CI-конфиг: джоба, которая гоняет pytest, должна ставить extras `web`.

pytest собирает все файлы тестов, даже если `-m` отсеивает их на запуске.
Сборка импортирует `fastapi`, `jinja2`, `httpx` — они лежат в extra `web`.
Джоба `test-browser` когда-то ставила только `.[dev]`: сборка падала на
импорте, pytest возвращал 2 («Interrupted: 1 error during collection»),
а в логах это выглядело как «браузер не работает».
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
WEB_EXTRAS = ("web",)


def _jobs() -> dict[str, str]:
    """Разобрать workflow на джобы: имя -> текст джобы.

    YAML-парсера в зависимостях нет (и ради одного файла он не нужен):
    структура фиксированная — секция `jobs:`, имена джоб с отступом в два
    пробела, тело джобы — всё до следующего имени.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"(?m)^jobs:\s*$\n", text)
    assert match, "в ci.yml пропала секция jobs"
    body = text[match.end() :]

    jobs: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in body.splitlines():
        header = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if header:
            if current is not None:
                jobs[current] = "\n".join(lines)
            current = header.group(1)
            lines = []
        elif line.strip():
            lines.append(line)
    if current is not None:
        jobs[current] = "\n".join(lines)
    return jobs


def _pip_installs(job: str) -> list[str]:
    return [line.strip() for line in job.splitlines() if "pip install" in line]


def _has_web_extra(job: str) -> bool:
    return any(re.search(r"\[[^\]]*\bweb\b[^\]]*\]", line) for line in _pip_installs(job))


def test_ci_workflow_is_parseable() -> None:
    jobs = _jobs()
    assert {"lint", "test", "test-browser"} <= jobs.keys()


def test_jobs_running_pytest_install_web_extras() -> None:
    offenders = []
    for name, job in _jobs().items():
        runs_pytest = "pytest" in job
        if runs_pytest and not _has_web_extra(job):
            offenders.append(name)
    assert not offenders, (
        f"эти джобы гоняют pytest, но не ставят extra `web` (сборка упадёт на импорте fastapi): {sorted(offenders)}"
    )


def test_browser_job_actually_runs_browser_tests() -> None:
    """Джоба не должна остаться пустой заготовкой без браузерных тестов."""
    job = _jobs()["test-browser"]
    assert 'pytest -m "browser"' in job
    assert "playwright install" in job
