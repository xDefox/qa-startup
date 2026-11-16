// ============================================================
// Oneshot Page — Form Handling & Auth Toggle
// Extracted from oneshot.html for CSP compliance
// ============================================================

(function () {
  const form = document.getElementById('oneshot-form');
  const authToggle = document.getElementById('auth_enabled');
  const authBlock = document.getElementById('auth-block');
  const authKind = document.getElementById('auth_kind');
  const loginUrlField = document.getElementById('auth-login-url-field');

  function syncAuth() {
    authBlock.hidden = !authToggle.checked;
    loginUrlField.hidden = !(authToggle.checked && authKind.value === 'form');
  }
  authToggle.addEventListener('change', syncAuth);
  authKind.addEventListener('change', syncAuth);
  syncAuth();

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitBtn = form.querySelector('button[type="submit"]');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Проверяем...';

    const formData = new FormData(form);
    const data = {
      url: formData.get('url'),
      organization_id: parseInt(formData.get('organization_id')),
      max_pages: parseInt(formData.get('max_pages')),
      checks: Array.from(form.querySelectorAll('input[name="checks"]:checked')).map(c => c.value),
      auth_enabled: formData.get('auth_enabled') === '1',
      auth_kind: formData.get('auth_kind'),
      auth_login: formData.get('auth_login'),
      auth_password: formData.get('auth_password'),
      auth_login_url: formData.get('auth_login_url'),
    };

    try {
      const resp = await fetch('/api/scan/oneshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await resp.json();

      if (!resp.ok) {
        throw new Error(result.detail || 'Ошибка запуска проверки');
      }

      const resultCard = document.createElement('div');
      resultCard.className = 'result-card';
      resultCard.innerHTML = `
        <h2>Проверка запущена</h2>
        <p>Сайт ID: ${result.site_id}</p>
        <p>Прогон ID: ${result.run_id}</p>
        <p>В пакете осталось: ${result.package_scans_left} сканов</p>
        <a href="/sites/${result.site_id}" class="btn btn-primary">Открыть отчёт</a>
      `;
      let resultEl = document.getElementById('result');
      if (!resultEl) {
        resultEl = document.createElement('div');
        resultEl.id = 'result';
        document.querySelector('.card.hero').appendChild(resultEl);
      }
      resultEl.innerHTML = '';
      resultEl.appendChild(resultCard);
      resultEl.hidden = false;
    } catch (err) {
      alert('Ошибка: ' + err.message);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Проверить (1 скан из пакета)';
    }
  });
})();