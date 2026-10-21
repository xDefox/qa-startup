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

  const cssPath = (el) => {
    if (!el || el.nodeType !== 1) return null;
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      if (node === document.documentElement) {
        parts.unshift('html');
        break;
      }
      let part = node.tagName.toLowerCase();
      if (node.id) {
        parts.unshift('#' + CSS.escape(node.id));
        break;
      }
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
