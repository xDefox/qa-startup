// ============================================================
// Settings Page — Auth & Watchdog Toggles
// Extracted from settings.html for CSP compliance
// ============================================================

(function () {
  const toggle = document.getElementById('auth-enabled');
  const block = document.getElementById('auth-block');
  const kind = document.getElementById('auth_kind');
  const loginUrlField = document.getElementById('auth-login-url-field');
  function syncAuth() {
    block.hidden = !toggle.checked;
    loginUrlField.hidden = !(toggle.checked && kind.value === 'form');
  }
  toggle.addEventListener('change', syncAuth);
  kind.addEventListener('change', syncAuth);
  syncAuth();
})();

(function () {
  const toggle = document.getElementById('watchdog-enabled');
  const secretField = document.getElementById('webhook-secret-field');
  const statusField = document.getElementById('watchdog-status');
  function syncWatchdog() {
    const enabled = toggle.checked;
    secretField.hidden = !enabled;
    statusField.hidden = !enabled;
  }
  toggle.addEventListener('change', syncWatchdog);
  syncWatchdog();
})();

// Watchdog tooltip
(function () {
  const trigger = document.querySelector('.tooltip-trigger');
  const tooltip = document.querySelector('.tooltip');
  if (!trigger || !tooltip) return;

  let isOpen = false;

  function open() {
    isOpen = true;
    tooltip.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    // Position tooltip below trigger
    positionTooltip();
  }

  function close() {
    isOpen = false;
    tooltip.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
  }

  function positionTooltip() {
    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // Default: below trigger
    let top = triggerRect.bottom + window.scrollY + 8;
    let left = triggerRect.left + window.scrollX + (triggerRect.width / 2) - (tooltipRect.width / 2);

    // Keep within viewport horizontally
    const margin = 12;
    if (left < margin) left = margin;
    if (left + tooltipRect.width > viewportWidth - margin) {
      left = viewportWidth - tooltipRect.width - margin;
    }

    // Keep within viewport vertically (prefer below, but if no space, show above)
    if (top + tooltipRect.height > viewportHeight + window.scrollY - margin) {
      top = triggerRect.top + window.scrollY - tooltipRect.height - 8;
    }
    if (top < margin) top = margin;

    tooltip.style.top = top + 'px';
    tooltip.style.left = left + 'px';
  }

  trigger.addEventListener('click', function (event) {
    event.stopPropagation();
    if (isOpen) close();
    else open();
  });

  tooltip.addEventListener('click', function (event) {
    event.stopPropagation();
  });

  document.addEventListener('click', function () {
    if (isOpen) close();
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && isOpen) close();
  });

  window.addEventListener('resize', function () {
    if (isOpen) positionTooltip();
  });
})();

// Delete site form confirmation
(function () {
  const form = document.getElementById('delete-site-form');
  if (!form) return;
  form.addEventListener('submit', function (event) {
    const siteUrl = form.action.split('/').slice(-2, -1)[0];
    if (!confirm('Удалить ' + siteUrl + ' вместе с историей проверок?')) {
      event.preventDefault();
    }
  });
})();