const terminal = new Terminal({
  convertEol: true,
  cursorBlink: false,
  cursorStyle: "block",
  cursorInactiveStyle: "block",
  fontFamily: "Menlo, Monaco, Consolas, 'Liberation Mono', 'DejaVu Sans Mono', monospace",
  fontSize: 16,
  fontWeight: "400",
  letterSpacing: 0,
  lineHeight: 1,
  scrollback: 5000,
  theme: { background: "#050705", foreground: "#d4ffd4", cursor: "#eaff38", cursorAccent: "#050705" },
});
terminal.open(document.getElementById("terminal"));
terminal.focus();

const status = document.getElementById("connection");
const block = document.getElementById("mcp-block");
const vmStats = document.getElementById("vm-stats");
const hostSelect = document.getElementById("host-select");
const consoleSelect = document.getElementById("console-select");
const refreshTargets = document.getElementById("refresh-targets");
const connectTarget = document.getElementById("connect-target");
const activeHost = document.getElementById("active-host");
const activeSocket = document.getElementById("active-socket");
const activeTransport = document.getElementById("active-transport");
const activePid = document.getElementById("active-pid");
let targets = [];
let currentTarget = null;
let discoveryPending = false;
let discoveryTimer = null;
let discoveryErrors = new Map();
let qemuConnected = false;
let connectionError = null;
const protocol = location.protocol === "https:" ? "wss:" : "ws:";
let socket;
let reconnectTimer;
const decoder = new TextDecoder();
const encoder = new TextEncoder();

const connectBrowser = () => {
const next = new WebSocket(`${protocol}//${location.host}/ws/console`);
socket = next;
socket.binaryType = "arraybuffer";
socket.onopen = () => { terminal.reset(); status.textContent = "broker connected"; };
socket.onclose = (event) => {
  if (socket !== next) return;
  qemuConnected = false;
  clearTimeout(reconnectTimer);
  if (event.code === 4403) {
    status.textContent = "sign in to reconnect";
    return;
  }
  status.textContent = "browser disconnected; reconnecting";
  reconnectTimer = setTimeout(connectBrowser, 1000);
};
socket.onerror = () => { status.textContent = "connection error"; };
socket.onmessage = async (event) => {
  if (socket !== next) return;
  if (typeof event.data === "string") {
    const message = JSON.parse(event.data);
    if (message.type === "status") {
      qemuConnected = message.connected;
      status.textContent = message.connected ? "QEMU connected" : "QEMU disconnected";
      if (message.error && message.error !== connectionError) terminal.write(`\r\n[connection failed: ${message.error}]\r\n`);
      connectionError = message.error || null;
      block.checked = message.mcp_write_blocked;
      if (Object.hasOwn(message, "current_target")) updateActiveTarget(message.current_target, false);
    } else if (message.type === "target") {
      qemuConnected = false;
      status.textContent = "connecting to QEMU";
      terminal.reset();
      updateActiveTarget(message.target, true);
    } else if (message.type === "input_error") {
      terminal.write(`\r\n[broker: ${message.error}]\r\n`);
    }
    return;
  }
  const data = event.data instanceof Blob ? await event.data.arrayBuffer() : event.data;
  terminal.write(decoder.decode(data, { stream: true }));
};
};

terminal.onData((data) => {
  if (qemuConnected && socket.readyState === WebSocket.OPEN) socket.send(encoder.encode(data));
});
block.addEventListener("change", () => {
  if (socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "set_mcp_write_blocked", blocked: block.checked }));
  }
});
const lifecycleButtons = document.querySelectorAll("button[data-action]");
const updateActiveTarget = (target, announce) => {
  currentTarget = target;
  if (!target) {
    activeHost.textContent = "none";
    activeSocket.textContent = "no console selected";
    activeTransport.textContent = "";
    activePid.textContent = "";
  } else {
    activeHost.textContent = target.host_id;
    activeSocket.textContent = target.endpoint || target.socket_path;
    activeTransport.textContent = target.host_id === "minnie-2-2" ? `via local ${target.endpoint_kind || "unix"}` : `via SSH ${target.endpoint_kind || "unix"}`;
    activePid.textContent = `PID ${target.pid}`;
    if (announce) terminal.write(`\r\n[broker: selected target ${target.host_id} PID ${target.pid} ${target.endpoint || target.socket_path}]\r\n`);
  }
  const lifecycleAvailable = target
    ? Boolean(target.capabilities?.lifecycle)
    : document.body.dataset.legacyLifecycle === "true";
  lifecycleButtons.forEach((button) => { button.disabled = !lifecycleAvailable; });
};

