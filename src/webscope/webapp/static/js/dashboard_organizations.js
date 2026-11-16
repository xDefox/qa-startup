// ============================================================
// Dashboard Organizations — Organization Management
// Extracted from dashboard_organizations.html for CSP compliance
// ============================================================

async function loadOrgs() {
  const res = await fetch('/api/organizations');
  if (!res.ok) return;
  const data = await res.json();
  const container = document.getElementById('orgs-list');
  if (!data.organizations || data.organizations.length === 0) {
    container.innerHTML = '<p class="muted">Организаций нет.</p>';
    return;
  }
  container.innerHTML = data.organizations.map(o => `
    <tr>
      <td>${o.name}</td>
      <td>${o.owner_email || '—'}</td>
      <td>${o.created_at ? o.created_at.slice(0, 10) : '—'}</td>
      <td>
        <button class="btn-sm edit-org-btn" data-org-id="${o.id}" data-org-name="${o.name}" data-org-email="${o.owner_email || ''}">Редактировать</button>
        <button class="btn-sm danger delete-org-btn" data-org-id="${o.id}" data-org-name="${o.name}">Удалить</button>
      </td>
    </tr>
  `).join('');
}

function createOrg() {
  const name = prompt('Название организации:');
  if (!name) return;
  const email = prompt('Email владельца (необязательно):') || '';
  fetch('/api/organizations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, owner_email: email })
  }).then(r => r.json()).then(() => loadOrgs());
}

function editOrg(id, name, email) {
  const newName = prompt('Новое название:', name);
  if (!newName) return;
  const newEmail = prompt('Новый email:', email) || '';
  fetch('/api/organizations/' + id, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: newName, owner_email: newEmail })
  }).then(r => r.json()).then(() => loadOrgs());
}

function deleteOrg(id, name) {
  if (!confirm('Удалить организацию "' + name + '"?')) return;
  fetch('/api/organizations/' + id, { method: 'DELETE' })
    .then(r => r.json()).then(() => loadOrgs());
}

// Event delegation for org buttons
document.addEventListener('click', async function (event) {
  const createBtn = event.target.closest('#create-org-btn');
  if (createBtn) {
    createOrg();
    return;
  }

  const editBtn = event.target.closest('.edit-org-btn');
  if (editBtn) {
    const id = parseInt(editBtn.dataset.orgId, 10);
    const name = editBtn.dataset.orgName;
    const email = editBtn.dataset.orgEmail;
    editOrg(id, name, email);
    return;
  }

  const deleteBtn = event.target.closest('.delete-org-btn');
  if (deleteBtn) {
    const id = parseInt(deleteBtn.dataset.orgId, 10);
    const name = deleteBtn.dataset.orgName;
    deleteOrg(id, name);
    return;
  }
});

loadOrgs();