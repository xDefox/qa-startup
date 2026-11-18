// ============================================================
// Организации: таблица, диалог создания и редактирования, удаление.
// ============================================================

(function () {
  const list = document.getElementById('orgs-list');
  const createBtn = document.getElementById('create-org-btn');
  const dialog = document.getElementById('org-dialog');
  const form = document.getElementById('org-form');
  const dialogTitle = document.getElementById('org-dialog-title');
  const idInput = document.getElementById('org-id');
  const nameInput = document.getElementById('org-name');
  const emailInput = document.getElementById('org-email');
  const cancelBtn = document.getElementById('org-cancel');

  function notify(message, type) {
    if (window.showToast) window.showToast(message, type);
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function request(url, options) {
    const response = await fetch(url, Object.assign({ credentials: 'same-origin' }, options));
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      payload = {};
    }
    if (!response.ok) {
      throw new Error(payload.detail || 'Сервер вернул ' + response.status);
    }
    return payload;
  }

  function renderRows(organizations) {
    if (!list) return;
    if (!organizations.length) {
      list.innerHTML = '<tr><td colspan="4" class="muted">Организаций пока нет.</td></tr>';
      return;
    }
    list.innerHTML = organizations.map(function (org) {
      const name = escapeHtml(org.name);
      const email = escapeHtml(org.owner_email || '—');
      const created = escapeHtml(org.created_at ? org.created_at.slice(0, 10) : '—');
      return '<tr>' +
        '<td>' + name + '</td>' +
        '<td>' + email + '</td>' +
        '<td>' + created + '</td>' +
        '<td><div class="actions">' +
        '<button type="button" class="btn btn-sm btn-secondary edit-org-btn" data-org-id="' + org.id +
        '" data-org-name="' + name + '" data-org-email="' + escapeHtml(org.owner_email || '') + '">Изменить</button>' +
        '<button type="button" class="btn btn-sm btn-danger delete-org-btn" data-org-id="' + org.id +
        '" data-org-name="' + name + '">Удалить</button>' +
        '</div></td></tr>';
    }).join('');
  }

  async function loadOrgs() {
    if (!list) return;
    try {
      const data = await request('/api/organizations');
      renderRows(data.organizations || []);
    } catch (error) {
      notify('Не удалось загрузить организации: ' + error.message, 'error');
    }
  }

  function openDialog(mode, org) {
    if (!dialog) return;
    if (dialogTitle) dialogTitle.textContent = mode === 'edit' ? 'Изменить организацию' : 'Новая организация';
    if (idInput) idInput.value = org ? org.id : '';
    if (nameInput) nameInput.value = org ? org.name : '';
    if (emailInput) emailInput.value = org ? org.owner_email || '' : '';
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    if (nameInput) nameInput.focus();
  }

  function closeDialog() {
    if (!dialog) return;
    if (typeof dialog.close === 'function') dialog.close();
    else dialog.removeAttribute('open');
  }

  if (createBtn) {
    createBtn.addEventListener('click', function () { openDialog('create'); });
  }
  if (cancelBtn) cancelBtn.addEventListener('click', closeDialog);
  if (dialog) {
    dialog.addEventListener('click', function (event) {
      if (event.target === dialog) closeDialog();
    });
  }

  if (form) {
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      const id = idInput ? idInput.value : '';
      const name = nameInput ? nameInput.value.trim() : '';
      const email = emailInput ? emailInput.value.trim() : '';
      if (!name) {
        notify('Укажите название организации', 'warning');
        if (nameInput) nameInput.focus();
        return;
      }
      const submit = form.querySelector('button[type="submit"]');
      if (submit) submit.disabled = true;
      try {
        await request(id ? '/api/organizations/' + id : '/api/organizations', {
          method: id ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name, owner_email: email }),
        });
        closeDialog();
        notify(id ? 'Организация обновлена' : 'Организация создана', 'success');
        await loadOrgs();
      } catch (error) {
        notify('Не удалось сохранить: ' + error.message, 'error');
      } finally {
        if (submit) submit.disabled = false;
      }
    });
  }

  if (list) {
    list.addEventListener('click', async function (event) {
      const editBtn = event.target.closest('.edit-org-btn');
      if (editBtn) {
        openDialog('edit', {
          id: editBtn.dataset.orgId,
          name: editBtn.dataset.orgName,
          owner_email: editBtn.dataset.orgEmail,
        });
        return;
      }
      const deleteBtn = event.target.closest('.delete-org-btn');
      if (!deleteBtn) return;
      const name = deleteBtn.dataset.orgName || 'организацию';
      if (!window.confirm('Удалить «' + name + '»? Сайты и пакеты останутся, но потеряют привязку.')) return;
      deleteBtn.disabled = true;
      try {
        await request('/api/organizations/' + deleteBtn.dataset.orgId, { method: 'DELETE' });
        notify('Организация удалена', 'success');
        await loadOrgs();
      } catch (error) {
        notify('Не удалось удалить: ' + error.message, 'error');
        deleteBtn.disabled = false;
      }
    });
  }

  // Данные уже отрисованы сервером — перезагружаем только если список пуст.
  if (list && !list.querySelector('tr')) loadOrgs();
})();
