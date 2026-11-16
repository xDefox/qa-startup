// ============================================================
// WebScope — Base JavaScript
// Extracted from base.html for CSP compliance
// ============================================================

// ============================================================
// Theme Toggle
// ============================================================
(function(){
  const root = document.documentElement;
  const btn = document.getElementById('theme-toggle');
  const icon = btn?.querySelector('.theme-icon');
  const key = 'webscope-theme';
  const sun = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="M4.93 4.93l1.41 1.41"></path><path d="M17.66 17.66l1.41 1.41"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="M6.34 17.66l-1.41 1.41"></path><path d="M19.07 4.93l-1.41 1.41"></path></svg>';
  const moon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>';
  function currentIsDark(){
    if(root.getAttribute('data-theme') === 'dark') return true;
    if(root.getAttribute('data-theme') === 'light') return false;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }
  function applyTheme(isDark){
    root.classList.add('theme-transition');
    if(isDark) root.setAttribute('data-theme','dark');
    else root.setAttribute('data-theme','light');
    if(icon){
      icon.innerHTML = isDark ? moon : sun;
      icon.style.transform = isDark ? 'rotate(-20deg)' : 'rotate(0deg)';
    }
    btn?.setAttribute('aria-label', isDark ? 'Тёмная тема' : 'Светлая тема');
    setTimeout(function(){ root.classList.remove('theme-transition'); }, 260);
  }
  let isDark = localStorage.getItem(key) === 'dark' || (localStorage.getItem(key) !== 'light' && currentIsDark());
  applyTheme(isDark);
  btn?.addEventListener('click', function(){
    isDark = !isDark;
    localStorage.setItem(key, isDark ? 'dark' : 'light');
    applyTheme(isDark);
  });
})();

// ============================================================
// Mobile Menu Toggle
// ============================================================
(function(){
  const toggle = document.getElementById('mobile-menu-toggle');
  const nav = document.getElementById('mobile-nav');
  if (!toggle || !nav) return;

  function openNav() {
    nav.hidden = false;
    toggle.setAttribute('aria-expanded', 'true');
    document.body.style.overflow = 'hidden';
  }
  function closeNav() {
    nav.hidden = true;
    toggle.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
  }
  toggle.addEventListener('click', function(e) {
    e.stopPropagation();
    if (nav.hidden) {
      openNav();
    } else {
      closeNav();
    }
  });
  // Close on link click
  nav.querySelectorAll('.mobile-nav-link').forEach(function(link) {
    link.addEventListener('click', closeNav);
  });
  // Close on backdrop click
  nav.addEventListener('click', function(e) {
    if (e.target === nav) closeNav();
  });
  // Close on Escape
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && !nav.hidden) closeNav();
  });
})();

// ============================================================
// Toast Notification System
// ============================================================
window.showToast = function(message, type) {
  type = type || 'warning'; // 'warning', 'error', 'success'
  const container = document.getElementById('toast-container');
  if (!container) return;
  
  const icons = {
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
  };
  
  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  toast.innerHTML = '<span class="toast-icon" aria-hidden="true">' + icons[type] + '</span><span class="toast-message">' + message + '</span><button class="toast-close" aria-label="Закрыть"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>';
  
  container.appendChild(toast);
  
  toast.querySelector('.toast-close').addEventListener('click', function() {
    removeToast(toast);
  });
  
  // Auto-remove after 5 seconds
  setTimeout(function() { removeToast(toast); }, 5000);
  
  function removeToast(el) {
    el.style.animation = 'toast-out 200ms ease-in forwards';
    setTimeout(function() { el.remove(); }, 200);
  }
};

// ============================================================
// Scan Progress Indicator (reusable)
// ============================================================
function showScanProgress(siteId) {
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

  // Poll for completion
  const check = async () => {
    try {
      const response = await fetch('/api/sites/' + siteId + '/runs');
      const data = await response.json();
      const running = (data.runs || []).some((run) => run.status === 'running');
      if (!running) { window.location.reload(); return; }
    } catch (error) { /* молча пробуем ещё раз */ }
    setTimeout(check, 3000);
  };
  setTimeout(check, 3000);
}