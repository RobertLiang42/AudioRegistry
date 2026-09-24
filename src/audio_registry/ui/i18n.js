(() => {
  'use strict';
  const supported = [];
  let fallback = 'en-US';
  const storageKey = 'audio-registry.locale';
  let catalog = {};
  let locale = fallback;

  function normalize(value) {
    const code = String(value || '').trim().replace('_', '-').toLowerCase();
    return supported.find(item => item.toLowerCase() === code)
      || supported.find(item => item.toLowerCase().split('-', 1)[0] === code.split('-', 1)[0])
      || null;
  }
  function lookup(key) {
    return key.split('.').reduce((value, part) => value && typeof value === 'object' ? value[part] : undefined, catalog);
  }
  function t(key, values = {}) {
    const template = lookup(key);
    if (typeof template !== 'string') return key;
    return template.replace(/\{([A-Za-z0-9_]+)\}/g, (_, name) => Object.hasOwn(values, name) ? String(values[name]) : `{${name}}`);
  }
  function translateDocument(root = document) {
    root.documentElement?.setAttribute('lang', locale);
    root.querySelectorAll('[data-i18n]').forEach(node => { node.textContent = t(node.dataset.i18n); });
    for (const [attribute, dataName] of [['placeholder','i18nPlaceholder'], ['aria-label','i18nAriaLabel'], ['title','i18nTitle']]) {
      root.querySelectorAll(`[data-${dataName.replace(/[A-Z]/g, c => '-' + c.toLowerCase())}]`).forEach(node => node.setAttribute(attribute, t(node.dataset[dataName])));
    }
  }
  async function load(requested, persist = false) {
    locale = normalize(requested) || fallback;
    if (!supported.includes(locale)) locale = fallback;
    const response = await fetch(`/locales/${locale}.json`, {cache:'no-store'});
    if (!response.ok) throw new Error(`Unable to load locale ${locale}`);
    catalog = await response.json();
    if (persist) localStorage.setItem(storageKey, locale);
    translateDocument();
    return locale;
  }
  const saved = (() => { try { return localStorage.getItem(storageKey); } catch (_) { return null; } })();
  const ready = (async () => {
    const manifestResponse = await fetch('/locales/manifest.json', {cache:'no-store'});
    if (!manifestResponse.ok) throw new Error('Unable to load locale manifest');
    const manifest = await manifestResponse.json();
    supported.splice(0, supported.length, ...manifest.locales);
    fallback = manifest.fallback;
    let configured = null;
    try {
      const response = await fetch('/api/locale', {cache:'no-store'});
      if (response.ok) configured = normalize((await response.json()).locale);
    } catch (_) {}
    const detected = normalize(saved) || configured || (navigator.languages || [navigator.language]).map(normalize).find(Boolean) || fallback;
    return load(detected);
  })().catch(() => load(fallback));
  window.AudioRegistryI18n = {supported, get fallback() { return fallback; }, ready, t, getLocale:() => locale, setLocale:value => load(value, true), translateDocument};
})();
