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

  const accessibleName = (el) => {
    if (!el) return '';
    const aria = (el.getAttribute && el.getAttribute('aria-label')) || '';
    if (aria.trim()) return aria.trim();
    const labelledby = (el.getAttribute && el.getAttribute('aria-labelledby')) || '';
    if (labelledby.trim()) {
      const names = labelledby.split(/\s+/)
        .map((id) => document.getElementById(id))
        .filter(Boolean)
        .map((n) => text(n))
        .join(' ');
      if (names.trim()) return names.trim();
    }
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
    const title = (el.getAttribute && el.getAttribute('title')) || '';
    if (title.trim()) return title.trim();
    return text(el);
  };

  window.__webscopeUtils = { text, cssPath, visible, accessibleName };
})();
"""
