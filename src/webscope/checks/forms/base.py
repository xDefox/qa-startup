"""Формы: проверяем, что заявка действительно может уйти.

Вместо эвристик по разметке мы делаем поведенческий тест: подставляем в
поля небольшие тестовые значения, кликаем кнопку отправки (с отловом
сетевых запросов) и смотрим, ушла ли заявка. Если nothing happened — находка
законна. Это единственный способ доказать, что кнопка ни к чему не подключена,
особенно на сайтах с jQuery delegation, React delegation или своих JavaScript-обработчиков.

Кроме поведенческого теста мы продолжаем оценивать классические проблемы
доступности: подписи полей, имена атрибутов, placeholder вместо label.
Типовые проблемы ввода: novalidate без своей валидации, type="text" у поля email,
отсутствующий autocomplete у email-поля, отсутствующий inputmode у телефона,
кнопка отправки без доступного имени.
"""

from __future__ import annotations

from ...context import ScanContext
from ...models import Finding, Severity

_SUBMIT_EVENTS = frozenset({"click", "submit", "pointerdown", "mousedown", "touchstart", "touchend", "keydown", "keyup"})

_TEST_FIELDS = {
    "name": "Тест",
    "email": "test@example.com",
    "tel": "+79991234567",
    "message": "webscope test",
}


# NOTE: строка, а не функция — page.evaluate(COLLECT) в run() ожидает исходник скрипта.
COLLECT = r"""
    () => {
      const u = window.__webscopeUtils;
      const skipped = ['hidden', 'submit', 'button', 'reset', 'image'];
      const visibleControl = (el) => {
        const tag = el.tagName.toLowerCase();
        if (!['input', 'select', 'textarea'].includes(tag)) return false;
        const type = (el.getAttribute('type') || '').toLowerCase();
        if (skipped.includes(type)) return false;
        return u.visible(el);
      };
      const controlsIn = (node) => Array.from(node.querySelectorAll('input, select, textarea')).filter(visibleControl);
      const textOf = (el) => (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '').trim();
      const submitWords = /отправ|заказать|оставить заяв|записаться|купить|оформить|позвонить/i;
      const submitLike = (el) => {
        const tag = el.tagName.toLowerCase();
        const type = (el.getAttribute('type') || '').toLowerCase();
        if (tag === 'input') return type === 'submit' || type === 'image';
        if (tag !== 'button') return false;
        if (type === 'submit' || type === '') return true;
        return submitWords.test(textOf(el));
      };

      const forms = Array.from(document.querySelectorAll('form')).map((form) => ({
        selector: u.cssPath(form),
        snippet: (form.outerHTML || '').slice(0, 240),
        action: form.getAttribute('action'),
        actionResolved: form.action || '',
        method: (form.getAttribute('method') || 'get').toLowerCase(),
        hasOnsubmit: !!form.getAttribute('onsubmit'),
        novalidate: form.hasAttribute('novalidate'),
        controls: controlsIn(form).map((el) => ({
          selector: u.cssPath(el),
          name: el.getAttribute('name'),
          type: (el.getAttribute('type') || el.tagName || '').toLowerCase(),
          snippet: (el.outerHTML || '').slice(0, 200),
          hasPlaceholder: el.hasAttribute('placeholder'),
          id: el.id || '',
          autocomplete: (el.getAttribute('autocomplete') || '').trim().toLowerCase(),
          inputmode: (el.getAttribute('inputmode') || '').trim().toLowerCase(),
          hasLabelFor: !!(el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]')),
          hasWrappedLabel: !!el.closest('label'),
          hasAriaLabel: !!(el.getAttribute('aria-label') || '').trim(),
          hasAriaLabelledby: !!(el.getAttribute('aria-labelledby') || '').trim(),
          hasTitle: !!(el.getAttribute('title') || '').trim(),
        })),
        buttons: Array.from(form.querySelectorAll('button, input[type="submit"], input[type="image"]')).map((el) => ({
          selector: u.cssPath(el),
          tag: el.tagName.toLowerCase(),
          type: (el.getAttribute('type') || '').toLowerCase(),
          text: textOf(el).slice(0, 80),
          submitLike: submitLike(el),
          snippet: (el.outerHTML || '').slice(0, 200),
        })),
      }));

      const orphans = [];
      for (const btn of Array.from(document.querySelectorAll('button, input[type="submit"], input[type="image"]'))) {
        const tag = btn.tagName.toLowerCase();
        if (tag === 'button' && btn.closest('form')) continue;
        if (btn.getAttribute('form')) continue;
        if (!submitLike(btn)) continue;
        if (!u.visible(btn)) continue;
        let node = btn.parentElement;
        let controls = [];
        let container = null;
        for (let depth = 0; depth < 4 && node && node !== document.body; depth += 1, node = node.parentElement) {
          const found = controlsIn(node);
          if (found.length) {
            controls = found;
            container = node;
            break;
          }
        }
        if (!controls.length) continue;
        orphans.push({
          selector: u.cssPath(btn),
          snippet: (btn.outerHTML || '').slice(0, 220),
          text: textOf(btn).slice(0, 80),
          controls: controls.length,
          controls_without_name: controls.filter((el) => !el.getAttribute('name')).length,
          container: container ? u.cssPath(container) : '',
        });
      }

      return { forms, orphans };
    }
    """


