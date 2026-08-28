import { Terminal } from "/static/vendor/xterm.mjs";
import { FitAddon } from "/static/vendor/addon-fit.mjs";

const terminal = new Terminal({
  cursorBlink: true,
  convertEol: false,
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  fontSize: 14,
  theme: { background: "#10130f", foreground: "#d8e6d4", cursor: "#b6e3af" },
});
const fit = new FitAddon();
terminal.loadAddon(fit);
terminal.open(document.getElementById("terminal"));
fit.fit();
window.addEventListener("resize", () => fit.fit());

const connection = document.getElementById("connection");
const identity = document.getElementById("identity");
const run = document.getElementById("run");
const lease = document.getElementById("lease");
const cursor = document.getElementById("cursor");
const error = document.getElementById("error");
const blockMcp = document.getElementById("block-mcp");
let socket;

function decodeBase64(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function encodeBase64(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function applyStatus(status) {
  connection.textContent = status.console_connected ? "console connected" : "console offline";
  run.textContent = status.run;
  lease.textContent = status.mcp_lease ? `${status.mcp_lease.owner} (${status.mcp_lease.expires_in_seconds.toFixed(0)}s)` : "none";
  cursor.textContent = String(status.cursor);
  blockMcp.checked = !status.policy.mcp_write_enabled;
  error.textContent = status.policy.error || status.last_connection_error || "";
}

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws/console`);
  socket.addEventListener("open", () => { connection.textContent = "broker connected"; });
  socket.addEventListener("close", () => {
    connection.textContent = "broker disconnected";
    window.setTimeout(connect, 1000);
  });
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "initial") {
      identity.textContent = `signed in as ${message.user.login}`;
      terminal.write(decodeBase64(message.data_base64));
      applyStatus(message.status);
    } else if (message.type === "output") {
      terminal.write(decodeBase64(message.data_base64));
      cursor.textContent = String(message.next_cursor);
    } else if (message.type === "status") {
      applyStatus(message.status);
    } else if (message.type === "error") {
      error.textContent = message.message;
    }
  });
}

terminal.onData((data) => {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "input", data_base64: encodeBase64(data) }));
  }
});

blockMcp.addEventListener("change", async () => {
  const response = await fetch("/api/policy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mcp_write_enabled: !blockMcp.checked }),
  });
  if (!response.ok) {
    error.textContent = `Policy update failed (${response.status})`;
    blockMcp.checked = !blockMcp.checked;
  }
});

connect();
