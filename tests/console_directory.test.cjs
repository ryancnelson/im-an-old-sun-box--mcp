const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
  class Element {
    constructor() { this.options = []; this.listeners = {}; this.dataset = {}; this._value = ''; }
    get value() { return this._value || this.options[0]?.value || ''; }
    set value(v) { this._value = v; }
    append(v) { this.options.push(v); }
    replaceChildren() { this.options = []; this._value = ''; }
    addEventListener(k, f) { this.listeners[k] = f; }
  }
  const elements = new Map();
  const timers = new Map();
  const requests = [];
  const output = [];
  const sockets = [];
  let serial = 0;
  const context = vm.createContext({
    Terminal: class { open() {} focus() {} onData() {} reset() {} write(s) { output.push(s); } },
    WebSocket: class { constructor() { sockets.push(this); } }, TextDecoder, TextEncoder, Blob,
    location: {protocol: 'http:', host: 'localhost:8877'},
    document: {
      getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
      createElement() { return new Element(); }, querySelectorAll() { return []; }, body: new Element(),
    },
    window: {addEventListener() {}},
    setInterval() {},
    setTimeout(f) { const id = ++serial; timers.set(id, f); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch(url) {
      if (url !== '/api/targets') return Promise.resolve({ok: true, json: async () => ({available: false})});
      return new Promise(resolve => requests.push(payload => resolve({ok: true, json: async () => payload})));
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/old_sun_mcp/static/app.js'), 'utf8'), context);
  return {elements, timers, requests, output, context, sockets};
}

const tick = () => new Promise(setImmediate);
const target = id => ({target_id: id, host_id: 'ci', qemu_name: 'guest', pid: 42,
                      endpoint: '/state/console.sock', container_name: 'woodpecker-123'});
const payload = targets => ({hosts: [{host_id: 'ci', label: 'CI', target_count: targets.length}], targets, errors: {}});

test('polling discovers new and removed guests without selecting a target', async () => {
  const h = harness();
  h.requests.shift()(payload([])); await tick();
  assert.equal(h.timers.size, 1);
  h.timers.values().next().value();
  h.requests.shift()(payload([target('one')])); await tick();
  assert.equal(h.elements.get('console-select').options.length, 1);
  assert.match(h.elements.get('console-select').options[0].textContent, /woodpecker-123/);
  h.timers.values().next().value();
  h.requests.shift()(payload([])); await tick();
  assert.equal(h.elements.get('connect-target').disabled, true);
});

test('refresh preserves a pending selection and does not overlap an in-flight poll', async () => {
  const h = harness();
  h.elements.get('refresh-targets').listeners.click();
  assert.equal(h.requests.length, 1);
  h.requests.shift()(payload([target('one'), target('two')])); await tick();
  h.elements.get('console-select').value = 'two';
  h.elements.get('refresh-targets').listeners.click();
  h.requests.shift()(payload([target('one'), target('two'), target('three')])); await tick();
  assert.equal(h.elements.get('console-select').value, 'two');
  assert.equal(h.timers.size, 1);
});

test('repeated discovery failures do not flood terminal output', async () => {
  const h = harness();
  const failed = {...payload([]), errors: {'ci/docker': {kind: 'timeout', message: 'timeout'}}};
  h.requests.shift()(failed); await tick();
  h.elements.get('refresh-targets').listeners.click();
  h.requests.shift()(failed); await tick();
  assert.equal(h.output.filter(s => s.includes('discovery ci/docker')).length, 1);
});

test('selecting a target does not claim a successful connection', async () => {
  const h = harness();
  vm.runInContext('socket.onmessage({data: JSON.stringify({type:"target", target:{host_id:"ci",pid:42,endpoint:"/socket"}})})', h.context);
  assert.match(h.output.join(''), /selected target/);
  assert.doesNotMatch(h.output.join(''), /connected target/);
});

test('connection failures are visible and repeated failures are deduplicated', async () => {
  const h = harness();
  const status = 'socket.onmessage({data: JSON.stringify({type:"status", connected:false, error:"Connection refused", mcp_write_blocked:true})})';
  vm.runInContext(status, h.context);
  vm.runInContext(status, h.context);
  assert.equal(h.output.filter(s => s.includes('Connection refused')).length, 1);
});

test('browser reconnects automatically after a broker deployment', () => {
  const h = harness();
  assert.equal(h.sockets.length, 1);
  h.sockets[0].onclose({code: 1006});
  assert.equal(h.timers.size, 1);
  h.timers.values().next().value();
  assert.equal(h.sockets.length, 2);
});

test('browser does not repeatedly reconnect after authentication is rejected', () => {
  const h = harness();
  h.sockets[0].onclose({code: 4403});
  assert.equal(h.timers.size, 0);
  assert.match(h.elements.get('connection').textContent, /sign in/i);
});
