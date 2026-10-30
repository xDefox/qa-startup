"""CLI webscope: scan / mcp / version."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .models import AuthCredentials, Severity, sort_findings
from .report import (
    build_fix_prompt,
    render_diff,
    render_html,
    render_json,
    render_junit,
    render_plain,
    render_sarif,
    render_text,
    render_trend,
)
from .scanner import ScanError, scan

FORMATS = ("text", "plain", "json", "html", "sarif", "junit")

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webscope",
        description="Детерминированный движок веб-QA: сканирование сайта и отчёт в машинно-читаемом виде.",
    )
    parser.add_argument("--version", action="version", version=f"webscope {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_auth_arguments(cmd: argparse.ArgumentParser) -> None:
        """Флаги входа на защищённый сайт (общие для scan и crawl)."""
        cmd.add_argument("--login", default=None, help="Логин: если задан, перед проверкой войдём на сайт")
        cmd.add_argument(
            "--password",
            default=None,
            help="Пароль (если не задан — переменная окружения WEBSCOPE_PASSWORD)",
        )
        cmd.add_argument(
            "--auth",
            choices=("basic", "form"),
            default="basic",
            help="basic — пароль на весь сайт, form — вход через форму на странице",
        )
        cmd.add_argument("--login-url", default=None, help="Адрес страницы входа (для --auth form)")

    scan_cmd = sub.add_parser("scan", help="Просканировать страницу")
    scan_cmd.add_argument("url", help="URL проверяемой страницы")
    scan_cmd.add_argument(
        "--checks",
        default="",
        help="Список проверок через запятую (по умолчанию все): a11y,content,forms,links,console,viewport",
    )
    scan_cmd.add_argument("--format", choices=FORMATS, default="text", help="Формат вывода")
    scan_cmd.add_argument("--out", type=Path, default=None, help="Записать вывод в файл")
    scan_cmd.add_argument(
        "--fail-on",
        choices=("critical", "serious", "moderate", "minor", "none"),
        default="serious",
        help="Severity, начиная с которого скан считается проваленным (код выхода 1)",
    )
    scan_cmd.add_argument("--evidence-dir", type=Path, default=None, help="Каталог для скриншотов находок")
    scan_cmd.add_argument("--baseline", type=Path, default=None, help="JSON-файл с известными находками (игнорируются)")
    scan_cmd.add_argument("--timeout", type=int, default=30000, help="Таймаут загрузки страницы, мс")
    scan_cmd.add_argument("--max-link-checks", type=int, default=20, help="Сколько внутренних ссылок проверять")
    scan_cmd.add_argument("--allow-private", action="store_true", help="Разрешить локальные адреса (для своих стендов)")
    scan_cmd.add_argument("--headed", action="store_true", help="Показывать браузер (по умолчанию headless)")
    scan_cmd.add_argument("--fix-prompt", action="store_true", help="Вместо отчёта вывести ТЗ для coding-агента")
    add_auth_arguments(scan_cmd)

    mcp_cmd = sub.add_parser("mcp", help="Запустить MCP-сервер (stdio)")
    mcp_cmd.add_argument("--allow-private", action="store_true", help="Разрешить локальные адреса")

    serve_cmd = sub.add_parser("serve", help="Запустить веб-интерфейс (для владельца сайта)")
    serve_cmd.add_argument("--host", default="127.0.0.1", help="Адрес прослушивания")
    serve_cmd.add_argument("--port", type=int, default=8000, help="Порт")
    serve_cmd.add_argument("--db", type=Path, default=Path("webscope.db"), help="Файл базы данных SQLite")
    serve_cmd.add_argument("--max-pages", type=int, default=20, help="Максимум страниц в обходе")
    serve_cmd.add_argument("--depth", type=int, default=2, help="Глубина обхода")
    serve_cmd.add_argument(
        "--check-interval",
        type=int,
        default=300,
        help="Как часто планировщик проверяет расписание, секунд",
    )
    serve_cmd.add_argument("--allow-private", action="store_true", help="Разрешить локальные адреса")

    crawl_cmd = sub.add_parser("crawl", help="Обойти сайт и проверить по одной странице каждого шаблона")
    crawl_cmd.add_argument("url", help="Адрес сайта")
    crawl_cmd.add_argument("--max-pages", type=int, default=30, help="Максимум страниц в обходе")
    crawl_cmd.add_argument("--depth", type=int, default=2, help="Глубина обхода по ссылкам")
    crawl_cmd.add_argument(
        "--ignore-robots", action="store_true", help="Игнорировать robots.txt (только для своих стендов)"
    )
    crawl_cmd.add_argument("--all-pages", action="store_true", help="Проверять все страницы, а не по одной на шаблон")
    crawl_cmd.add_argument("--checks", default="", help="Список проверок через запятую")
    crawl_cmd.add_argument("--format", choices=FORMATS, default="text", help="Формат вывода")
    crawl_cmd.add_argument("--out", type=Path, default=None, help="Записать вывод в файл")
    crawl_cmd.add_argument(
        "--history-dir", type=Path, default=None, help="Каталог для сохранения снимков и сравнения с прошлым"
    )
    crawl_cmd.add_argument("--fail-on", choices=("critical", "serious", "moderate", "minor", "none"), default="none")
    crawl_cmd.add_argument("--timeout", type=int, default=30000, help="Таймаут загрузки страницы, мс")
    crawl_cmd.add_argument("--allow-private", action="store_true", help="Разрешить локальные адреса")
    add_auth_arguments(crawl_cmd)

    diff_cmd = sub.add_parser("diff", help="Сравнить два снимка (прошлый и текущий)")
    diff_cmd.add_argument("old", type=Path, help="Файл старого снимка (JSON)")
    diff_cmd.add_argument("new", type=Path, help="Файл нового снимка (JSON)")
    diff_cmd.add_argument("--format", choices=("text", "json"), default="text")

    history_cmd = sub.add_parser("history", help="История прогонов по сайту")
    history_cmd.add_argument("url", help="Адрес сайта")
    history_cmd.add_argument("--dir", type=Path, required=True, help="Каталог истории")
    history_cmd.add_argument("--format", choices=("text", "json"), default="text")

    return parser


def _snippet_key(snippet: str | None) -> str:
    """Нормализованный ключ фрагмента: тот же, что в history._element_key."""
    return "".join((snippet or "").split())[:80].lower()


def _load_baseline(path: Path | None) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Читает baseline: известные пары (rule, selector) и (rule, snippet-key).

    Селектор может сдвинуться между версиями разметки, поэтому тот же известный
    дефект дополнительно распознаётся по нормализованному фрагменту элемента.
    """
    if path is None:
        return set(), set()
    data = json.loads(path.read_text(encoding="utf-8"))
    known_pairs: set[tuple[str, str]] = set()
    known_snippets: set[tuple[str, str]] = set()
    for item in data.get("findings", []):
        rule = item.get("rule", "")
        known_pairs.add((rule, item.get("selector") or ""))
        snippet = _snippet_key(item.get("snippet"))
        if snippet:
            known_snippets.add((rule, snippet))
    return known_pairs, known_snippets


