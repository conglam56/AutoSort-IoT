/** The browser owns one Serial port. All cloud operations use the login cookie + CSRF. */
const hex = value => value.replaceAll('-', '');
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const labels = new Set(['GREEN', 'RIPE', 'REJECT']);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
// Stay below the server's 15-second station lease, including slow responses.
const cloudSilenceLimit = 12000;
const transientPollError = error => [408, 429, 500, 502, 503, 504].includes(error?.status)
  || (!error?.status && ['TimeoutError', 'TypeError'].includes(error?.name));
export const bounded = (promise, ms, message) => {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); })])
    .finally(() => clearTimeout(timer));
};

export class BrowserStation {
  constructor({ request, capture, notify = () => {}, changed = () => {} }) {
    Object.assign(this, { request, capture, notify, changed });
    this.active = false; this.closed = false; this.run = null; this.pending = null;
    this.connection = crypto.randomUUID(); this.seen = new Set(); this.triggers = new Set();
    this.buffer = ''; this.partialAt = 0; this.serialWrites = Promise.resolve(); this.operations = Promise.resolve();
  }
  api(action, options = {}) {
    return this.request('/api/browser-station/' + this.connection + '/' + action,
      { method: 'POST', body: '{}', timeoutMs: 4000, ...options });
  }
  async connect(port) {
    this.port = port;
    try {
      await port.open({ baudRate: 115200, bufferSize: 4096 });
      if (this.closed) { await port.close(); throw new Error('Đã hủy kết nối ESP32.'); }
      this.writer = port.writable.getWriter(); this.reader = port.readable.getReader();
      this.reading = this.read();
      await delay(2000); // ESP32 boards commonly reset when their USB port opens.
      if (this.closed) throw new Error('Kết nối đã đóng.');
      const idle = new Promise(resolve => { this.idle = resolve; });
      await this.write('BRIDGE:CONNECT');
      await bounded(idle, 7000, 'ESP32 chưa sẵn sàng. Nhấn EN/RESET, kiểm tra firmware rồi kết nối lại.');
      const registeredAt = performance.now(), registered = await this.api('register');
      this.cameraId = registered.cameraId; this.registered = true;
      this.lastCloudPoll = registeredAt;
      if (this.closed) {
        try { await this.api('disconnect'); } catch { /* Its lease will expire. */ }
        throw new Error('ESP32 đã ngắt trong lúc đăng ký trạm.');
      }
      this.active = true;
      this.notify('Đã kết nối ESP32 và camera. Motor dừng; dùng Bắt đầu trên web.');
      this.changed(true);
      this.polling = this.pollLoop();
    } catch (error) { await this.close(); throw error; }
  }
  write(line) {
    if (!/^[\x20-\x7e]{1,126}$/.test(line)) return Promise.reject(new Error('Lệnh Serial không hợp lệ.'));
    const operation = this.serialWrites.then(() => {
      if (!this.writer || this.closed) throw new Error('Kết nối ESP32 đã đóng.');
      return bounded(this.writer.write(new TextEncoder().encode(line + '\n')), 2000, 'Ghi ESP32 quá hạn.');
    });
    this.serialWrites = operation.catch(() => { this.writeFailed = true; });
    return operation;
  }
  enqueue(operation) {
    this.operations = this.operations.then(() => { if (!this.closed) return operation(); })
      .catch(error => this.fail(error));
  }
  tick() {
    if (this.closed) return;
    const now = performance.now();
    if (this.active && now - this.lastCloudPoll >= cloudSilenceLimit)
      return this.fail(new Error('Mất liên lạc cloud quá 12 giây. Trạm đã ngắt; kiểm tra mạng rồi kết nối lại.'));
    if (this.buffer && now - this.partialAt >= 1000) return this.fail(new Error('Dòng Serial nhận dở quá hạn.'));
    if (this.pending && now >= this.pending.deadline) return this.fail(new Error('ESP32 chưa xác nhận lệnh đúng hạn.'));
    if (!this.lastPing || now - this.lastPing >= 1000) {
      this.lastPing = now;
      this.write('BRIDGE:PING').catch(error => this.fail(error));
    }
  }
  async read() {
    try {
      while (!this.closed) {
        const { value, done } = await this.reader.read();
        if (done) { if (!this.closed) throw new Error('ESP32 đã ngắt kết nối.'); break; }
        for (const byte of value) {
          if (byte === 10) {
            const line = this.buffer.replace(/\r$/, ''); this.buffer = ''; this.partialAt = 0;
            if (line === 'CONTROLLER:IDLE') {
              this.timer ??= setInterval(() => this.tick(), 200);
              this.idle?.(); this.idle = null;
            } else if (line.startsWith('FAULT:')) {
              throw new Error('ESP32 khóa lỗi (' + line.slice(6).replace(/[^A-Z0-9_]/g, '') + '). Kiểm tra trạm rồi RESET.');
            } else this.enqueue(() => this.handleLine(line));
          } else {
            if (byte > 126 || (byte < 32 && byte !== 13) || this.buffer.length >= 127)
              throw new Error('Dữ liệu Serial không hợp lệ.');
            if (!this.buffer) this.partialAt = performance.now();
            this.buffer += String.fromCharCode(byte);
          }
        }
      }
    } catch (error) { if (!this.closed) void this.fail(error); }
  }
  async pollLoop() {
    while (!this.closed) {
      await this.pollOnce();
      await delay(500);
    }
  }
  async pollOnce() {
    if (this.closed) return;
    const started = performance.now();
    const remaining = cloudSilenceLimit - (started - this.lastCloudPoll);
    const disconnected = () => this.fail(new Error('Mất liên lạc cloud quá 12 giây. Trạm đã ngắt; kiểm tra mạng rồi kết nối lại.'));
    if (!(remaining > 0)) return disconnected();
    let result;
    try {
      // Only polls are retried. START/prepare/ACK and Serial writes are never replayed.
      result = await this.api('poll', { timeoutMs: Math.min(4000, remaining) });
    } catch (error) {
      if (this.closed) return;
      if (!transientPollError(error)) return this.fail(error);
      if (performance.now() - this.lastCloudPoll >= cloudSilenceLimit) return disconnected();
      if (!this.pollDegraded) {
        this.pollDegraded = true;
        this.notify('Cloud phản hồi chậm. Đang thử lại kết nối; giữ tab này hiển thị.');
      }
      return;
    }
    if (this.closed) return;
    // A response arriving after our lease budget must not revive a stale station.
    if (performance.now() - this.lastCloudPoll >= cloudSilenceLimit) return disconnected();
    this.lastCloudPoll = started;
    if (this.pollDegraded) { this.pollDegraded = false; this.notify('Đã khôi phục kết nối cloud.'); }
    this.enqueue(() => this.handleCommand(result.command, started));
  }
  async handleCommand(command, polledAt) {
    if (!command || this.seen.has(command.id)) return;
    if (!uuid.test(command.id) || !uuid.test(command.runId) || !['START', 'PAUSE', 'RESUME', 'STOP'].includes(command.action))
      throw new Error('Lệnh điều khiển không hợp lệ.');
    const deadline = polledAt + Number(command.expiresInSeconds) * 1000;
    if (!(command.expiresInSeconds > 0 && command.expiresInSeconds <= 15) || performance.now() >= deadline)
      throw new Error('Lệnh điều khiển đã quá hạn.');
    if (this.pending && (command.action !== 'STOP' || command.runId !== this.pending.runId))
      throw new Error('Có lệnh chưa được ESP32 xác nhận.');
    if (command.action === 'START') {
      if (this.run) throw new Error('Trạm vẫn có lượt đang hoạt động.');
      const run = await this.api('prepare/' + command.id);
      if (run.runId !== command.runId || run.status !== 'RUNNING') throw new Error('Không mở được phiên.');
      this.run = command.runId;
      const latestAt = performance.now(), latest = (await this.api('poll')).command;
      if (!latest || latest.id !== command.id) {
        if (latest?.action === 'STOP' && latest.runId === command.runId) return this.handleCommand(latest, latestAt);
        throw new Error('Lệnh Bắt đầu đã bị thay thế.');
      }
    } else if ((this.run && this.run !== command.runId) || (!this.run && command.action !== 'STOP'))
      throw new Error('Lệnh không thuộc lượt hiện tại.');
    if (performance.now() >= deadline) throw new Error('Lệnh đã quá hạn trước khi gửi ESP32.');
    if (command.action === 'STOP') this.job?.abort.abort();
    this.pending = { ...command, deadline }; this.seen.add(command.id);
    await this.write('CONTROL:' + hex(command.id) + ':' + command.action + ':' + hex(command.runId));
  }
  async handleLine(line) {
    if (line.startsWith('ACK:')) {
      const match = /^ACK:([0-9a-f]{32}):(IDLE|RUNNING|PAUSED|REJECTED)$/.exec(line);
      if (!match) throw new Error('ACK không hợp lệ.');
      const pending = this.pending;
      if (!pending || match[1] !== hex(pending.id)) return;
      if (performance.now() >= pending.deadline) throw new Error('ACK đã quá hạn.');
      const expected = { START: 'RUNNING', RESUME: 'RUNNING', PAUSE: 'PAUSED', STOP: 'IDLE' }[pending.action];
      const success = match[2] === expected;
      try { await this.api('ack/' + pending.id, { body: JSON.stringify({ state: success ? expected : 'FAULT', success }) }); }
      catch (error) {
        if (error.detail === 'COMMAND_EXPIRED') {
          const now = performance.now(), latest = (await this.api('poll')).command;
          if (latest?.action === 'STOP' && latest.runId === pending.runId) {
            this.pending = null; return this.handleCommand(latest, now);
          }
        }
        throw error;
      }
      this.pending = null;
      if (!success) throw new Error('ESP32 từ chối lệnh. Để IR trống trước khi Bắt đầu; kiểm tra trạm.');
      if (pending.action === 'STOP') { this.job?.abort.abort(); this.job = null; this.run = null; }
      this.notify({ START: 'Đã bật chế độ tự động.', PAUSE: 'Đã tạm dừng.', RESUME: 'Đã tiếp tục.', STOP: 'Đã kết thúc phiên.' }[pending.action]);
      this.changed(true); return;
    }
    if (!line.startsWith('TRIGGER:')) return; // STATE and COUNTS are telemetry, not motor commands.
    const match = /^TRIGGER:([0-9a-f]{32}):([1-9][0-9]{0,9})$/.exec(line);
    if (!match || Number(match[2]) > 0xffffffff) throw new Error('TRIGGER không hợp lệ.');
    if (this.pending?.action === 'STOP') return;
    if (!this.run || match[1] !== hex(this.run)) throw new Error('TRIGGER không thuộc lượt đang chạy.');
    if (this.triggers.has(line)) return;
    if (this.job) throw new Error('Có hơn một vật đang chờ xử lý.');
    this.triggers.add(line);
    const job = { run: this.run, counter: match[2], abort: new AbortController() };
    this.job = job; void this.infer(job);
  }
  async infer(job) {
    let label;
    try {
      const image = await bounded(this.capture(), 3000, 'Camera chưa có khung hình mới.');
      if (job.abort.signal.aborted || this.closed) return;
      const data = new FormData(); data.append('image', image, 'snapshot.jpg');
      data.append('runId', job.run); data.append('counter', job.counter);
      const result = await this.api('infer', { body: data, timeoutMs: 22000,
        signal: AbortSignal.any([job.abort.signal, AbortSignal.timeout(22000)]) });
      if (!labels.has(result.label) || result.run_id !== job.run || result.camera_id !== this.cameraId
          || result.fruit_id !== 'F-' + hex(job.run) + '-' + job.counter
          || !Number.isFinite(result.confidence) || result.confidence < 0 || result.confidence > 1
          || typeof result.model_version !== 'string' || !result.model_version
          || result.model_version.startsWith('mock') || result.decision_reason === 'MOCK_MODE')
        throw new Error('AI trả kết quả không hợp lệ.');
      label = result.label; this.notify('Vật ' + job.counter + ': ' + label + ' · ' + (result.confidence * 100).toFixed(1) + '%');
    } catch (error) {
      if (job.abort.signal.aborted || this.closed) return;
      if ([401, 403, 409].includes(error.status)) { await this.fail(error); return; }
      label = 'REJECT'; this.notify('Chụp/AI chưa thành công. Vật hiện tại đi REJECT dự phòng.', true);
    }
    if (this.closed || this.job !== job || this.run !== job.run || this.pending?.action === 'STOP') return;
    this.job = null;
    this.write('RESULT:' + hex(job.run) + ':' + job.counter + ':' + label).catch(error => this.fail(error));
  }
  async fail(error) {
    if (this.closed) return;
    this.notify(error?.status ? 'Cloud từ chối kết nối (' + (error.detail || error.status) + '). Trạm đã ngắt.' :
      (error?.name === 'TimeoutError' ? 'Cloud phản hồi quá hạn khi xác nhận trạm. Kiểm tra mạng rồi kết nối lại.' :
        error?.message || 'Mất kết nối trạm.'), true);
    await this.close();
  }
  async close() {
    if (this.closed) return;
    // Mark closed before any await: late inference/queued commands can never restart the motor.
    this.closed = true; this.active = false; clearInterval(this.timer); this.job?.abort.abort(); this.run = null;
    this.changed(false);
    if (this.writer && !this.writeFailed) {
      try {
        await bounded(this.serialWrites.then(() => {
          if (!this.writeFailed) return this.writer.write(new TextEncoder().encode('BRIDGE:STOP\n'));
        }),
          1000, 'Stop timeout');
      } catch { /* USB loss leaves the firmware watchdog as the final stop path. */ }
    }
    if (this.registered) {
      try { await this.api('disconnect', { keepalive: true, timeoutMs: 2500 }); } catch { /* Lease expires if offline. */ }
    }
    try { await bounded(this.reader?.cancel(), 1000, 'Read cancel timeout'); } catch { /* Port may already be disconnected. */ }
    try {
      this.reader?.releaseLock(); this.writer?.releaseLock();
      await bounded(this.port?.close(), 2000, 'Port close timeout');
    } catch { /* USB unplugged or stream already closed. Firmware still has its watchdog. */ }
  }
}
