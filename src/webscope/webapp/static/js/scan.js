// ============================================================
// Scan Page — Form Submit Button State
// Extracted from scan.html for CSP compliance
// ============================================================

(function () {
  const form = document.getElementById('scan-form');
  const submitBtn = document.getElementById('scan-submit');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Проверяем…';
    submitBtn.classList.add('btn-secondary');
    submitBtn.classList.remove('btn-primary');
  });
})();