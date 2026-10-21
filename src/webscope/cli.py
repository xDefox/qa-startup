"""CLI webscope: scan / mcp / version."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .models import Severity, sort_findings
from .report import build_fix_prompt, render_html, render_json, render_junit, render_sarif, render_text
from .scanner import ScanError, scan

FORMATS = ("text", "json", "html", "sarif", "junit")

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

    mcp_cmd = sub.add_parser("mcp", help="Запустить MCP-сервер (stdio)")
    mcp_cmd.add_argument("--allow-private", action="store_true", help="Разрешить локальные адреса")

    return parser


def _load_baseline(path: Path | None) -> set[tuple[str, str]]:
    """Читает baseline: список пар (rule, selector), которые считаются известными."""
    if path is None:
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    known: set[tuple[str, str]] = set()
    for item in data.get("findings", []):
        known.add((item.get("rule", ""), item.get("selector") or ""))
    return known


def _severity_threshold(name: str) -> int:
    if name == "none":
        return 99
    return Severity(name).rank


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
        )
    except ScanError as exc:
        print(f"webscope: ошибка — {exc}", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - верхняя граница ошибок CLI
        print(f"webscope: непредвиденная ошибка — {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    baseline = _load_baseline(args.baseline)
    if baseline:
        result.findings = sort_findings([f for f in result.findings if (f.rule, f.selector or "") not in baseline])

    if args.fix_prompt:
        output = build_fix_prompt(result)
    elif args.format == "json":
        output = render_json(result)
    elif args.format == "html":
        output = render_html(result)
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


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import serve

    serve(allow_private=args.allow_private)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scan":
        return cmd_scan(args)
    if args.command == "mcp":
        return cmd_mcp(args)
    parser.error(f"неизвестная команда: {args.command}")
    return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
