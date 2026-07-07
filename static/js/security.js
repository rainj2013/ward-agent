"use strict";

function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderMarkdown(text) {
  if (typeof marked === 'undefined') return escapeHtml(text);
  const html = marked.parse(String(text ?? ''));
  return typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize(html) : escapeHtml(text);
}
