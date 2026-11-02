import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = await readFile(new URL('../dashboard/browser-station.js', import.meta.url), 'utf8');
const { BrowserStation } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const run = '11111111-1111-1111-1111-111111111111';
const start = { id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', runId: run, action: 'START', expiresInSeconds: 12 };
const stop = { ...start, id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', action: 'STOP' };
const hex = x => x.replaceAll('-', '');
const flush = () => new Promise(resolve => setTimeout(resolve, 15));
function fixture(api = async () => ({}), capture = async () => new Blob(['jpeg'], { type: 'image/jpeg' })) {
  const writes = [], calls = [];
  const station = new BrowserStation({ request: async (path, options) => {
    calls.push([path, options]); return api(path, options);
  }, capture });
  station.writer = { write: async data => writes.push(new TextDecoder().decode(data)), releaseLock() {} };
  station.cameraId = 'browser-fixture';
  return { station, writes, calls };
}
test('START is prepared once, duplicate delivery never resends a motor command, ACK is scoped', async () => {
  const { station: s, writes, calls } = fixture(async path => path.endsWith('/poll') ?
    { command: start } : { runId: run, status: 'RUNNING' });
  await s.handleCommand(start, performance.now());
  await s.handleCommand(start, performance.now());
  assert.equal(writes.filter(x => x.startsWith('CONTROL:')).length, 1);
  await s.handleLine('ACK:' + hex(stop.id) + ':RUNNING');
  assert.equal(calls.filter(x => x[0].includes('/ack/')).length, 0);
  await s.handleLine('ACK:' + hex(start.id) + ':RUNNING');
  await s.handleLine('ACK:' + hex(start.id) + ':RUNNING');
  assert.equal(calls.filter(x => x[0].includes('/ack/')).length, 1);
  await s.close();
});
test('STOP superseding START during preparation prevents sending START to ESP32', async () => {
  const { station: s, writes } = fixture(async path => path.endsWith('/poll') ?
    { command: stop } : { runId: run, status: 'RUNNING' });
  await s.handleCommand(start, performance.now());
  assert.equal(writes.some(x => x.includes(':START:')), false);
  assert.equal(writes.filter(x => x.includes(':STOP:')).length, 1);
  await s.close();
});
test('a stopped capture cannot publish its result or restart a new run', async () => {
  let release;
  const { station: s, writes, calls } = fixture(undefined, () => new Promise(resolve => { release = resolve; }));
  s.run = run;
  await s.handleLine('TRIGGER:' + hex(run) + ':1');
  await s.handleLine('TRIGGER:' + hex(run) + ':1'); // Exact duplicate is ignored.
  await s.handleCommand(stop, performance.now());
  await s.handleLine('ACK:' + hex(stop.id) + ':IDLE');
  s.run = '22222222-2222-2222-2222-222222222222';
  release(new Blob(['jpeg'])); await flush();
  assert.equal(writes.some(x => x.startsWith('RESULT:')), false);
  assert.equal(calls.some(x => x[0].endsWith('/infer')), false);
  await s.close();
});
test('one trigger creates one multipart upload and a result bound to run/counter', async () => {
  const { station: s, writes, calls } = fixture(async (path, options) => {
    if (!path.endsWith('/infer')) return {};
    assert(options.body instanceof FormData);
    assert.equal(options.body.get('runId'), run);
    assert.equal(options.body.get('counter'), '1');
    return { label: 'GREEN', run_id: run, camera_id: 'browser-fixture',
      fruit_id: 'F-' + hex(run) + '-1', confidence: .9, model_version: 'real-test-detector' };
  });
  s.run = run;
  await s.handleLine('TRIGGER:' + hex(run) + ':1'); await flush();
  await s.handleLine('TRIGGER:' + hex(run) + ':1'); await flush();
  assert.equal(calls.filter(x => x[0].endsWith('/infer')).length, 1);
  assert.equal(writes.filter(x => x.startsWith('RESULT:')).length, 1);
  assert.equal(writes[0], 'RESULT:' + hex(run) + ':1:GREEN\n');
  await s.close();
});
test('authentication or run conflicts stop the station rather than send fallback motion', async () => {
  for (const status of [401, 403, 409]) {
    const { station: s, writes } = fixture(async () => { throw Object.assign(new Error('denied'), { status }); });
    s.run = run; await s.handleLine('TRIGGER:' + hex(run) + ':1'); await flush();
    assert(s.closed); assert(writes.includes('BRIDGE:STOP\n'));
    assert(!writes.some(x => x.startsWith('RESULT:')));
  }
});
test('camera failure routes only the active object to REJECT, never overrides STOP', async () => {
  const { station: s, writes } = fixture(undefined, async () => { throw new Error('camera lost'); });
  s.run = run; await s.handleLine('TRIGGER:' + hex(run) + ':1'); await flush();
  assert(writes.includes('RESULT:' + hex(run) + ':1:REJECT\n'));
  assert(!s.closed); await s.close();
});
test('fragmented CRLF serial input is assembled, an incomplete line expires and closes', async () => {
  const { station: s, writes } = fixture();
  let input;
  s.reader = new ReadableStream({ start(controller) { input = controller; } }).getReader();
  const reading = s.read();
  input.enqueue(new TextEncoder().encode('CONTROLLER:ID'));
  await flush(); assert(!s.timer);
  input.enqueue(new TextEncoder().encode('LE\r\nSTATE:1\r\n')); await flush();
  assert(s.timer);
  input.enqueue(new TextEncoder().encode('TRIG')); await flush();
  s.partialAt = performance.now() - 1100; s.tick(); await flush();
  assert(s.closed); assert(writes.includes('BRIDGE:STOP\n')); await reading;
});
test('expired ACK and malformed trigger never dispatch a result', async () => {
  const { station: s, writes } = fixture();
  s.pending = { ...start, deadline: performance.now() - 1 };
  await assert.rejects(s.handleLine('ACK:' + hex(start.id) + ':RUNNING'), /quá hạn/);
  s.pending = null; s.run = run;
  await assert.rejects(s.handleLine('TRIGGER:' + hex(run) + ':4294967296'), /không hợp lệ/);
  await assert.rejects(s.handleLine('TRIGGER:' + hex(stop.id) + ':1'), /không thuộc/);
  assert(!writes.some(x => x.startsWith('RESULT:'))); await s.close();
});
test('an ambiguous Serial write never appends STOP to a possibly partial command', async () => {
  const { station: s } = fixture();
  let writes = 0;
  s.writer.write = async () => { writes++; throw new Error('USB write interrupted'); };
  await assert.rejects(s.write('BRIDGE:PING'), /interrupted/);
  await s.close();
  assert.equal(writes, 1);
});
