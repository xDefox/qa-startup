// ============================================================
// Разовая проверка: показ полей входа и запуск скана.
// ============================================================

(function () {
  const form = document.getElementById('oneshot-form');
  if (!form) return;

  const authToggle = document.getElementById('auth_enabled');
  const authBlock = document.getElementById('auth-block');
  const authKind = document.getElementById('auth_kind');
  const loginUrlField = document.getElementById('auth-login-url-field');
  const resultEl = document.getElementById('result');

  function syncAuth() {
    if (!authToggle || !authBlock) return;
    authBlock.hidden = !authToggle.checked;
    if (loginUrlField && authKind) {
      loginUrlField.hidden = !(authToggle.checked && authKind.value === 'form');
    }
  }
  if (authToggle) {
    authToggle.addEventListener('change', syncAuth);
    syncAuth();
  }
  if (authKind) authKind.addEventListener('change', syncAuth);

  function notify(message, type) {
    if (window.showToast) window.showToast(message, type);
  }

  function label(button, text) {
    const span = button ? button.querySelector('span') : null;
    if (span) span.textContent = text;
    else if (button) button.textContent = text;
  }

  function renderResult(payload) {
    if (!resultEl) return;
    resultEl.textContent = '';

    const card = document.createElement('div');
    card.className = 'card card--accent result-card';

    const title = document.createElement('h2');
    title.textContent = 'Проверка запущена';
    card.appendChild(title);

    const meta = document.createElement('p');
    meta.className = 'muted';
    meta.textContent = 'Сайт №' + payload.site_id + ' · прогон №' + payload.run_id +
      (typeof payload.package_scans_left === 'number'
        ? ' · в пакете осталось: ' + payload.package_scans_left + ' сканов'
        : '');
    card.appendChild(meta);

    const actions = document.createElement('div');
    actions.className = 'actions mt-2';
    const link = document.createElement('a');
    link.className = 'btn btn-primary';
    link.href = '/sites/' + payload.site_id;
    link.textContent = 'Открыть отчёт';
    actions.appendChild(link);
    const again = document.createElement('a');
    again.className = 'btn btn-secondary';
    again.href = '/sites/' + payload.site_id + '/settings';
    again.textContent = 'Настройки сайта';
    actions.appendChild(again);
    card.appendChild(actions);

    resultEl.appendChild(card);
    resultEl.hidden = false;
  }

  form.addEventListener('submit', async function (event) {
    event.preventDefault();

    const submitBtn = form.querySelector('button[type="submit"]');
    const original = submitBtn ? (submitBtn.querySelector('span') || submitBtn).textContent.trim() : '';
    if (submitBtn) submitBtn.disabled = true;
    label(submitBtn, 'Запускаем…');

    const data = new FormData(form);
    const organizationId = Number.parseInt(data.get('organization_id'), 10);
    if (!organizationId) {
      notify('Сначала создайте организацию в кабинете', 'warning');
      if (submitBtn) submitBtn.disabled = false;
      label(submitBtn, original);
      return;
    }

    const body = {
      url: String(data.get('url') || '').trim(),
      organization_id: organizationId,
      max_pages: Number.parseInt(data.get('max_pages'), 10) || 10,
      checks: Array.from(form.querySelectorAll('input[name="checks"]:checked')).map(function (item) {
        return item.value;
      }),
      auth_enabled: Boolean(authToggle && authToggle.checked),
      auth_kind: data.get('auth_kind') || 'basic',
      auth_login: data.get('auth_login') || '',
      auth_password: data.get('auth_password') || '',
      auth_login_url: data.get('auth_login_url') || '',
    };

    if (!body.url) {
      notify('Укажите адрес сайта', 'warning');
      if (submitBtn) submitBtn.disabled = false;
      label(submitBtn, original);
      return;
    }

    try {
      const response = await fetch('/api/scan/oneshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(body),
      });
      let payload = {};
      try {
        payload = await response.json();
      } catch (error) {
        payload = {};
      }
      if (!response.ok) {
        throw new Error(payload.detail || 'Не удалось запустить проверку');
      }
      renderResult(payload);
      notify('Проверка запущена', 'success');
    } catch (error) {
      notify('Ошибка: ' + error.message, 'error');
    } finally {
      if (submitBtn) submitBtn.disabled = false;
      label(submitBtn, original);
    }
  });
})();
