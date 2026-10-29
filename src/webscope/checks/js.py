"""Общие JS-хелперы, инжектируемые в страницу перед проверками.

Хелперы дают единый способ получить CSS-селектор элемента и его доступное имя —
это нужно и для отчёта, и для того, чтобы по находке можно было сразу открыть
элемент (и скриншотить его).
"""

from __future__ import annotations

JS_UTILS = r"""
(() => {
  if (window.__webscopeUtils) return;

  const text = (el) => ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g, ' ').trim();

  // Сгенерированные id (react-aria-123, :r0:, uuid, счётчики) меняются между
  // рендерами — по ним нельзя строить устойчивый селектор для диффов.
  const looksGenerated = (id) => {
    if (!id) return true;
    if (id.length > 64) return true;
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(id)) return true;  // uuid
    if (/^[0-9a-f]{16,}$/i.test(id)) return true;            // hex-хеш
    if (/^\d+$/.test(id)) return true;                        // чистое число
    if (/^:r[0-9a-z]+:$/i.test(id)) return true;              // react hooks / radix
    if (/-{1,2}\d{2,}$/.test(id)) return true;                // item-123, item--45
    return false;
  };

  // Тестовые атрибуты — самый устойчивый якорь: разработчик держит их стабильными.
  const stableAttr = (el) => {
    for (const attr of ['data-testid', 'data-test', 'data-cy', 'data-qa']) {
      const value = el.getAttribute && el.getAttribute(attr);
      if (value && value.trim()) {
        return '[' + attr + '="' + value.trim().replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"]';
      }
    }
    return null;
  };

  const cssPath = (el) => {
    if (!el || el.nodeType !== 1) return null;
    const ownAttr = stableAttr(el);
    if (ownAttr) return el.tagName.toLowerCase() + ownAttr;
    if (el.id && !looksGenerated(el.id)) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      if (node === document.documentElement) {
        parts.unshift('html');
        break;
      }
      const anchor = stableAttr(node);
      if (anchor) {
        parts.unshift(node.tagName.toLowerCase() + anchor);
        break;
      }
      if (node.id && !looksGenerated(node.id)) {
        parts.unshift('#' + CSS.escape(node.id));
        break;
      }
      let part = node.tagName.toLowerCase();
      const parent = node.parentElement;
      if (parent) {
        const twins = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (twins.length > 1) part += ':nth-of-type(' + (twins.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };

  const visible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    const style = window.getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none';
  };

  // Текст из aria-labelledby: список id → текстовые узлы.
  const labelledbyText = (el) => {
    const ids = (el.getAttribute && el.getAttribute('aria-labelledby')) || '';
    if (!ids.trim()) return '';
    return ids.trim().split(/\s+/)
      .map((id) => document.getElementById(id))
      .filter(Boolean)
      .map((n) => text(n))
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
  };

  // Элемент не показан пользователю: display:none у самого или у предка.
  // checkVisibility есть в Chromium 105+; фолбэк — по вычисленному стилю.
  const hiddenForUser = (node) => {
    if (typeof node.checkVisibility === 'function') {
      return !node.checkVisibility({ checkOpacity: false, checkVisibilityCSS: true });
    }
    const style = window.getComputedStyle(node);
    return style.display === 'none' || style.visibility === 'hidden';
  };

  // Имя из содержимого: текст потомков + alt у картинок + подписи svg/иконок.
  // Без обхода <a><img alt="Telegram"></a> выглядела ссылкой без имени — это
  // давало сотни ложных срабатываний на реальных сайтах (axe такие ссылки считает
  // именованными). aria-hidden и display:none скринридер не читает — и мы не читаем.
  const nameFromContent = (el) => {
    let out = '';
    const walk = (node) => {
      if (!node) return;
      if (node.nodeType === 3) { out += ' ' + (node.nodeValue || ''); return; }
      if (node.nodeType !== 1) return;
      if (node.getAttribute('aria-hidden') === 'true') return;
      if (hiddenForUser(node)) return;
      // Имя вложенного узла: aria-labelledby/aria-label важнее его содержимого.
      const nested = labelledbyText(node)
        || ((node.getAttribute('aria-label') || '').trim());
      if (nested) { out += ' ' + nested; return; }
      const tag = node.tagName.toUpperCase();  // у SVG tagName строчный
      if (tag === 'IMG') { out += ' ' + (node.getAttribute('alt') || '').trim(); return; }
      if (tag === 'SVG') {
        const svgTitle = node.querySelector('title');
        out += ' ' + (svgTitle ? text(svgTitle) : '');
        return;
      }
      if (tag === 'INPUT') {
        const type = (node.getAttribute('type') || '').toLowerCase();
        if (['submit', 'button', 'reset'].includes(type)) out += ' ' + (node.value || '').trim();
        return;
      }
      if (tag === 'BR') { out += ' '; return; }
      for (const child of node.childNodes) walk(child);
    };
    walk(el);
    return out.replace(/\s+/g, ' ').trim();
  };

  // Порядок как в accname: aria-labelledby → aria-label → нативное имя
  // (alt/value/label) → содержимое → title.
  const accessibleName = (el) => {
    if (!el) return '';
    const labelledby = labelledbyText(el);
    if (labelledby) return labelledby;
    const aria = (el.getAttribute && el.getAttribute('aria-label')) || '';
    if (aria.trim()) return aria.trim();
    if (el.tagName === 'IMG') return (el.getAttribute('alt') || '').trim();
    if (el.tagName === 'INPUT') {
      const type = (el.getAttribute('type') || 'text').toLowerCase();
      if (['submit', 'button', 'reset'].includes(type)) return (el.value || '').trim();
      if (el.id) {
        const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (label && text(label)) return text(label);
      }
      const wrapping = el.closest && el.closest('label');
      if (wrapping && text(wrapping)) return text(wrapping);
    }
    const fromContent = nameFromContent(el);
    if (fromContent) return fromContent;
    const title = (el.getAttribute && el.getAttribute('title')) || '';
    return title.trim();
  };

  window.__webscopeUtils = { text, cssPath, visible, accessibleName };
})();
"""