def _is_known(finding, baseline: tuple[set[tuple[str, str]], set[tuple[str, str]]]) -> bool:
    pairs, snippets = baseline
    if (finding.rule, finding.selector or "") in pairs:
        return True
    snippet = _snippet_key(finding.snippet)
    return bool(snippet) and (finding.rule, snippet) in snippets


def _severity_threshold(name: str) -> int:
    if name == "none":
        return 99
    return Severity(name).rank


def _auth_from_args(args: argparse.Namespace) -> AuthCredentials | None:
    """Собирает учётные данные из флагов (None — сайт открыт, вход не нужен)."""
    if not getattr(args, "login", None):
        return None
    password = args.password if args.password is not None else os.environ.get("WEBSCOPE_PASSWORD", "")
    return AuthCredentials(
        kind=getattr(args, "auth", "basic"),
        login=args.login,
        password=password,
        login_url=getattr(args, "login_url", None),
    )


def cmd_scan(args: argparse.Namespace) -> int:
    url = args.url
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    checks = [name.strip() for name in args.checks.split(",") if name.strip()] or None

    try:
        result = scan(
            url,
            checks=checks,
            timeout_ms=args.timeout,
            headless=not args.headed,
            evidence_dir=args.evidence_dir,
            max_link_checks=args.max_link_checks,
            allow_private=args.allow_private,
            auth=_auth_from_args(args),
        )
    except ScanError as exc:
        print(f"webscope: ошибка — {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - верхняя граница ошибок CLI
        print(f"webscope: непредвиденная ошибка — {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    baseline = _load_baseline(args.baseline)
    if args.baseline is not None:
        result.findings = sort_findings([f for f in result.findings if not _is_known(f, baseline)])

    if args.fix_prompt:
        output = build_fix_prompt(result)
    elif args.format == "json":
        output = render_json(result)
    elif args.format == "html":
        output = render_html(result)
    elif args.format == "plain":
        output = render_plain(result)
    elif args.format == "sarif":
        output = render_sarif(result)
    elif args.format == "junit":
        output = render_junit(result)
    else:
        output = render_text(result)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"webscope: отчёт записан в {args.out}", file=sys.stderr)
    else:
        print(output)

    threshold = _severity_threshold(args.fail_on)
    if any(finding.severity.rank <= threshold for finding in result.findings):
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Запускает веб-интерфейс: сайт для владельца + планировщик проверок."""
    try:
        import uvicorn
    except ImportError:
        print(
            "webscope: нужен uvicorn и fastapi — установите: pip install 'webscope[web]'",
            file=sys.stderr,
        )
        return EXIT_ERROR

    from .webapp.app import create_app
    from .webapp.scheduler import ScanOptions

    options = ScanOptions(
        max_pages=args.max_pages,
        depth=args.depth,
        allow_private=args.allow_private,
    )
    app = create_app(
        db_path=args.db,
        options=options,
        check_interval=args.check_interval,
        allow_private=args.allow_private,
    )

    print(f"webscope: веб-интерфейс на http://{args.host}:{args.port}", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return EXIT_OK


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import serve

    serve(allow_private=args.allow_private)
    return EXIT_OK


def cmd_crawl(args: argparse.Namespace) -> int:
    from .history import diff_snapshots, latest_snapshot, save_snapshot, snapshot_from_result
    from .scanner import scan_site

    url = args.url if args.url.startswith(("http://", "https://")) else f"https://{args.url}"
    checks = [name.strip() for name in args.checks.split(",") if name.strip()] or None

    try:
        result, crawl_result = scan_site(
            url,
            max_pages=args.max_pages,
            max_depth=args.depth,
            respect_robots=not args.ignore_robots,
            all_pages=args.all_pages,
            checks=checks,
            timeout_ms=args.timeout,
            allow_private=args.allow_private,
            auth=_auth_from_args(args),
        )
    except ScanError as exc:
        print(f"webscope: ошибка — {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - верхняя граница ошибок CLI
        print(f"webscope: непредвиденная ошибка — {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    diff_payload = None
    if args.history_dir is not None:
        previous = latest_snapshot(args.history_dir, url)
        snapshot = snapshot_from_result(result)
        save_snapshot(snapshot, args.history_dir)
        if previous is not None:
            diff_payload = diff_snapshots(previous, snapshot)

    if args.format == "json":
        payload = result.to_dict()
        payload["crawl"] = crawl_result.to_dict()
        if diff_payload is not None:
            payload["diff"] = diff_payload.to_dict()
        output = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        header = (
            f"сайт: {url}\n"
            f"найдено страниц: {len(crawl_result.pages)} "
            f"(шаблонов: {len(crawl_result.templates)}), проверено: {result.pages_scanned}\n"
            f"sitemap: {'да' if crawl_result.sitemap_used else 'нет'} · "
            f"robots.txt: {'учтён' if crawl_result.robots_checked else 'не найден'}\n"
        )
        body = render_plain(result) if args.format == "plain" else render_text(result)
        output = header + "\n" + body
        if diff_payload is not None:
            output += "\n\n" + render_diff(diff_payload)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        print(f"webscope: отчёт записан в {args.out}", file=sys.stderr)
    else:
        print(output)

    threshold = _severity_threshold(args.fail_on)
    if any(finding.severity.rank <= threshold for finding in result.findings):
        return EXIT_FINDINGS
    return EXIT_OK


def cmd_diff(args: argparse.Namespace) -> int:
    from .history import diff_snapshots, load_snapshot

    try:
        old = load_snapshot(args.old)
        new = load_snapshot(args.new)
    except (OSError, ValueError) as exc:
        print(f"webscope: не удалось прочитать снимок — {exc}", file=sys.stderr)
        return EXIT_ERROR

    diff = diff_snapshots(old, new)
    if args.format == "json":
        print(json.dumps(diff.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_diff(diff))
    return EXIT_OK


def cmd_history(args: argparse.Namespace) -> int:
    from .history import trend

    points = trend(args.dir, args.url)
    if args.format == "json":
        print(json.dumps(points, ensure_ascii=False, indent=2))
    else:
        print(render_trend(points))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "crawl":
        return cmd_crawl(args)
    if args.command == "diff":
        return cmd_diff(args)
    if args.command == "history":
        return cmd_history(args)
    if args.command == "mcp":
        return cmd_mcp(args)
    if args.command == "serve":
        return cmd_serve(args)
    parser.error(f"неизвестная команда: {args.command}")
    return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