def _probe_submission(page: object, selector: str, container_selector: str | None = None) -> bool:
    attempted: dict[str, bool] = {"submit": False}

    def on_request(request) -> None:
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            attempted["submit"] = True

    def route_handler(route) -> None:
        if route.request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            route.abort()
        else:
            route.continue_()

    page.on("request", on_request)
    page.route("**/*", route_handler)

    try:
        page.evaluate(
            """() => {
                const modals = Array.from(document.querySelectorAll('[role="dialog"], .modal, .popup, [class*="modal"], [class*="popup"]'));
                for (const m of modals) {
                    if (m.offsetWidth > 0 && m.offsetHeight > 0) {
                        m.style.display = 'none';
                    }
                }
                const overlays = Array.from(document.querySelectorAll('[class*="overlay"], [class*="banner"], [class*="toast"]'));
                for (const o of overlays) {
                    if (o.offsetWidth > 0 && o.offsetHeight > 0) {
                        o.style.display = 'none';
                    }
                }
            }""",
        )
    except Exception:  # noqa: BLE001, S110 - элемент мог не проявиться: продолжаем
        pass

    js_fill = """([sel, fillMap]) => {
        const btn = document.querySelector(sel);
        if (!btn) return false;
        let container = btn;
        for (let depth = 0; depth < 5 && container && container !== document.body; depth++) {
            const found = container.querySelectorAll('input, select, textarea').length;
            if (found && container !== btn) break;
            container = container.parentElement;
        }
        const form = btn.closest('form');
        if (fillMap && typeof fillMap === 'object') {
            for (const [name, value] of Object.entries(fillMap)) {
                const el = container.querySelector(`[name="${name}"]`);
                if (el) {
                    el.value = value;
                    const event = new Event('input', { bubbles: true });
                    el.dispatchEvent(event);
                }
            }
        }
        try {
            btn.click();
            return true;
        } catch (e) {
            return false;
        }
    }"""

    test_data = _TEST_FIELDS if selector.lower().startswith("#feedback") else {}
    try:
        page.evaluate(js_fill, (selector, test_data))
    except Exception:  # noqa: BLE001, S110 - поле не нашлось/не заполнилось: продолжаем
        pass

    before_html = page.evaluate("document.body.innerHTML")
    before_url = page.url

    try:
        page.click(selector, timeout=3000)
    except Exception:  # noqa: BLE001
        page.unroute("**/*", route_handler)
        page.remove_listener("request", on_request)
        return False

    page.wait_for_timeout(2500)

    after_html = page.evaluate("document.body.innerHTML")
    after_url = page.url

    html_changed = before_html != after_html
    url_changed = after_url != before_url

    page.unroute("**/*", route_handler)
    page.remove_listener("request", on_request)

    return html_changed or url_changed


def _ensure_fields_in_container(page: object, button_selector: str, min_fields: int = 1) -> bool:
    js = """([buttonSelector, minFields]) => {
        const btn = document.querySelector(buttonSelector);
        if (!btn) return {found: false, count: 0};
        let count = 0, depth = 0;
        let node = btn;
        while (node && node !== document.body && depth < 5) {
            count += node.querySelectorAll('input, select, textarea').length;
            if (count > 0 && node !== btn) break;
            node = node.parentElement;
            depth++;
        }
        return {found: count >= minFields, count};
    }"""
    result = page.evaluate(js, (button_selector, min_fields))
    return result["found"]


