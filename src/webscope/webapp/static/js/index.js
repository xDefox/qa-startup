// ============================================================
// Index Page — Upload & Form Handling
// Extracted from index.html for CSP compliance
// ============================================================

(function () {
  const form = document.getElementById('site-form');
  const urlInput = document.getElementById('url');
  const fileInput = document.getElementById('local-file');
  const dirInput = document.getElementById('local-dir');
  const uploadZone = document.getElementById('upload-zone');
  const uploadContent = document.getElementById('upload-content');
  const uploadSelected = document.getElementById('upload-selected');
  const uploadCount = document.getElementById('upload-count');
  const uploadClear = document.getElementById('upload-clear');
  const uploadProgress = document.getElementById('upload-progress');
  const progressFill = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');

  let selectedFiles = [];

  function showToast(message, type) {
    type = type || 'warning';
    const container = document.getElementById('toast-container');
    if (!container) {
      console.warn('toast-container not found');
      return;
    }
    const icons = {
      warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
      error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>',
      success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
    };
    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.innerHTML = '<span class="toast-icon" aria-hidden="true">' + icons[type] + '</span><span class="toast-message">' + message + '</span><button class="toast-close" aria-label="Закрыть"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>';
    container.appendChild(toast);
    toast.querySelector('.toast-close').addEventListener('click', () => removeToast(toast));
    setTimeout(() => removeToast(toast), 5000);
    function removeToast(el) {
      el.style.animation = 'toast-out 200ms ease-in forwards';
      setTimeout(() => el.remove(), 200);
    }
  }
  window.showToast = showToast;

  function showSelected(files) {
    selectedFiles = Array.from(files);
    uploadContent.hidden = true;
    uploadSelected.hidden = false;

    const countText = selectedFiles.length + ' ' +
      (selectedFiles.length === 1 ? 'файл' :
       selectedFiles.length < 5 ? 'файла' : 'файлов');

    const fileList = selectedFiles.map((f, i) =>
      '<div class="upload-file-item" data-index="' + i + '">' +
        '<span class="upload-file-name" title="' + (f.webkitRelativePath || f.name).replace(/"/g, '"') + '">' +
          (i + 1) + '. ' + (f.webkitRelativePath || f.name) +
        '</span>' +
        '<button type="button" class="upload-file-remove" aria-label="Удалить файл" data-index="' + i + '">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>' +
        '</button>' +
      '</div>'
    ).join('');

    uploadCount.innerHTML = countText + '<div class="upload-file-list">' + fileList + '</div>';

    uploadCount.querySelectorAll('.upload-file-remove').forEach(btn => {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        const idx = parseInt(this.dataset.index, 10);
        removeFile(idx);
      });
    });
  }

  function removeFile(index) {
    selectedFiles.splice(index, 1);
    if (selectedFiles.length === 0) {
      clearSelection();
    } else {
      showSelected(selectedFiles);
    }
  }

  function clearSelection() {
    selectedFiles = [];
    fileInput.value = '';
    dirInput.value = '';
    uploadContent.hidden = false;
    uploadSelected.hidden = true;
  }

  async function upload(files) {
    if (!files || !files.length) return null;
    const fd = new FormData();
    for (let i = 0; i < files.length; i++) {
      fd.append('files', files[i]);
      fd.append('paths', files[i].webkitRelativePath || files[i].name);
    }
    uploadSelected.hidden = true;
    uploadProgress.hidden = false;
    progressFill.style.width = '0%';
    progressText.textContent = 'Загрузка…';
    try {
      const data = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload');
        xhr.upload.addEventListener('progress', e => {
          if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            progressFill.style.width = pct + '%';
            progressText.textContent = 'Загрузка: ' + pct + '%';
          }
        });
        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              const data = JSON.parse(xhr.responseText);
              if (data && data.url) {
                resolve(data.url);
              } else {
                reject(new Error('Нет URL в ответе'));
              }
            } catch (e) {
              reject(new Error('Ошибка парсинга ответа'));
            }
          } else {
            reject(new Error('Upload failed: ' + xhr.status));
          }
        });
        xhr.addEventListener('error', () => reject(new Error('Network error')));
        xhr.send(fd);
      });
      return data;
    } catch (e) {
      uploadProgress.hidden = true;
      uploadContent.hidden = false;
      if (window.showToast) {
        window.showToast('Ошибка загрузки: ' + e.message, 'error');
      } else {
        alert('Ошибка загрузки: ' + e.message);
      }
      return null;
    }
  }

  fileInput?.addEventListener('change', e => {
    if (e.target.files.length) showSelected(e.target.files);
  });
  dirInput?.addEventListener('change', e => {
    if (e.target.files.length) showSelected(e.target.files);
  });

  form?.addEventListener('submit', async (e) => {
    const hasUrl = urlInput.value.trim().length > 0;
    if (!hasUrl && selectedFiles.length === 0) {
      e.preventDefault();
      if (window.showToast) {
        window.showToast('Укажите адрес сайта или выберите папку/файл для загрузки', 'warning');
      } else {
        alert('Укажите адрес сайта или выберите папку/файл для загрузки');
      }
      return;
    }
    if (selectedFiles.length > 0) {
      e.preventDefault();
      try {
        const url = await upload(selectedFiles);
        if (url) {
          urlInput.value = url;
          fileInput.value = '';
          dirInput.value = '';
          form.submit();
        }
      } catch (err) {
        if (window.showToast) {
          window.showToast('Ошибка загрузки: ' + err.message, 'error');
        } else {
          alert('Ошибка загрузки: ' + err.message);
        }
      }
    }
  });

  uploadClear?.addEventListener('click', clearSelection);

  ['dragenter', 'dragover'].forEach(evt => {
    uploadZone.addEventListener(evt, e => {
      e.preventDefault();
      e.stopPropagation();
      uploadZone.classList.add('drag-over');
    });
  });
  ['dragleave', 'drop'].forEach(evt => {
    uploadZone.addEventListener(evt, e => {
      e.preventDefault();
      e.stopPropagation();
      uploadZone.classList.remove('drag-over');
    });
  });
  uploadZone.addEventListener('drop', e => {
    const files = e.dataTransfer.files;
    if (files.length) showSelected(files);
  });

  uploadZone.addEventListener('click', e => {
    if (e.target.closest('label, button')) return;
    if (e.target === uploadZone || e.target.closest('.upload-zone-content')) {
      fileInput.click();
    }
  });
})();

// Auth toggle for index.html
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