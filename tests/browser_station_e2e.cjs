/** Dedicated localhost Spring/PG/ONNX E2E. Serial is a fixture, camera is Chromium's fake device. */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises'), path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const origin = process.env.AUTOSORT_BROWSER_ORIGIN;
  assert(origin && /^http:\/\/127\.0\.0\.1:\d+$/.test(origin), 'Dedicated localhost test server required');
  const root = path.resolve(__dirname, '..'), out = path.join(root, '.local/browser-station');
  const browser = await chromium.launch({ channel: 'chrome', headless: true,
    args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['camera'] });
  await context.addInitScript(() => {
    window.__cameraResets = [];
    const media = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'srcObject');
    Object.defineProperty(HTMLMediaElement.prototype, 'srcObject', { ...media, set(value) {
      if (!value) window.__cameraResets.push(new Error().stack);
      media.set.call(this, value);
    } });
    let input;
    const encoder = new TextEncoder();
    window.__serialWrites = [];
    window.__emitSerial = line => input.enqueue(encoder.encode(line));
    const port = {
      async open() {
        this.readable = new ReadableStream({ start(controller) { input = controller; } });
        this.writable = new WritableStream({ write(data) {
          const line = new TextDecoder().decode(data); window.__serialWrites.push(line);
          if (line === 'BRIDGE:CONNECT\n') {
            window.__emitSerial('CONTROLLER:ID'); setTimeout(() => window.__emitSerial('LE\r\nSTATE:7\r\n'), 30);
          }
          const control = /^CONTROL:([0-9a-f]{32}):(START|PAUSE|RESUME|STOP):([0-9a-f]{32})\n$/.exec(line);
          if (control) setTimeout(() => window.__emitSerial('ACK:' + control[1] + ':' +
            ({ START: 'RUNNING', RESUME: 'RUNNING', PAUSE: 'PAUSED', STOP: 'IDLE' }[control[2]]) + '\r\n'), 20);
        } });
      },
      async close() {},
      getInfo() { return { usbVendorId: 0x10c4, usbProductId: 0xea60 }; }
    };
    Object.defineProperty(navigator, 'serial', { value: {
      requestPort: async () => port, getPorts: async () => []
    }, configurable: true });
  });
  const page = await context.newPage(), errors = [];
  page.setDefaultTimeout(15000);
  const waitUpload = async () => {
    const deadline = Date.now() + 12000;
    while (!held && Date.now() < deadline) await page.waitForTimeout(50);
    if (!held) {
      await page.screenshot({ path: path.join(out, 'capture-failure.png') });
      throw new Error('Upload did not start: ' + await page.locator('#device-message').textContent()
        + ' DIAG=' + JSON.stringify(await page.evaluate(() => ({
          video: [...document.querySelectorAll('video')].map(v => ({id:v.id,width:v.videoWidth,height:v.videoHeight,
            ready:v.readyState,paused:v.paused,time:v.currentTime,hidden:v.closest('[hidden]')?.id})),
          tracks: document.getElementById('device-video').srcObject?.getTracks().map(t => ({state:t.readyState,muted:t.muted,settings:t.getSettings()})),
          resets:window.__cameraResets.slice(-4),
          uart:window.__serialWrites.filter(x=>!x.startsWith('BRIDGE:PING'))
        }))));
    }
  };
  let uploads = 0, release, held;
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(origin + '/dashboard/login.html');
    await page.locator('#login-username').fill('admin');
    await page.locator('#login-password').fill(process.env.BOOTSTRAP_ADMIN_PASSWORD);
    await page.locator('#login-submit').click();
    await page.waitForURL('**/index.html');
    await page.waitForFunction(() => !document.body.classList.contains('auth-pending'));
    // Verify these are today's packaged assets, not an old jar's static resources.
    for (const name of ['browser-station.js', 'devices.js']) {
      const response = await page.request.get(origin + '/dashboard/' + name);
      assert.equal((await response.text()).replaceAll('\r\n', '\n'),
        (await fs.readFile(path.join(root, 'dashboard', name), 'utf8')).replaceAll('\r\n', '\n'));
    }
    await page.locator('#btn-devices').click();
    await page.locator('#device-serial').click();
    await page.locator('#device-camera-start').click();
    await page.waitForFunction(() => !document.getElementById('device-connect').disabled);
    await page.screenshot({ path: path.join(out, 'connect-desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(out, 'connect-mobile.png') });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert(await page.locator('#device-dialog').evaluate(el => el.scrollWidth <= el.clientWidth + 1));
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('#device-connect').click();
    await page.waitForFunction(() => document.getElementById('btn-devices').textContent === 'Thiết bị đã kết nối');
    await page.waitForFunction(() => !document.getElementById('btn-start').disabled);
    assert(!(await page.evaluate(() => window.__serialWrites)).some(x => x.startsWith('CONTROL:')));
    await page.locator('#btn-start').click();
    await page.waitForFunction(() => document.getElementById('station-status').textContent === 'Chế độ tự động đang hoạt động');
    const writes = await page.evaluate(() => window.__serialWrites);
    const runHex = writes.find(x => x.includes(':START:')).trim().split(':')[3];
    await page.route('**/api/browser-station/*/infer', async route => {
      uploads++;
      const data = route.request().postDataBuffer();
      assert(route.request().headers()['content-type'].startsWith('multipart/form-data; boundary='));
      assert(data.indexOf(Buffer.from([255, 216])) >= 0, 'A real JPEG from the browser camera is uploaded');
      assert(!route.request().headers()['x-api-key'], 'No private device key in the browser');
      held = true; await new Promise(resolve => { release = resolve; });
      try { await route.continue(); } catch { /* STOP can abort the pending upload. */ }
    });
    await page.evaluate(run => window.__emitSerial('TRIGGER:' + run + ':1\r\n'), runHex);
    await waitUpload();
    await page.locator('#btn-pause').click();
    await page.waitForFunction(() => document.getElementById('station-status').textContent.includes('Đã tạm dừng'));
    release();
    await page.waitForFunction(() => window.__serialWrites.some(x => /^RESULT:.*:1:(GREEN|RIPE|REJECT)\n$/.test(x)));
    const current = await (await page.request.get(origin + '/api/session/current')).json();
    assert.equal(current.fruits.length, 1);
    assert.equal(current.fruits[0].modelVersion, 'autosort-yolo11n-detect-v2-13714d07b0-640');
    await page.evaluate(run => window.__emitSerial('TRIGGER:' + run + ':1\r\n'), runHex);
    await page.waitForTimeout(200); assert.equal(uploads, 1);
    await page.locator('#btn-start').click(); // Resume.
    await page.waitForFunction(() => document.getElementById('station-status').textContent === 'Chế độ tự động đang hoạt động');
    held = false;
    await page.evaluate(run => window.__emitSerial('TRIGGER:' + run + ':2\r\n'), runHex);
    await waitUpload();
    await page.locator('#btn-stop').click();
    await page.waitForFunction(() => document.getElementById('station-status').textContent.includes('Trạm sẵn sàng'));
    release(); await page.waitForTimeout(200);
    assert(!(await page.evaluate(() => window.__serialWrites)).some(x => /^RESULT:.*:2:/.test(x)));
    assert.equal(await (await page.request.get(origin + '/api/session/current')).json(), null);
    await page.screenshot({ path: path.join(out, 'connected-dashboard.png') });
    // Hiding the owning tab closes the station; firmware is never left intentionally unattended.
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForFunction(() => window.__serialWrites.includes('BRIDGE:STOP\n'));
    await page.waitForTimeout(500);
    const station = await (await page.request.get(origin + '/api/station')).json();
    assert.equal(station.state, 'OFFLINE');
    assert.equal(station.online, false);
    assert.deepEqual(errors, []);
    console.log('PASS: login -> device dialog -> real browser camera JPEG -> real Java/ONNX/PG -> scoped Serial RESULT');
    console.log('PASS: pause retains one session, duplicate TRIGGER ignored, STOP cancels late AI, hidden tab disconnects');
    console.log('PASS: desktop/mobile dialog, no horizontal overflow, no page errors, no device key sent');
  } catch (error) {
    console.error('UI DIAGNOSTIC', await page.evaluate(() => ({
      message: document.getElementById('device-message')?.textContent,
      dialog:document.getElementById('device-dialog')?.open,
      resets:window.__cameraResets,
      tracks:document.getElementById('device-video')?.srcObject?.getTracks().map(t=>({state:t.readyState,settings:t.getSettings()})),
      log:document.getElementById('device-log')?.textContent
    })));
    await page.screenshot({path:path.join(out,'failure.png')});
    throw error;
  } finally {
    page.on('dialog', dialog => dialog.accept());
    await context.close(); await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
