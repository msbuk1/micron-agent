"use strict";

const chat = document.getElementById("chat");
const input = document.getElementById("input");
const sendBtn = document.getElementById("send-btn");
const fileInput = document.getElementById("file-input");
const fileName = document.getElementById("file-name");
const modelInfo = document.getElementById("model-info");

// Fetch health on load
fetch("/health")
  .then((r) => r.json())
  .then((d) => {
    modelInfo.textContent =
      (d.llm_configured ? "●" : "○") + " " + d.tools + " tools, " + d.memories + " memories";
  })
  .catch(() => {
    modelInfo.textContent = "○ offline";
  });

// Theme toggle
const themeBtn = document.getElementById("theme-toggle");

function applyTheme(t) {
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("theme", t);
  themeBtn.textContent = t === "dark" ? "☀️" : "🌙";
}

const saved = localStorage.getItem("theme") ||
  (matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light");
applyTheme(saved);

themeBtn.addEventListener("click", () => {
  applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
});

function addSpinner() {
  const d = document.createElement("div");
  d.className = "spinner";
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

function setBusy(b) {
  sendBtn.disabled = b;
  input.disabled = b;
  fileInput.disabled = b;
}

class EventRenderer {
  constructor(chatEl, callbacks) {
    this.chat = chatEl;
    this.onConfirm = (callbacks && callbacks.onConfirm) || function () {};
    this.onCancel = (callbacks && callbacks.onCancel) || function () {};
    this.lastMsg = null;
    this.thinkingBuffer = "";
    this.assistantText = "";
  }

  text(ev) {
    if (
      !this.lastMsg ||
      this.lastMsg.classList.contains("thinking") ||
      this.lastMsg.classList.contains("tool-call")
    ) {
      this.lastMsg = this.addMsg("assistant", "");
    }
    this.lastMsg.textContent += ev.content;
    this.assistantText += ev.content;
    this.thinkingBuffer = "";
  }

  thinking(ev) {
    if (!this.lastMsg || !this.lastMsg.classList.contains("thinking")) {
      this.lastMsg = this.addMsg("thinking", "🤔 " + ev.content);
      this.thinkingBuffer = ev.content;
    } else {
      this.thinkingBuffer += " " + ev.content;
      this.lastMsg.textContent = "🤔 " + this.thinkingBuffer;
    }
    this.chat.scrollTop = this.chat.scrollHeight;
  }

  tool_start(ev) {
    if (this.lastMsg && this.lastMsg.classList.contains("thinking")) {
      this.thinkingBuffer += " 🔧 " + ev.name + "...";
      this.lastMsg.textContent = "🤔 " + this.thinkingBuffer;
    } else {
      this.lastMsg = this.addMsg("thinking", "🤔 🔧 " + ev.name + "...");
      this.thinkingBuffer = "🔧 " + ev.name + "...";
    }
    this.chat.scrollTop = this.chat.scrollHeight;
  }

  tool_result(ev) {
    if (this.lastMsg && this.lastMsg.classList.contains("thinking")) {
      if (this.thinkingBuffer.includes("🔧 " + ev.name)) {
        this.thinkingBuffer = this.thinkingBuffer.replace(
          "🔧 " + ev.name + "...",
          "🔧 " + ev.name + "... done"
        );
        this.lastMsg.textContent = "🤔 " + this.thinkingBuffer;
      }
    }
  }

  tool_error(ev) {
    if (this.lastMsg && this.lastMsg.classList.contains("thinking")) {
      this.thinkingBuffer += " ⚠️ " + ev.name + ": " + (ev.error || "failed");
      this.lastMsg.textContent = "🤔 " + this.thinkingBuffer;
    } else {
      this.addMsg("error", "⚠️ " + ev.name + ": " + (ev.error || "failed"));
    }
  }

  error(ev) {
    this.addMsg("error", "⚠️ " + (ev.message || "unknown error"));
  }

  confirmation_required(ev) {
    const writes = ev.pending_writes || [];
    const details = writes
      .map((w) => {
        const args = Object.entries(w.args || {})
          .map(([k, v]) => k + "=" + String(v).slice(0, 60))
          .join(", ");
        return "  " + w.tool_name + "(" + args + ")";
      })
      .join("\n");
    this.addMsg("system", "⚠️ Write confirmation required:\n" + details + "\n");

    const btnBar = document.createElement("div");
    btnBar.style.cssText = "display:flex;gap:8px;padding:4px 0";

    const okBtn = document.createElement("button");
    okBtn.textContent = "✅ Confirm";
    okBtn.style.cssText =
      "padding:6px 12px;background:var(--btn);border:none;border-radius:4px;color:#fff;cursor:pointer;font-size:13px";

    const cancelBtn = document.createElement("button");
    cancelBtn.textContent = "❌ Cancel";
    cancelBtn.style.cssText =
      "padding:6px 12px;background:var(--error);border:1px solid var(--border);border-radius:4px;color:var(--fg);cursor:pointer;font-size:13px";

    okBtn.onclick = () => {
      btnBar.remove();
      this.onConfirm(writes);
    };
    cancelBtn.onclick = () => {
      btnBar.remove();
      this.addMsg("system", "Write cancelled.");
      this.onCancel();
    };

    btnBar.appendChild(okBtn);
    btnBar.appendChild(cancelBtn);
    this.chat.appendChild(btnBar);
    this.chat.scrollTop = this.chat.scrollHeight;
    return true;
  }

  done(_ev) {
    /* stream end — orchestrator handles cleanup */
  }

  addMsg(cls, txt) {
    const d = document.createElement("div");
    d.className = "msg " + cls;
    d.textContent = txt;
    this.chat.appendChild(d);
    this.chat.scrollTop = this.chat.scrollHeight;
    return d;
  }
}

const history = [];
let pendingConfirm = null;

async function send(msg, filePath, confirmData) {
  setBusy(true);
  const renderer = new EventRenderer(chat, {
    onConfirm: (writes) => {
      pendingConfirm = writes;
      const lastMsg = history[history.length - 1];
      send(lastMsg ? lastMsg.content : "continue", null, pendingConfirm);
    },
    onCancel: () => {
      pendingConfirm = null;
    },
  });
  if (filePath) renderer.addMsg("system", "📎 Uploaded: " + filePath);
  renderer.addMsg("user", msg);
  history.push({ role: "user", content: msg });
  const sp = addSpinner();
  try {
    const body = { message: msg, history: history.slice(0, -1), stream: true };
    if (confirmData) {
      body.confirm = true;
      body.pending_writes = confirmData;
    }
    const resp = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() || "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6).trim();
        if (data === "[DONE]") continue;
        try {
          const ev = JSON.parse(data);
          const handler = renderer[ev.type];
          if (handler) {
            const stop = handler.call(renderer, ev);
            if (stop) return;
          }
        } catch (e) {
          console.error("Event parsing error:", e);
        }
      }
    }
  } catch (e) {
    renderer.addMsg("error", "Connection failed: " + e.message);
  } finally {
    if (renderer.assistantText) history.push({ role: "assistant", content: renderer.assistantText });
    sp.remove();
    setBusy(false);
    input.focus();
  }
}

// File upload
fileInput.addEventListener("change", async () => {
  const f = fileInput.files[0];
  if (!f) return;
  fileName.textContent = f.name;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const resp = await fetch("/upload", { method: "POST", body: fd });
    const data = await resp.json();
    if (data.path) {
      fileName.textContent = "✓ " + f.name;
      input.value = "Read the uploaded file: " + data.filename;
    } else {
      fileName.textContent = "✗ upload failed";
    }
  } catch (_e) {
    fileName.textContent = "✗ upload error";
  }
});

// Send on button click or Enter
sendBtn.addEventListener("click", () => {
  const msg = input.value.trim();
  if (!msg) return;
  const f = fileInput.files[0];
  const filePath = f ? fileName.textContent.replace(/^✓ /, "") : "";
  input.value = "";
  fileName.textContent = "";
  fileInput.value = "";
  send(msg, filePath);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendBtn.click();
  }
});