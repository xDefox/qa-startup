// ============================================================
// Dashboard API Keys — Key Management
// Extracted from dashboard_api_keys.html for CSP compliance
// ============================================================

async function loadApiKeys() {
  const res = await fetch('/api/api-keys');
  if (!res.ok) return;
  const data = await res.json();
  const container = document.getElementById('api-keys-list');
  if (!data.keys || data.keys.length === 0) {
    container.innerHTML = '<p class="muted">Ключей нет. Нажмите «Создать ключ».</p>';
    return;
  }
  container.innerHTML = data.keys.map(k => `
    <div class="api-key-row">
      <code>${k.prefix}****${k.suffix}</code>
      <span class="muted">Создан: ${k.created_at}</span>
      <button class="btn-sm danger revoke-api-key-btn" data-key-id="${k.id}">Отозвать</button>
    </div>
  `).join('');
}

async function createApiKey() {
  const res = await fetch('/api/api-keys', { method: 'POST' });
  if (!res.ok) return alert('Ошибка создания');
  const data = await res.json();
  alert('Ключ создан (покажите только один раз):\n' + data.key);
  loadApiKeys();
}

async function revokeApiKey(id) {
  if (!confirm('Отозвать этот ключ?')) return;
  const res = await fetch('/api/api-keys/' + id, { method: 'DELETE' });
  if (!res.ok) return alert('Ошибка');
  loadApiKeys();
}

// Event delegation for API key buttons
document.addEventListener('click', async function (event) {
  const createBtn = event.target.closest('#create-api-key-btn');
  if (createBtn) {
    createApiKey();
    return;
  }

  const revokeBtn = event.target.closest('.revoke-api-key-btn');
  if (revokeBtn) {
    const id = revokeBtn.dataset.keyId;
    revokeApiKey(id);
    return;
  }
});

loadApiKeys();