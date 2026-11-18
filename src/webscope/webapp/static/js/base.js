// ============================================================
// webscope — общий слой: тема, мобильное меню, уведомления
// ============================================================
(function () {
  const root = document.documentElement;
  const button = document.getElementById('theme-toggle');
  const icon = button ? button.querySelector('.theme-icon') : null;
  const key = 'webscope-theme';
  const sun = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"></path></svg>';
  const moon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>';

  function systemPrefersDark() {
    return Boolean(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
  }

  function applyTheme(dark) {
    root.classList.add('theme-transition');
    root.setAttribute('data-theme', dark ? 'dark' : 'light');
    if (icon) icon.innerHTML = dark ? moon : sun;
    if (button) button.setAttribute('aria-label', dark ? 'Тёмная тема' : 'Светлая тема');
    window.setTimeout(function () { root.classList.remove('theme-transition'); }, 260);
  }

  const stored = localStorage.getItem(key);
  let dark = stored === 'dark' || (stored !== 'light' && systemPrefersDark());
  applyTheme(dark);
  if (button) {
    button.addEventListener('click', function () {
      dark = !dark;
      localStorage.setItem(key, dark ? 'dark' : 'light');
      applyTheme(dark);
    });
  }
})();

(function () {
  const toggle = document.getElementById('mobile-menu-toggle');
  const nav = document.getElementById('mobile-nav');
  if (!toggle || !nav) return;

  function close() {
    nav.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }

  toggle.addEventListener('click', function (event) {
    event.stopPropagation();
    const open = nav.hidden;
    nav.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    document.body.style.overflow = open ? 'hidden' : '';
  });
  nav.querySelectorAll('a').forEach(function (link) { link.addEventListener('click', close); });
  nav.addEventListener('click', function (event) { if (event.target === nav) close(); });
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') close(); });
})();

// Единая точка уведомлений для всех страниц.
window.showToast = function (message, type) {
  type = type === 'error' || type === 'success' ? type : 'warning';
  const container = document.getElementById('toast-container');
  if (!container) return;

  const icons = {
    warning: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>',
    error: '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>',
    success: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>'
  };

  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

  const iconWrap = document.createElement('span');
  iconWrap.className = 'toast-icon';
  iconWrap.setAttribute('aria-hidden', 'true');
  iconWrap.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + icons[type] + '</svg>';

  const text = document.createElement('span');
  text.className = 'toast-message';
  text.textContent = String(message);

  const close = document.createElement('button');
  close.className = 'toast-close';
  close.type = 'button';
  close.setAttribute('aria-label', 'Закрыть');
  close.textContent = '×';

  toast.append(iconWrap, text, close);
  container.appendChild(toast);

  function remove() {
    toast.classList.add('toast--out');
    window.setTimeout(function () { toast.remove(); }, 200);
  }

  close.addEventListener('click', remove);
  window.setTimeout(remove, 5000);
};
