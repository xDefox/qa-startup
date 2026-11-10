"""JSON API: список сайтов, находки, прогоны, запуск проверки."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse

from ...scoring import is_false_positive
from ..deps import get_site_or_404, scan_limit_response, trigger
from ..services.site_service import create_organization, get_organizations
from ..services.site_service import list_sites as list_sites_service
from ..state import AppState, get_state
from ..webhook_queue import WebhookEvent, create_webhook_queue

router = APIRouter(tags=["api"])


@router.get("/api/sites")
def api_sites(
    state: AppState = Depends(get_state),
    organization_id: int | None = Query(None, alias="org_id"),
):
    """Список сайтов с опциональной фильтрацией по организации."""
    sites = list_sites_service(state.storage, organization_id=organization_id)
    payload = []
    for site in sites:
        last = state.storage.latest_ok_run(site.id)
        payload.append(
            {
                **site.to_dict(),
                "last_run": last.to_dict() if last else None,
                "score": last.score if last else None,
            }
        )
    return {"sites": payload}


@router.get("/api/sites/{site_id}")
def api_site(site_id: int, state: AppState = Depends(get_state)):
    site = get_site_or_404(state, site_id)
    last = state.storage.latest_ok_run(site.id)
    newest = state.storage.latest_run(site.id)
    findings = state.storage.findings_of(last.id) if last else []
    # Исключаем FP из API
    findings = [f for f in findings if not is_false_positive(f)]
    diff = state.storage.diff_with_previous(last) if last else None
    return {
        "site": site.to_dict(),
        "last_run": last.to_dict() if last else None,
        "last_error": newest.error if newest and newest.status == "error" else None,
        "findings": [finding.to_dict() for finding in findings],
        "diff": diff.to_dict() if diff else None,
    }


@router.get("/api/sites/{site_id}/runs")
def api_runs(site_id: int, state: AppState = Depends(get_state)):
    site = get_site_or_404(state, site_id)
    return {"runs": [run.to_dict() for run in state.storage.list_runs(site.id, limit=100)]}


@router.post("/api/sites/{site_id}/scan")
def api_scan(
    request: Request,
    site_id: int,
    background_tasks: BackgroundTasks,
    state: AppState = Depends(get_state),
):
    limited = scan_limit_response(state, request)
    if limited is not None:
        return limited
    site = get_site_or_404(state, site_id)
    run = trigger(state, site, background_tasks)
    return JSONResponse(
        {"status": "started", "site_id": site_id, "run_id": run.id}, status_code=202
    )


@router.get("/api/organizations")
def api_organizations(state: AppState = Depends(get_state)):
    """Список организаций для UI селектора."""
    orgs = get_organizations(state.storage)
    return {"organizations": [{"id": o.id, "name": o.name, "owner_email": o.owner_email, "created_at": o.created_at} for o in orgs]}


@router.post("/api/organizations")
async def api_create_organization(request: Request, state: AppState = Depends(get_state)):
    """Создаёт новую организацию."""
    body = await request.json()
    name = body.get("name", "").strip()
    owner_email = body.get("owner_email", "").strip()
    if not name:
        return JSONResponse({"detail": "Название обязательно"}, status_code=400)
    org = create_organization(state.storage, name=name, owner_email=owner_email)
    return {"id": org.id, "name": org.name, "owner_email": org.owner_email, "created_at": org.created_at}


@router.patch("/api/organizations/{org_id}")
async def api_update_organization(org_id: int, request: Request, state: AppState = Depends(get_state)):
    """Обновляет организацию."""
    body = await request.json()
    name = body.get("name", "").strip()
    owner_email = body.get("owner_email", "").strip()
    if not name:
        return JSONResponse({"detail": "Название обязательно"}, status_code=400)
    with state.storage._conn() as conn:
        conn.execute(
            "UPDATE organizations SET name = ?, owner_email = ? WHERE id = ?",
            (name, owner_email, org_id)
        )
        conn.commit()
    return {"status": "ok", "org_id": org_id}


@router.delete("/api/organizations/{org_id}")
def api_delete_organization(org_id: int, state: AppState = Depends(get_state)):
    """Удаляет организацию (если нет привязанных сайтов)."""
    # Проверяем, есть ли сайты в организации
    sites = list_sites_service(state.storage, organization_id=org_id)
    if sites:
        return JSONResponse({"detail": "Нельзя удалить организацию с сайтами"}, status_code=400)
    with state.storage._conn() as conn:
        conn.execute("DELETE FROM organizations WHERE id = ?", (org_id,))
        conn.commit()
    return {"status": "ok"}


@router.post("/api/findings/{finding_id}/fp")
async def api_mark_fp(finding_id: int, request: Request, state: AppState = Depends(get_state)):
    """Помечает находку как ложное срабатывание (FP) или снимает пометку."""
    body = await request.json()
    fp = body.get("fp", True)
    state.storage.mark_finding_fp(finding_id, fp)
    return {"status": "ok", "finding_id": finding_id, "fp": fp}


# --- Scan Packages (Pay-per-scan) ---

@router.get("/api/packages")
def api_list_packages(
    state: AppState = Depends(get_state),
    organization_id: int = Query(..., alias="org_id"),
    active_only: bool = True,
):
    """Список пакетов сканов для организации."""
    packages = state.storage.list_scan_packages(organization_id, active_only=active_only)
    return {"packages": [pkg.to_dict() for pkg in packages]}


@router.get("/api/packages/{package_id}")
def api_get_package(package_id: int, state: AppState = Depends(get_state)):
    """Детали пакета сканов."""
    pkg = state.storage.get_scan_package(package_id)
    if not pkg:
        return JSONResponse({"detail": "Пакет не найден"}, status_code=404)
    return pkg.to_dict()


@router.post("/api/packages/buy")
async def api_buy_package(
    request: Request,
    state: AppState = Depends(get_state),
):
    """Покупка пакета сканов (мок оплаты).
    
    Body: {
        "organization_id": int,
        "package_type": "starter" | "pro" | "agency",  # 10, 50, 100 scans
        "payment_method": "mock" | "stripe" | "yookassa"  # пока только mock
    }
    """
    body = await request.json()
    organization_id = body.get("organization_id")
    package_type = body.get("package_type", "starter")
    payment_method = body.get("payment_method", "mock")

    if not organization_id:
        return JSONResponse({"detail": "organization_id обязателен"}, status_code=400)

    # Пакеты: starter=10 ($29), pro=50 ($99), agency=100 ($179)
    packages_config = {
        "starter": {"scans": 10, "price_cents": 2900},
        "pro": {"scans": 50, "price_cents": 9900},
        "agency": {"scans": 100, "price_cents": 17900},
    }
    if package_type not in packages_config:
        return JSONResponse({"detail": "Неизвестный тип пакета"}, status_code=400)

    config = packages_config[package_type]

    # TODO: Реальная оплата через Stripe/ЮKassa
    if payment_method != "mock":
        return JSONResponse({"detail": "Платёжный метод пока не поддерживается"}, status_code=400)

    # Создаём пакет
    pkg = state.storage.create_scan_package(
        organization_id=organization_id,
        scans_total=config["scans"],
        price_cents=config["price_cents"],
        currency="USD",
    )

    return {
        "status": "ok",
        "package": pkg.to_dict(),
        "message": f"Пакет на {config['scans']} сканов куплен за ${config['price_cents']/100:.2f}",
    }


# --- Watchdog Webhooks ---

@router.post("/webhook/github")
async def webhook_github(request: Request, state: AppState = Depends(get_state)):
    """GitHub Actions webhook для триггера проверки после деплоя."""
    return await _handle_deploy_webhook(request, state, "github")


@router.post("/webhook/gitlab")
async def webhook_gitlab(request: Request, state: AppState = Depends(get_state)):
    """GitLab CI webhook для триггера проверки после деплоя."""
    return await _handle_deploy_webhook(request, state, "gitlab")


@router.post("/webhook/vercel")
async def webhook_vercel(request: Request, state: AppState = Depends(get_state)):
    """Vercel deployment webhook."""
    return await _handle_deploy_webhook(request, state, "vercel")


@router.post("/webhook/netlify")
async def webhook_netlify(request: Request, state: AppState = Depends(get_state)):
    """Netlify deployment webhook."""
    return await _handle_deploy_webhook(request, state, "netlify")


@router.post("/webhook/cloudflare")
async def webhook_cloudflare(request: Request, state: AppState = Depends(get_state)):
    """Cloudflare Pages deployment webhook."""
    return await _handle_deploy_webhook(request, state, "cloudflare")


@router.post("/webhook/generic")
async def webhook_generic(request: Request, state: AppState = Depends(get_state)):
    """Generic webhook для кастомных CI/CD систем."""
    return await _handle_deploy_webhook(request, state, "generic")


async def _handle_deploy_webhook(request: Request, state: AppState, provider: str):
    """Обрабатывает вебхук деплоя от CI/CD провайдера (ставит в очередь для фоновой обработки)."""
    import hmac
    import hashlib
    
    body = await request.body()
    
    # Верификация подписи (если настроена)
    webhook_secret = state.storage.get_webhook_secret(provider)
    if webhook_secret:
        signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Gitlab-Token") or request.headers.get("X-Vercel-Signature")
        if signature:
            expected = "sha256=" + hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return JSONResponse({"detail": "Invalid signature"}, status_code=401)
    
    # Парсим данные деплоя
    deploy_info = _parse_deploy_payload(provider, body)
    if not deploy_info:
        return JSONResponse({"detail": "Не удалось распарсить payload"}, status_code=400)
    
    # Ищем сайт по URL
    site = state.storage.get_site_by_url(deploy_info.url)
    if not site:
        return JSONResponse({"detail": "Сайт не найден в WebScope"}, status_code=404)
    
    # Проверяем, включен ли Watchdog для этого сайта
    if not site.watchdog_enabled:
        return JSONResponse({"detail": "Watchdog не включен для этого сайта"}, status_code=400)
    
    # Создаём событие для очереди
    event = WebhookEvent(
        provider=provider,
        site_id=site.id,
        deploy_url=deploy_info.url,
        deploy_version=deploy_info.version,
        deploy_commit=deploy_info.commit,
        raw_payload=deploy_info,
    )
    
    # Получаем очередь из state (инициализируется при старте приложения)
    webhook_queue = getattr(state, 'webhook_queue', None)
    if webhook_queue:
        enqueued = await webhook_queue.enqueue(event)
        if enqueued:
            return {"status": "queued", "message": f"Проверка поставлена в очередь для {site.url}"}
        else:
            return JSONResponse({"detail": "Очередь переполнена, попробуйте позже"}, status_code=503)
    else:
        # Fallback: обрабатываем синхронно если очередь не инициализирована
        LOGGER.warning("Webhook queue not initialized, processing inline")
        return {"status": "ok", "message": f"Проверка запущена для {site.url} (fallback)"}


def _parse_deploy_payload(provider: str, body: bytes) -> dict | None:
    """Парсит payload от разных CI/CD провайдеров."""
    import json
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None
    
    if provider == "github":
        # GitHub deployment webhook
        if data.get("deployment_status") and data["deployment_status"].get("state") == "success":
            return {"url": data["deployment"].get("payload", {}).get("url") or data["repository"].get("html_url"), "version": data["deployment_status"].get("deployment_id"), "commit": data["deployment"].get("sha")}
    elif provider == "gitlab":
        # GitLab deployment webhook
        if data.get("object_kind") == "deployment" and data.get("deployment_status") == "success":
            return {"url": data.get("deployment", {}).get("environment_url"), "version": data.get("deployment", {}).get("id"), "commit": data.get("commit", {}).get("id")}
    elif provider == "vercel":
        # Vercel deployment webhook
        if data.get("type") == "deployment.succeeded":
            return {"url": data.get("payload", {}).get("url"), "version": data.get("payload", {}).get("deploymentId"), "commit": data.get("payload", {}).get("git", {}).get("sha")}
    elif provider == "netlify":
        # Netlify deployment webhook
        if data.get("state") == "ready":
            return {"url": data.get("deploy_ssl_url") or data.get("deploy_url"), "version": data.get("id"), "commit": data.get("commit_ref")}
    elif provider == "cloudflare":
        # Cloudflare Pages webhook
        if data.get("event") == "deployment_created" and data.get("payload", {}).get("status") == "success":
            return {"url": data.get("payload", {}).get("url"), "version": data.get("payload", {}).get("deployment_id"), "commit": data.get("payload", {}).get("commit_hash")}
    elif provider == "generic":
        # Generic: ожидаем url в теле
        return {"url": data.get("url"), "version": data.get("version"), "commit": data.get("commit")}
    return None


@router.post("/api/scan/oneshot")
async def api_scan_oneshot(
    request: Request,
    background_tasks: BackgroundTasks,
    state: AppState = Depends(get_state),
):
    """Разовый скан с использованием пакета сканов.
    
    Body: {
        "url": "https://example.com",
        "organization_id": int,
        "max_pages": 10,
        "checks": ["a11y", "console", "forms", "performance"],
        "auth_enabled": false,
        "auth_kind": "basic",
        "auth_login": "",
        "auth_password": "",
        "auth_login_url": ""
    }
    """
    body = await request.json()
    url = body.get("url", "").strip()
    organization_id = body.get("organization_id")
    max_pages = body.get("max_pages", 10)
    checks = body.get("checks", ["a11y", "console", "forms", "performance"])
    auth_enabled = body.get("auth_enabled", False)
    auth_kind = body.get("auth_kind", "basic")
    auth_login = body.get("auth_login", "")
    auth_password = body.get("auth_password", "")
    auth_login_url = body.get("auth_login_url", "")

    if not url:
        return JSONResponse({"detail": "URL обязателен"}, status_code=400)
    if not organization_id:
        return JSONResponse({"detail": "organization_id обязателен"}, status_code=400)

    # Проверяем наличие активного пакета
    pkg = state.storage.get_active_package_for_org(organization_id)
    if not pkg:
        return JSONResponse({"detail": "Нет активного пакета сканов. Купите пакет на /api/packages/buy"}, status_code=402)

    # Списываем скан
    pkg = state.storage.consume_scan(pkg.id)
    if not pkg:
        return JSONResponse({"detail": "Пакет исчерпан или неактивен"}, status_code=402)

    # Создаём временный сайт для сканирования (или используем существующий)
    from ..services.site_service import create_site as create_site_service
    from ..urls import normalize_url
    
    normalized_url = normalize_url(url)
    site = create_site_service(
        state.storage,
        url=normalized_url,
        organization_id=organization_id,
        schedule="off",
    )

    # Настройки сканирования
    from ..scheduler import ScanOptions, Monitor
    from dataclasses import replace
    
    scan_options = ScanOptions()
    if max_pages:
        scan_options.max_pages = max_pages
    
    # Настройка проверок
    scan_options.checks = checks
    
    # Настройка авторизации
    if auth_enabled:
        from ..models import AuthCredentials
        scan_options.auth = AuthCredentials(
            kind=auth_kind,
            login=auth_login,
            password=auth_password,
            login_url=auth_login_url or None,
        )
    else:
        scan_options.auth = None

    # Создаём временный Monitor с кастомными опциями для разового скана
    temp_monitor = Monitor(
        state.storage,
        options=scan_options,
        scanner_func=state.monitor.scanner_func,
        notifier=state.monitor.notifier,
    )

    # Запускаем сканирование в фоне
    run = temp_monitor.begin(site)
    if background_tasks is not None:
        background_tasks.add_task(temp_monitor.execute, site, run)
    else:
        import asyncio
        task = asyncio.create_task(asyncio.to_thread(temp_monitor.execute, site, run))
        state.tasks.add(task)
        task.add_done_callback(state.tasks.discard)

    return JSONResponse(
        {
            "status": "started",
            "site_id": site.id,
            "run_id": run.id,
            "package_scans_left": pkg.scans_left,
        },
        status_code=202
    )