def run(page: object, ctx: ScanContext) -> list[Finding]:
    try:
        data = page.evaluate(COLLECT)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - страница могла не догрузиться
        return []

    findings: list[Finding] = []
    url = ctx.final_url
    checked_selectors: set[str] = set()

    for form in data.get("forms") or []:
        if form.get("novalidate"):
            findings.append(
                Finding(
                    rule="forms/novalidate",
                    severity=Severity.MODERATE,
                    title="Форма отключает браузерную валидацию",
                    message="У формы задан novalidate — встроенные проверки полей отключены, своих проверок нет.",
                    url=url,
                    selector=form.get("selector"),
                    snippet=form.get("snippet"),
                    source="webscope.forms",
                ),
            )

    # Контролы и кнопки поднимаются из каждой формы — COLLECT возвращает
    # {forms, orphans} и плоского "controls" верхнего уровня нет.
    all_controls = [c for form in data.get("forms") or [] for c in form.get("controls") or []]

    for control in all_controls:
        labelled = (
            control["hasLabelFor"]
            or control["hasWrappedLabel"]
            or control["hasAriaLabel"]
            or control["hasAriaLabelledby"]
            or control["hasTitle"]
        )
        if not labelled and control.get("hasPlaceholder"):
            findings.append(
                Finding(
                    rule="forms/placeholder-as-label",
                    severity=Severity.MODERATE,
                    title="Поле без подписи, только placeholder",
                    message="Placeholder исчезает при вводе и не заменяет <label>.",
                    url=url,
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    help_url="https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html",
                    details={"type": control.get("type")},
                ),
            )
        if not labelled and not control.get("hasPlaceholder"):
            findings.append(
                Finding(
                    rule="forms/control-without-label",
                    severity=Severity.SERIOUS,
                    title="Поле формы без подписи",
                    message="У элемента управления нет <label>, aria-label или title.",
                    url=url,
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    help_url="https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html",
                    details={"type": control.get("type")},
                ),
            )
        if not control.get("name"):
            findings.append(
                Finding(
                    # Старое имя control-without-name в PLAIN_IMPACT/ACCEPTANCE сохранено как алиас.
                    rule="forms/field-without-name",
                    severity=Severity.MODERATE,
                    title="Поле без атрибута name",
                    message="Без name значение не отправится в форму (кроме JS-обработчиков).",
                    url=url,
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    details={"type": control.get("type")},
                ),
            )

        # Поля, очевидно названные email/телефоном по name/id: тип и вводные
        # атрибуты (autocomplete, inputmode) должны быть правильными.
        name_or_id = ((control.get("name") or "") + " " + (control.get("id") or "")).lower()
        if "email" in name_or_id and control["type"] != "email" and control["type"] not in ("submit", "image"):
            findings.append(
                Finding(
                    rule="forms/email-wrong-type",
                    severity=Severity.MODERATE,
                    title="Поле для e-mail не типа email",
                    message="Поле названо email, но type не email — на мобильном не появится нужная клавиатура.",
                    url=url,
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    details={"type": control.get("type")},
                ),
            )
        if control["type"] == "email" and not control.get("autocomplete"):
            findings.append(
                Finding(
                    rule="forms/email-without-autocomplete",
                    severity=Severity.MODERATE,
                    title="Email-поле без autocomplete",
                    message="У email-поля нет autocomplete=\"email\" — клиенту приходится вводить адрес вручную.",
                    url=url,
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    details={"type": control.get("type")},
                ),
            )
        if ("tel" in name_or_id or "phone" in name_or_id or control["type"] == "tel") and not control.get("inputmode"):
            findings.append(
                Finding(
                    rule="forms/tel-missing-inputmode",
                    severity=Severity.MODERATE,
                    title="Поле телефона без inputmode=\"tel\"",
                    message="У поля телефона нет inputmode=\"tel\" — на мобильном неудобно вводить номер.",
                    url=url,
                    selector=control.get("selector"),
                    snippet=control.get("snippet"),
                    details={"type": control.get("type")},
                ),
            )

    all_buttons = [b for form in data.get("forms") or [] for b in form.get("buttons") or []]

    for button in all_buttons:
        if not button.get("submitLike"):
            continue
        text = (button.get("text") or "").strip()
        # input[type=submit] без value — браузер сам показывает «Submit», дефекта нет.
        if button.get("tag") == "input" and not text:
            continue
        if text:
            continue
        findings.append(
            Finding(
                rule="forms/submit-without-accessible-name",
                severity=Severity.SERIOUS,
                title="Кнопка отправки без доступного имени",
                message="У кнопки отправки нет текста, aria-label или другого имени — клиент не понимает, что нажать.",
                url=url,
                selector=button.get("selector"),
                snippet=button.get("snippet"),
                source="webscope.forms",
            ),
        )

    for orphan in data.get("orphans") or []:
        selector = orphan.get("selector") or ""
        if not selector or selector in checked_selectors:
            continue
        checked_selectors.add(selector)

        if not _ensure_fields_in_container(page, selector, min_fields=1):
            continue

        if _probe_submission(page, selector):
            continue

        details = {
            "reason": "dead_submit",
            "controls": orphan.get("controls"),
            "controls_without_name": orphan.get("controls_without_name"),
            "container": orphan.get("container"),
        }
        findings.append(
            Finding(
                rule="forms/dead-submit",
                severity=Severity.CRITICAL,
                title="Форма не отправляет заявки: кнопка «отправить сообщение» ни к чему не подключена",
                message=(
                    "Рядом поля ввода, но после нажатия кнопки заявка не ушла: "
                    "не было POST/PUT/PATCH/DELETE запросов и навигации на другую страницу. "
                    "Клиент заполняет поля, нажимает кнопку — и ничего не происходит."
                ),
                url=url,
                selector=orphan.get("selector"),
                snippet=orphan.get("snippet"),
                source="webscope.forms",
                details=details,
            ),
        )

    return findings