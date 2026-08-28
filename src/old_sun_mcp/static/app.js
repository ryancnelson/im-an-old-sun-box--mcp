const gallantLineHeight = navigator.userAgent.includes("Firefox/") ? 22 / 12 : 1;

const terminal = new Terminal({
  convertEol: true,
  cursorBlink: false,
  cursorStyle: "block",
  cursorInactiveStyle: "block",
  fontFamily: "Gallant12, Menlo, Monaco, Consolas, monospace",
  fontSize: 16,
  fontWeight: "400",
  letterSpacing: 0,
  // Firefox honors Gallant's embedded 12x22 bitmap strike literally, while
  // Chromium derives a 12px CSS line box. Compensate only in Firefox.
  lineHeight: gallantLineHeight,
  scrollback: 5000,
  theme: { background: "#050705", foreground: "#d4ffd4", cursor: "#eaff38", cursorAccent: "#050705" },
});
terminal.open(document.getElementById("terminal"));
terminal.focus();
document.fonts.load("16px Gallant12").then(() => terminal.refresh(0, terminal.rows - 1));

const status = document.getElementById("connection");
const block = document.getElementById("mcp-block");
const vmStats = document.getElementById("vm-stats");
const protocol = location.protocol === "https:" ? "wss:" : "ws:";
const socket = new WebSocket(`${protocol}//${location.host}/ws/console`);
socket.binaryType = "arraybuffer";
const decoder = new TextDecoder();
const encoder = new TextEncoder();

socket.onopen = () => { status.textContent = "broker connected"; };
socket.onclose = () => { status.textContent = "browser disconnected"; };
socket.onerror = () => { status.textContent = "connection error"; };
socket.onmessage = async (event) => {
  if (typeof event.data === "string") {
    const message = JSON.parse(event.data);
    if (message.type === "status") {
      status.textContent = message.connected ? "QEMU connected" : "QEMU disconnected";
      block.checked = message.mcp_write_blocked;
    } else if (message.type === "input_error") {
      terminal.write(`\r\n[broker: ${message.error}]\r\n`);
    }
    return;
  }
  const data = event.data instanceof Blob ? await event.data.arrayBuffer() : event.data;
  terminal.write(decoder.decode(data, { stream: true }));
};

terminal.onData((data) => {
  if (socket.readyState === WebSocket.OPEN) socket.send(encoder.encode(data));
});
block.addEventListener("change", () => {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "set_mcp_write_blocked", blocked: block.checked }));
  }
});
document.querySelectorAll("button[data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.dataset.action;
    if (["reset", "powerdown"].includes(action) && !window.confirm(`${button.textContent}?`)) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/lifecycle/${action}`, { method: "POST" });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error_output || result.error || `HTTP ${response.status}`);
      terminal.write(`\r\n[vm control: ${action} accepted]\r\n`);
    } catch (error) {
      terminal.write(`\r\n[vm control failed: ${error.message}]\r\n`);
    } finally {
      button.disabled = false;
      terminal.focus();
    }
  });
});
const refreshStats = async () => {
  try {
    const response = await fetch("/api/vm-stats");
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    if (!data.running) {
      vmStats.textContent = "VM stopped";
      return;
    }
    const rssMiB = Math.round(Number(data.rss_kib) / 1024);
    vmStats.textContent = `PID ${data.pid} · up ${data.elapsed} · CPU ${data.cpu_percent}% · RSS ${rssMiB} MiB`;
  } catch (_) {
    vmStats.textContent = "statistics unavailable";
  }
};
refreshStats();
setInterval(refreshStats, 10000);
window.addEventListener("resize", () => terminal.focus());
