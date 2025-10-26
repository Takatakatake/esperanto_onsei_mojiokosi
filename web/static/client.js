(function(){
  const finalEl = document.getElementById('final');
  const translationsEl = document.getElementById('translations');
  const partialEl = document.getElementById('partial');
  const showPartial = document.getElementById('showPartial');
  const fontSize = document.getElementById('fontSize');
  const historyEl = document.getElementById('history');
  const darkMode = document.getElementById('darkMode');
  const translationControlsEl = document.getElementById('translationControls');

  const LANG_LABELS = {
    ja: '日本語',
    ko: '한국어',
    en: 'English',
    eo: 'Esperanto'
  };

  const translationVisibility = {};
  let lastTranslations = {};

  translationControlsEl.style.display = 'none';

  function labelForLang(code) {
    return LANG_LABELS[code] || code.toUpperCase();
  }

  function updateFontSizes() {
    const v = Number(fontSize.value);
    finalEl.style.fontSize = `${v}px`;
    partialEl.style.fontSize = `${Math.max(24, Math.floor(v * 0.75))}px`;
    translationsEl.style.fontSize = `${Math.max(24, Math.floor(v * 0.6))}px`;
  }

  fontSize.addEventListener('input', updateFontSizes);
  updateFontSizes();

  showPartial.addEventListener('change', () => {
    partialEl.style.display = showPartial.checked ? 'block' : 'none';
  });

  function setTheme() {
    document.body.classList.remove('dark','light');
    document.body.classList.add(darkMode.checked ? 'dark' : 'light');
  }
  darkMode.addEventListener('change', setTheme);
  setTheme();

  function updateTranslationControlsVisibility() {
    translationControlsEl.style.display = translationControlsEl.childElementCount ? 'flex' : 'none';
  }

  function applyTranslationVisibility(lang) {
    const visible = translationVisibility[lang];
    document.querySelectorAll(`[data-translation-lang="${lang}"]`).forEach((el) => {
      el.classList.toggle('hidden', !visible);
    });
  }

  function ensureToggle(lang) {
    if (lang in translationVisibility) {
      return;
    }
    translationVisibility[lang] = true;
    const wrapper = document.createElement('label');
    wrapper.className = 'toggle';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.dataset.lang = lang;
    checkbox.addEventListener('change', () => {
      translationVisibility[lang] = checkbox.checked;
      applyTranslationVisibility(lang);
      renderFinalTranslations(lastTranslations);
    });
    const text = document.createElement('span');
    text.textContent = labelForLang(lang);
    wrapper.appendChild(checkbox);
    wrapper.appendChild(text);
    translationControlsEl.appendChild(wrapper);
    updateTranslationControlsVisibility();
  }

  function createTranslationLine(lang, text) {
    const line = document.createElement('div');
    line.className = 'translation-line';
    line.dataset.translationLang = lang;
    const label = document.createElement('span');
    label.className = 'translation-label';
    label.textContent = labelForLang(lang);
    const body = document.createElement('span');
    body.className = 'translation-text';
    body.textContent = text;
    line.appendChild(label);
    line.appendChild(body);
    if (!translationVisibility[lang]) {
      line.classList.add('hidden');
    }
    return line;
  }

  function renderFinalTranslations(translations) {
    lastTranslations = translations || {};
    translationsEl.innerHTML = '';
    const entries = Object.entries(lastTranslations).filter(([, value]) => value && value.trim());
    entries.forEach(([lang]) => ensureToggle(lang));
    let visibleCount = 0;
    entries.forEach(([lang, value]) => {
      if (!translationVisibility[lang]) {
        return;
      }
      const line = createTranslationLine(lang, value);
      translationsEl.appendChild(line);
      visibleCount += 1;
    });
    translationsEl.style.display = visibleCount ? 'flex' : 'none';
  }

  function appendToHistory(speaker, text, translations) {
    const row = document.createElement('div');
    row.className = 'row';

    const original = document.createElement('div');
    original.className = 'history-original';
    original.textContent = speaker + text;
    row.appendChild(original);

    const entries = Object.entries(translations || {}).filter(([, value]) => value && value.trim());
    if (entries.length) {
      const list = document.createElement('div');
      list.className = 'history-translations';
      entries.forEach(([lang, value]) => {
        ensureToggle(lang);
        const line = createTranslationLine(lang, value);
        list.appendChild(line);
      });
      row.appendChild(list);
    }

    historyEl.appendChild(row);
    historyEl.scrollTop = historyEl.scrollHeight;
  }

  function connect() {
    const wsUrl = `ws://${location.host}/ws`;
    const ws = new WebSocket(wsUrl);
    ws.onopen = () => console.log('[WS] open');
    ws.onclose = () => {
      console.log('[WS] closed, retrying...');
      setTimeout(connect, 1500);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        const speaker = msg.speaker ? `[${msg.speaker}] ` : '';
        if (msg.type === 'partial') {
          if (showPartial.checked) {
            partialEl.textContent = speaker + (msg.text || '');
          }
        } else if (msg.type === 'final') {
          const text = (msg.text || '').trim();
          finalEl.textContent = speaker + text;
          renderFinalTranslations(msg.translations || {});
          if (text) {
            appendToHistory(speaker, text, msg.translations || {});
          }
          partialEl.textContent = '';
        }
      } catch (e) {
        console.warn('bad message', e);
      }
    };
  }
  connect();
})();
