// ============================================================
// Страница отчёта: прогресс проверки, выбор прогона,
// переключатель вида находок, панель скачивания и FP.
// ============================================================

function siteIdFromLocation() {
  const match = window.location.pathname.match(/^\/sites\/(\d+)/);
  return match ? match[1] : null;
}

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
  const anchor = document.querySelector('main .report-hero') || document.querySelector('main .card');
  if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(box, anchor);
  else document.querySelector('main').prepend(box);
}

async function checkScanCompletion(siteId) {
  try {
    const response = await fetch('/api/sites/' + siteId + '/runs');
    const data = await response.json();
    const running = (data.runs || []).some(function (run) { return run.status === 'running'; });
    if (!running) {
      window.location.reload();
      return;
    }
  } catch (error) {
    // сеть моргнула — пробуем ещё раз
  }
  window.setTimeout(function () { checkScanCompletion(siteId); }, 3000);
}

(function () {
  const form = document.querySelector('form.scan-form');
  if (!form) return;
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    showScanProgress();
    try {
      await fetch(form.action, { method: 'POST', credentials: 'same-origin' });
      const siteId = siteIdFromLocation();
      if (siteId) window.setTimeout(function () { checkScanCompletion(siteId); }, 1000);
    } catch (error) {
      form.submit();
    }
  });
})();

(function () {
  const pending = document.getElementById('scan-progress');
  const siteId = siteIdFromLocation();
  if (pending && siteId) window.setTimeout(function () { checkScanCompletion(siteId); }, 3000);
})();

(function () {
  const select = document.getElementById('run-select');
  if (!select) return;
  select.addEventListener('change', function () {
    const siteId = siteIdFromLocation();
    if (siteId && this.value) window.location.href = '/sites/' + siteId + '/runs/' + this.value;
  });
})();

// --- переключатель вида находок ---
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

// --- панель скачивания ---
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
    if (top + box.height > window.innerHeight - margin) top = Math.max(margin, anchor.top - box.height - gap);
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

  opener.addEventListener('click', function (event) {
    event.stopPropagation();
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

  links.forEach(function (link) {
    link.addEventListener('click', function () { close(false); });
  });
})();

// --- ложные находки ---
(function () {
  document.querySelectorAll('.btn-fp').forEach(function (button) {
    button.addEventListener('click', async function () {
      const findingId = this.dataset.findingId;
      const current = this.dataset.fp === 'true';
      const next = !current;

      this.dataset.fp = String(next);
      this.textContent = next ? '✓ Ложная находка' : 'Это ложная находка';
      this.disabled = true;

      try {
        const response = await fetch('/api/findings/' + findingId + '/fp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fp: next }),
          credentials: 'same-origin'
        });
        if (!response.ok) throw new Error('Сервер не принял отметку');
        if (window.showToast) window.showToast(next ? 'Находка отмечена как ложная' : 'Находка восстановлена', 'success');
      } catch (error) {
        this.dataset.fp = String(current);
        this.textContent = current ? '✓ Ложная находка' : 'Это ложная находка';
        if (window.showToast) window.showToast('Ошибка: ' + error.message, 'error');
      } finally {
        this.disabled = false;
      }
    });
  });
})();