const populateConsoles = () => {
  const selected = consoleSelect.value;
  consoleSelect.replaceChildren();
  targets.filter((target) => target.host_id === hostSelect.value).forEach((target) => {
    const option = document.createElement("option");
    option.value = target.target_id;
    option.textContent = `${target.container_name ? `${target.container_name} · ` : ""}${target.qemu_name || "QEMU"} · PID ${target.pid} · ${target.socket_path || target.endpoint}`;
    consoleSelect.append(option);
  });
  if (consoleSelect.options.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No live QEMU consoles";
    option.disabled = true;
    option.selected = true;
    consoleSelect.append(option);
  }
  if ([...consoleSelect.options].some((option) => option.value === selected)) consoleSelect.value = selected;
  connectTarget.disabled = !consoleSelect.value;
};

const loadTargets = async () => {
  if (discoveryPending) return;
  discoveryPending = true;
  clearTimeout(discoveryTimer);
  refreshTargets.disabled = true;
  try {
    const response = await fetch("/api/targets");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    targets = payload.targets;
    const selectedHost = hostSelect.value || currentTarget?.host_id;
    hostSelect.replaceChildren();
    const hosts = payload.hosts || [...new Set(targets.map((target) => target.host_id))].map((hostId) => ({ host_id: hostId, label: hostId }));
    hosts.forEach((host) => {
      const option = document.createElement("option");
      option.value = host.host_id;
      option.textContent = `${host.label}${host.target_count === 0 ? " · no live console" : ""}`;
      hostSelect.append(option);
    });
    if ([...hostSelect.options].some((option) => option.value === selectedHost)) hostSelect.value = selectedHost;
    populateConsoles();
    const nextErrors = new Map();
    Object.entries(payload.errors).forEach(([hostId, error]) => {
      const message = `${error.kind}: ${error.message}`;
      nextErrors.set(hostId, message);
      if (discoveryErrors.get(hostId) !== message) terminal.write(`\r\n[discovery ${hostId}: ${message}]\r\n`);
    });
    discoveryErrors = nextErrors;
  } catch (error) {
    if (discoveryErrors.get("request") !== error.message) terminal.write(`\r\n[discovery failed: ${error.message}]\r\n`);
    discoveryErrors.set("request", error.message);
  } finally {
    discoveryPending = false;
    refreshTargets.disabled = false;
    discoveryTimer = setTimeout(loadTargets, 10000);
  }
};

hostSelect.addEventListener("change", populateConsoles);
consoleSelect.addEventListener("change", () => { connectTarget.disabled = !consoleSelect.value; });
refreshTargets.addEventListener("click", loadTargets);
connectTarget.addEventListener("click", async () => {
  if (!consoleSelect.value) return;
  connectTarget.disabled = true;
  try {
    const response = await fetch("/api/target/select", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Old-Sun-CSRF": "1" },
      body: JSON.stringify({ target_id: consoleSelect.value }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
  } catch (error) {
    terminal.write(`\r\n[target connection failed: ${error.message}]\r\n`);
  } finally {
    connectTarget.disabled = !consoleSelect.value;
    terminal.focus();
  }
});
document.querySelectorAll("button[data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const action = button.dataset.action;
    if (["reset", "powerdown"].includes(action) && !window.confirm(`${button.textContent}?`)) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/lifecycle/${action}`, {
        method: "POST",
        headers: { "X-Old-Sun-CSRF": "1" },
      });
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
connectBrowser();
refreshStats();
loadTargets();
setInterval(refreshStats, 10000);
window.addEventListener("resize", () => terminal.focus());
