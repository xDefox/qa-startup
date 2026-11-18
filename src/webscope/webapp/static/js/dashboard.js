// ============================================================
// Кабинет: загрузка локальной сборки и форма мониторинга
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
  const uploadFileList = document.getElementById('upload-file-list');
  const uploadClear = document.getElementById('upload-clear');
  const uploadProgress = document.getElementById('upload-progress');
  const progressFill = document.getElementById('progress-fill');
  const progressText = document.getElementById('progress-text');

  let selectedFiles = [];

  function notify(message, type) {
    if (window.showToast) window.showToast(message, type);
  }

  function clearSelection() {
    selectedFiles = [];
    if (fileInput) fileInput.value = '';
    if (dirInput) dirInput.value = '';
    if (uploadContent) uploadContent.hidden = false;
    if (uploadSelected) uploadSelected.hidden = true;
    if (uploadFileList) uploadFileList.textContent = '';
  }

  function showSelected(files) {
    selectedFiles = Array.from(files || []);
    if (!selectedFiles.length) {
      clearSelection();
      return;
    }
    if (uploadContent) uploadContent.hidden = true;
    if (uploadSelected) uploadSelected.hidden = false;

    const label = selectedFiles.length === 1 ? 'файл' : selectedFiles.length < 5 ? 'файла' : 'файлов';
    if (uploadCount) uploadCount.textContent = selectedFiles.length + ' ' + label;
    if (!uploadFileList) return;

    uploadFileList.textContent = '';
    selectedFiles.forEach(function (file, index) {
      const row = document.createElement('div');
      row.className = 'upload-file-item';
      const name = document.createElement('span');
      name.className = 'upload-file-name';
      name.title = file.webkitRelativePath || file.name;
      name.textContent = (index + 1) + '. ' + (file.webkitRelativePath || file.name);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'upload-file-remove';
      remove.setAttribute('aria-label', 'Удалить файл');
      remove.textContent = '×';
      remove.addEventListener('click', function () {
        selectedFiles.splice(index, 1);
        showSelected(selectedFiles);
      });
      row.append(name, remove);
      uploadFileList.appendChild(row);
    });
  }

  function upload(files) {
    return new Promise(function (resolve, reject) {
      if (!files || !files.length) {
        resolve(null);
        return;
      }
      const data = new FormData();
      files.forEach(function (file) {
        data.append('files', file);
        data.append('paths', file.webkitRelativePath || file.name);
      });
      if (uploadSelected) uploadSelected.hidden = true;
      if (uploadProgress) uploadProgress.hidden = false;
      if (progressFill) progressFill.style.width = '0%';
      if (progressText) progressText.textContent = 'Загрузка…';

      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/upload');
      xhr.upload.addEventListener('progress', function (event) {
        if (!event.lengthComputable) return;
        const percent = Math.round((event.loaded / event.total) * 100);
        if (progressFill) progressFill.style.width = percent + '%';
        if (progressText) progressText.textContent = 'Загрузка: ' + percent + '%';
      });
      xhr.addEventListener('load', function () {
        if (xhr.status < 200 || xhr.status >= 300) {
          reject(new Error('Сервер вернул ' + xhr.status));
          return;
        }
        try {
          const answer = JSON.parse(xhr.responseText);
          if (!answer || !answer.url) throw new Error('В ответе нет адреса сборки');
          resolve(answer);
        } catch (error) {
          reject(error);
        }
      });
      xhr.addEventListener('error', function () { reject(new Error('Сеть недоступна')); });
      xhr.send(data);
    });
  }

  if (fileInput) fileInput.addEventListener('change', function (event) { showSelected(event.target.files); });
  if (dirInput) dirInput.addEventListener('change', function (event) { showSelected(event.target.files); });
  if (uploadClear) uploadClear.addEventListener('click', clearSelection);

  if (form) {
    form.addEventListener('submit', async function (event) {
      const hasUrl = urlInput && urlInput.value.trim().length > 0;
      if (!hasUrl && !selectedFiles.length) {
        event.preventDefault();
        notify('Укажите адрес сайта или выберите папку/файл для загрузки', 'warning');
        return;
      }
      if (!selectedFiles.length) return;
      event.preventDefault();
      try {
        const uploaded = await upload(selectedFiles);
        if (!uploaded) return;
        if (uploaded.site_id) {
          window.location.href = '/sites/' + uploaded.site_id;
          return;
        }
        urlInput.value = uploaded.url;
        if (fileInput) fileInput.value = '';
        if (dirInput) dirInput.value = '';
        form.submit();
      } catch (error) {
        if (uploadProgress) uploadProgress.hidden = true;
        if (uploadContent) uploadContent.hidden = false;
        notify('Ошибка загрузки: ' + error.message, 'error');
      }
    });
  }

  if (uploadZone) {
    ['dragenter', 'dragover'].forEach(function (name) {
      uploadZone.addEventListener(name, function (event) {
        event.preventDefault();
        event.stopPropagation();
        uploadZone.classList.add('drag-over');
      });
    });
    ['dragleave', 'drop'].forEach(function (name) {
      uploadZone.addEventListener(name, function (event) {
        event.preventDefault();
        event.stopPropagation();
        uploadZone.classList.remove('drag-over');
      });
    });
    uploadZone.addEventListener('drop', function (event) {
      if (event.dataTransfer.files.length) showSelected(event.dataTransfer.files);
    });
    uploadZone.addEventListener('click', function (event) {
      if (event.target.closest('label, button')) return;
      if (fileInput) fileInput.click();
    });
  }
})();

// --- блок авторизации ---
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
