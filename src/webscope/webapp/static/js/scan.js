// ============================================================
// Быстрая проверка: блокируем кнопку, пока идёт отправка формы.
// ============================================================

(function () {
  const form = document.getElementById('scan-form');
  const submitBtn = document.getElementById('scan-submit');
  if (!form || !submitBtn) return;

  form.addEventListener('submit', function () {
    const span = submitBtn.querySelector('span');
    if (span) span.textContent = 'Проверяем…';
    else submitBtn.textContent = 'Проверяем…';
    submitBtn.disabled = true;
    submitBtn.classList.add('btn-secondary');
    submitBtn.classList.remove('btn-primary');
  });
})();
