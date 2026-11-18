// ============================================================
// Настройки сайта: вход, Watchdog, подсказка и удаление.
// ============================================================

(function () {
  const toggle = document.getElementById('auth-enabled');
  const block = document.getElementById('auth-block');
  const kind = document.getElementById('auth_kind');
  const loginUrlField = document.getElementById('auth-login-url-field');
  if (!toggle || !block || !kind) return;

  function sync() {
    block.hidden = !toggle.checked;
    if (loginUrlField) loginUrlField.hidden = !(toggle.checked && kind.value === 'form');
  }
  toggle.addEventListener('change', sync);
  kind.addEventListener('change', sync);
  sync();
})();

(function () {
  const toggle = document.getElementById('watchdog-enabled');
  const secretField = document.getElementById('webhook-secret-field');
  const statusField = document.getElementById('watchdog-status');
  if (!toggle) return;

  function sync() {
    const enabled = toggle.checked;
    if (secretField) secretField.hidden = !enabled;
    if (statusField) statusField.hidden = !enabled;
  }
  toggle.addEventListener('change', sync);
  sync();
})();

(function () {
  const trigger = document.querySelector('.tooltip-trigger');
  const tooltip = document.querySelector('.tooltip');
  if (!trigger || !tooltip) return;

  let isOpen = false;

  function open() {
    isOpen = true;
    tooltip.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    place();
  }

  function close() {
    isOpen = false;
    tooltip.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  }

  function place() {
    const anchor = trigger.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    const margin = 12;
    let left = anchor.left + anchor.width / 2 - box.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - box.width - margin));
    let top = anchor.bottom + 8;
    if (top + box.height > window.innerHeight - margin) top = anchor.top - box.height - 8;
    top = Math.max(margin, top);
    tooltip.style.left = Math.round(left) + 'px';
    tooltip.style.top = Math.round(top) + 'px';
  }

  trigger.addEventListener('click', function (event) {
    event.stopPropagation();
    if (isOpen) close();
    else open();
  });

  tooltip.addEventListener('click', function (event) { event.stopPropagation(); });
  document.addEventListener('click', function () { if (isOpen) close(); });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && isOpen) {
      close();
      trigger.focus();
    }
  });
  window.addEventListener('resize', function () { if (isOpen) place(); });
  window.addEventListener('scroll', function () { if (isOpen) place(); }, true);
})();

(function () {
  const form = document.getElementById('delete-site-form');
  if (!form) return;
  form.addEventListener('submit', function (event) {
    const url = form.dataset.siteUrl || 'этот сайт';
    if (!window.confirm('Удалить ' + url + ' вместе с историей проверок?')) {
      event.preventDefault();
    }
  });
})();
