const chat   = document.getElementById('chat');
const input   = document.getElementById('input');
const sendBtn = document.getElementById('send-btn');
const fileInput = document.getElementById('file-input');
const fileName  = document.getElementById('file-name');
const modelInfo = document.getElementById('model-info');
const themeBtn  = document.getElementById('theme-toggle');

const history = [];

// ── Health check ────────────────────────────────────────────────────────
fetch('/health').then(r => r.json()).then(d => {
  modelInfo.textContent = (d.llm_configured ? '●' : '○') + ' ' + d.tools + ' tools, ' + d.memories + ' memories';
}).catch(() => modelInfo.textContent = '○ offline');

// ── Theme toggle ────────────────────────────────────────────────────────
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('theme', t);
  themeBtn.textContent = t === 'dark' ? '☀️' : '🌙';
}
const saved = localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
applyTheme(saved);
themeBtn.addEventListener('click', () =>
  applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark')
);

// ── Helpers ─────────────────────────────────────────────────────────────
function addMsg(cls, txt) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.textContent = txt;
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

function addSpinner() {
  const d = document.createElement('div');
  d.className = 'spinner';
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

function setBusy(b) {
  sendBtn.disabled   = b;
  input.disabled     = b;
  fileInput.disabled = b;
}

// ── Send ────────────────────────────────────────────────────────────────
async function send(msg, filePath) {
  setBusy(true);
  if (filePath) addMsg('system', '📎 Uploaded: ' + filePath);
  addMsg('user', msg);
  history.push({ role: 'user', content: msg });

  const sp = addSpinner();
  let assistantText = '';

  try {
    const body = { message: msg, history: history.slice(0, -1), stream: true };

    const resp = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    const reader = resp.body.getReader();
    const dec    = new TextDecoder();
    let buf      = '';
    let lastMsg  = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (data === '[DONE]') continue;

        try {
          const ev = JSON.parse(data);

          if (ev.type === 'text') {
            if (!lastMsg || lastMsg.classList.contains('tool-call')) {
              lastMsg = addMsg('assistant', '');
            }
            lastMsg.textContent += ev.content;
            assistantText += ev.content;

          } else if (ev.type === 'tool_start') {
            lastMsg = addMsg('tool-call', '🔧 ' + ev.name + '…');

          } else if (ev.type === 'tool_result') {
            if (lastMsg && lastMsg.classList.contains('tool-call')) {
              lastMsg.textContent += ' done';
            }

          } else if (ev.type === 'tool_error') {
            addMsg('error', '⚠️ ' + ev.name + ': ' + (ev.error || 'failed'));

          } else if (ev.type === 'error') {
            addMsg('error', '⚠️ ' + (ev.message || 'unknown error'));
          }

        } catch (e) { /* parse error — skip */ }
      }
    }
  } catch (e) {
    addMsg('error', 'Connection failed: ' + e.message);
  } finally {
    if (assistantText) history.push({ role: 'assistant', content: assistantText });
    sp.remove();
    setBusy(false);
    input.focus();
  }
}

// ── File upload ─────────────────────────────────────────────────────────
fileInput.addEventListener('change', async () => {
  const f = fileInput.files[0];
  if (!f) return;
  fileName.textContent = '📎 Uploading ' + f.name + '…';

  const fd = new FormData();
  fd.append('file', f);
  try {
    const resp = await fetch('/upload', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.path) {
      fileName.textContent = '✓ ' + f.name;
      send('I uploaded a file. It was saved to: ' + data.path + '\nFilename: ' + f.name + '\nSize: ' + data.size + ' bytes\nMIME: ' + data.mimetype + '\n\nPlease read and summarise it.', null);
    } else {
      fileName.textContent = '✗ upload failed';
      addMsg('error', '⚠️ Upload failed: ' + (data.error || 'unknown error'));
    }
  } catch (e) {
    fileName.textContent = '✗ upload error';
    addMsg('error', '⚠️ Upload error: ' + e.message);
  }
});

// ── Send on button click or Enter ───────────────────────────────────────
sendBtn.addEventListener('click', () => {
  const msg = input.value.trim();
  if (!msg) return;
  const f = fileInput.files[0];
  const filePath = f ? fileName.textContent.replace(/^✓ /, '') : '';
  input.value    = '';
  fileName.textContent = '';
  fileInput.value      = '';
  send(msg, filePath);
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
  }
});
