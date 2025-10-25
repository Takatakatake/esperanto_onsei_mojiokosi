(function(){
  const finalEl = document.getElementById('final');
  const partialEl = document.getElementById('partial');
  const showPartial = document.getElementById('showPartial');
  const fontSize = document.getElementById('fontSize');

  fontSize.addEventListener('input', () => {
    const v = fontSize.value;
    finalEl.style.fontSize = v + 'px';
    partialEl.style.fontSize = Math.max(24, Math.floor(v*0.75)) + 'px';
  });

  showPartial.addEventListener('change', () => {
    partialEl.style.display = showPartial.checked ? 'block' : 'none';
  });

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
        if (msg.type === 'partial') {
          if (showPartial.checked) partialEl.textContent = msg.text || '';
        } else if (msg.type === 'final') {
          // Show as larger line and clear partial
          if ((msg.text||'').trim()) finalEl.textContent = msg.text;
          partialEl.textContent = '';
        }
      } catch (e) { console.warn('bad message', e); }
    };
  }
  connect();
})();

