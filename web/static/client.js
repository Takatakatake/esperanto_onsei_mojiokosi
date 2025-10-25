(function(){
  const finalEl = document.getElementById('final');
  const partialEl = document.getElementById('partial');
  const showPartial = document.getElementById('showPartial');
  const fontSize = document.getElementById('fontSize');
  const historyEl = document.getElementById('history');
  const darkMode = document.getElementById('darkMode');

  fontSize.addEventListener('input', () => {
    const v = fontSize.value;
    finalEl.style.fontSize = v + 'px';
    partialEl.style.fontSize = Math.max(24, Math.floor(v*0.75)) + 'px';
  });

  showPartial.addEventListener('change', () => {
    partialEl.style.display = showPartial.checked ? 'block' : 'none';
  });

  function setTheme() {
    document.body.classList.remove('dark','light');
    document.body.classList.add(darkMode.checked ? 'dark' : 'light');
  }
  darkMode.addEventListener('change', setTheme);
  setTheme();

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
          if (showPartial.checked) partialEl.textContent = speaker + (msg.text || '');
        } else if (msg.type === 'final') {
          const text = (msg.text||'').trim();
          if (text) {
            finalEl.textContent = speaker + text;
            const row = document.createElement('div');
            row.className = 'row';
            row.textContent = speaker + text;
            historyEl.appendChild(row);
            historyEl.scrollTop = historyEl.scrollHeight;
          }
          partialEl.textContent = '';
        }
      } catch (e) { console.warn('bad message', e); }
    };
  }
  connect();
})();
