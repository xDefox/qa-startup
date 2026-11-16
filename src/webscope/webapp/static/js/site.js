// ============================================================
// Site Page — Scan Progress, Download Panel, FP Toggle, View Toggle
// Extracted from site.html for CSP compliance
// ============================================================

// Show scan progress indicator
function showScanProgress() {
  if (document.getElementById('scan-progress')) return;
  const box = document.createElement('div');
  box.className = 'scan-progress';
  box.id = 'scan-progress';
  box.setAttribute('role', 'status');
  box.setAttribute('aria-live', 'polite');
  const spinner = document.createElement('span');
  spinner.className = 'scan-spinner';
  spinner.setAttribute('aria-hidden', 'true');
  const text = document.createElement('span');
  text.className = 'scan-progress-text';
  text.textContent = 'Идёт проверка сайта… это занимает до минуты. Страница обновится сама.';
  box.append(spinner, text);
  const card = document.querySelector('main .card');
  if (card) card.parentNode.insertBefore(box, card);
  else document.querySelector('main').prepend(box);
}

// Poll for scan completion
async function checkScanCompletion(siteId) {
  try {
    const response = await fetch('/api/sites/' + siteId + '/runs');
    const data = await response.json();
    const running = (data.runs || []).some((run) => run.status === 'running');
    if (!running) {
      window.location.reload();
      return;
    }
  } catch (error) {
    // молча пробуем ещё раз
  }
  setTimeout(() => checkScanCompletion(siteId), 3000);
}

// Initialize scan form handler
(function () {
  const form = document.querySelector('form.scan-form');
  if (!form) return;

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    showScanProgress();
    try {
      await fetch(form.action, { method: 'POST', credentials: 'same-origin' });
      setTimeout(() => checkScanCompletion(new URL(form.action).pathname.split('/')[3]), 1000);
    } catch (error) {
      form.submit();
    }
  });
})();

// Download panel handler
(function () {
  const opener = document.getElementById('download-open');
  const pop = document.getElementById('download-pop');
  if (!opener || !pop) return;

  let isOpen = false;

  function place() {
    const anchor = opener.getBoundingClientRect();
    const box = pop.getBoundingClientRect();
    const gap = 8;
    const margin = 12;
    let left = anchor.right - box.width;
    left = Math.max(margin, Math.min(left, window.innerWidth - box.width - margin));
    let top = anchor.bottom + gap;
    if (top + box.height > window.innerHeight - margin) {
      top = Math.max(margin, anchor.top - box.height - gap);
    }
    pop.style.left = Math.round(left) + 'px';
    pop.style.top = Math.round(top) + 'px';
  }

  const nameInput = pop.querySelector('#download-name');
  const nameExt = pop.querySelector('#download-name-ext');
  const links = pop.querySelectorAll('a[download]');

  function cleanName(value) {
    return (value || '')
      .replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, '-')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/^[.\-_ ]+|[.\-_ ]+$/g, '')
      .slice(0, 120);
  }

  function applyName() {
    const name = cleanName(nameInput ? nameInput.value : '');
    links.forEach(function (link) {
      const base = link.dataset.baseHref;
      const ext = link.dataset.ext || '';
      link.setAttribute('href', name ? base + '&filename=' + encodeURIComponent(name) : base);
      link.setAttribute('download', (name || 'webscope') + '.' + ext);
    });
    if (nameExt && links.length) nameExt.textContent = '.' + (links[0].dataset.ext || '');
  }

  if (nameInput) nameInput.addEventListener('input', applyName);
  applyName();

  function open() {
    isOpen = true;
    pop.hidden = false;
    opener.setAttribute('aria-expanded', 'true');
    place();
    const first = nameInput || pop.querySelector('a');
    if (first) first.focus();
  }

  function close(focusBack) {
    if (!isOpen) return;
    isOpen = false;
    pop.hidden = true;
    opener.setAttribute('aria-expanded', 'false');
    if (focusBack) opener.focus();
  }

  opener.addEventListener('click', function () {
    if (isOpen) close(true);
    else open();
  });

  document.addEventListener('click', function (event) {
    if (isOpen && !pop.contains(event.target) && !opener.contains(event.target)) close(false);
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && isOpen) close(true);
  });
  window.addEventListener('resize', function () { if (isOpen) place(); });
  window.addEventListener('scroll', function () { if (isOpen) place(); }, true);

  pop.querySelectorAll('a[download]').forEach(function (link) {
    link.addEventListener('click', function () { close(false); });
  });
})();

// FP (false positive) toggle button handler
(function () {
  document.querySelectorAll('.btn-fp').forEach(function (btn) {
    btn.addEventListener('click', async function () {
      const findingId = this.dataset.findingId;
      const currentFp = this.dataset.fp === 'true';
      const newFp = !currentFp;

      this.dataset.fp = newFp.toString();
      this.textContent = newFp ? '✓ Ложная находка' : '🚫 Это ложная находка';
      this.disabled = true;

      try {
        const response = await fetch('/api/findings/' + findingId + '/fp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fp: newFp }),
          credentials: 'same-origin'
        });
        if (!response.ok) throw new Error('Server error');
        if (window.showToast) {
          window.showToast(newFp ? 'Находка отмечена как ложная' : 'Находка восстановлена', 'success');
        }
      } catch (error) {
        this.dataset.fp = currentFp.toString();
        this.textContent = currentFp ? '✓ Ложная находка' : '🚫 Это ложная находка';
        if (window.showToast) {
          window.showToast('Ошибка: ' + error.message, 'error');
        }
      } finally {
        this.disabled = false;
      }
    });
  });
})();

// View toggle (list/table)
function setFindingsView(mode) {
  if (mode !== 'list' && mode !== 'table') return;
  document.querySelectorAll('.findings-view').forEach(function (panel) {
    panel.hidden = panel.dataset.mode !== mode;
  });
  document.querySelectorAll('.view-toggle .view-btn').forEach(function (btn) {
    btn.setAttribute('aria-pressed', btn.dataset.view === mode ? 'true' : 'false');
  });
  localStorage.setItem('webscope_view', mode);
}

document.querySelectorAll('.view-toggle .view-btn').forEach(function (btn) {
  btn.addEventListener('click', function () { setFindingsView(btn.dataset.view); });
});

(function () {
  const saved = localStorage.getItem('webscope_view') || 'list';
  setFindingsView(saved === 'table' ? 'table' : 'list');
})();

// Auto-check for pending scan on page load
(function () {
  const pending = document.getElementById('scan-progress');
  if (pending) {
    const siteId = new URL(window.location.href).pathname.split('/')[3];
    if (siteId) setTimeout(() => checkScanCompletion(siteId), 3000);
  }
})();

// Run selector handler
(function () {
  const select = document.getElementById('run-select');
  if (!select) return;
  select.addEventListener('change', function () {
    const siteId = new URL(window.location.href).pathname.split('/')[3];
    if (siteId && this.value) {
      window.location.href = '/sites/' + siteId + '/runs/' + this.value;
    }
  });
})();