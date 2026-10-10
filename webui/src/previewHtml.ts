export const EDITOR_IMAGE_ALLOWED_DATA_ATTRS = new Set(['data-editor-image', 'data-layout', 'data-align', 'data-width']);
export const ALLOWED_STYLE_PROPS = new Set(['font-size', 'color', 'font-family', 'background-color', 'text-align', 'font-weight', 'font-style', 'text-decoration', 'margin-left', 'margin-right', 'margin', 'width']);

export const normalizePreviewHtmlContent = (content: string) => {
  const parsed = new DOMParser().parseFromString(`<body>${content || ''}</body>`, 'text/html');

  parsed.body.querySelectorAll('p').forEach(p => {
    if (p.textContent && p.textContent.includes('Connessione in corso alla stanza condivisa')) {
      p.remove();
    }
  });

  parsed.body.querySelectorAll('*').forEach(element => {
    const tag = element.tagName.toLowerCase();
    const isEditorImageContainer = tag === 'div' && element.hasAttribute('data-editor-image');
    const isEditorImageAsset = tag === 'img' && element.parentElement?.hasAttribute('data-editor-image');

    if (!isEditorImageContainer && !isEditorImageAsset) {
      element.removeAttribute('align');
      const htmlEl = element as HTMLElement;
      const allowedStyles = Array.from(htmlEl.style)
        .filter(prop => ALLOWED_STYLE_PROPS.has(prop))
        .map(prop => `${prop}: ${htmlEl.style.getPropertyValue(prop)}`)
        .join('; ');
      if (allowedStyles) {
        element.setAttribute('style', allowedStyles);
      } else {
        element.removeAttribute('style');
      }
      Array.from(element.attributes)
        .filter(attribute => attribute.name.startsWith('data-'))
        .forEach(attribute => element.removeAttribute(attribute.name));
      return;
    }

    if (isEditorImageContainer) {
      Array.from(element.attributes)
        .filter(attribute => attribute.name.startsWith('data-') && !EDITOR_IMAGE_ALLOWED_DATA_ATTRS.has(attribute.name))
        .forEach(attribute => element.removeAttribute(attribute.name));
      element.removeAttribute('class');
      return;
    }

    if (isEditorImageAsset) {
      element.removeAttribute('class');
      Array.from(element.attributes)
        .filter(attribute => attribute.name.startsWith('data-'))
        .forEach(attribute => element.removeAttribute(attribute.name));

      const parentContainer = element.parentElement;
      const widthAttr = element.getAttribute('width');
      if (!widthAttr && parentContainer) {
        const rawWidth = parentContainer.getAttribute('data-width') || parentContainer.style.width || '56';
        const numeric = Number.parseFloat(rawWidth);
        const validPercent = Number.isFinite(numeric) ? Math.min(100, Math.max(20, Math.round(numeric))) : 56;
        const targetPx = Math.round((634 * validPercent) / 100);
        element.setAttribute('width', String(targetPx));
      }
      return;
    }

    element.removeAttribute('class');
    Array.from(element.attributes)
      .filter(attribute => attribute.name.startsWith('data-'))
      .forEach(attribute => element.removeAttribute(attribute.name));
  });

  return parsed.body.innerHTML;
};
