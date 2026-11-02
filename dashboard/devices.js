import { BrowserStation, bounded } from './browser-station.js';

export function createDevicePanel({ request, changed }) {
  const $ = id => document.getElementById(id);
  let port, stream, imageCapture, agent, busy = false, releaseLock, generation = 0;
  const log = (message, error = false) => {
    $('device-message').textContent = message;
    $('device-message').classList.toggle('device-error', error);
    $('device-message').setAttribute('role', error ? 'alert' : 'status');
    const line = document.createElement('li');
    line.textContent = new Date().toLocaleTimeString('vi-VN') + ' · ' + message;
    $('device-log').prepend(line);
    while ($('device-log').children.length > 12) $('device-log').lastElementChild.remove();
  };
  function render() {
    const connected = !!agent?.active;
    $('btn-devices').textContent = connected ? 'Thiết bị đã kết nối' : 'Kết nối thiết bị';
    $('device-connect').disabled = busy || connected || !port || !stream;
    $('device-disconnect').disabled = busy || !connected;
    $('device-serial').disabled = $('device-camera-start').disabled = $('device-camera').disabled = busy || connected;
    $('device-serial-state').textContent = connected ? 'ESP32 đã xác nhận' : port ? 'Đã chọn cổng USB' : 'Chưa chọn ESP32';
    $('device-inline-status').textContent = connected ? 'Đã nối ESP32 · Giữ tab này hiển thị khi vận hành' : 'Xem trước camera';
    changed?.();
  }
  function stopCamera() {
    const previous = stream; stream = null; imageCapture = null;
    previous?.getTracks().forEach(track => track.stop());
    $('device-video').srcObject = $('device-preview').srcObject = null;
    $('device-inline').hidden = true;
  }
  async function camera() {
    if (agent?.active || busy) return;
    const attempt = generation;
    busy = true; render();
    try {
      const next = await navigator.mediaDevices.getUserMedia({
        video: $('device-camera').value ? { deviceId: { exact: $('device-camera').value } } : true,
        audio: false
      });
      if (attempt !== generation) { next.getTracks().forEach(track => track.stop()); return; }
      stopCamera(); stream = next;
      if (window.ImageCapture) imageCapture = new ImageCapture(stream.getVideoTracks()[0]);
      $('device-video').srcObject = $('device-preview').srcObject = stream;
      $('device-inline').hidden = false;
      await Promise.all([$('device-video').play(), $('device-preview').play()]);
      await capture(); // Do not enable connection until a fresh frame can actually be captured.
      const cameras = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
      if (!cameras.length) cameras.push({ deviceId: stream.getVideoTracks()[0].getSettings().deviceId || '',
        label: stream.getVideoTracks()[0].label || 'Camera đang mở' });
      $('device-camera').replaceChildren(...cameras.map((d, i) => {
        const option = document.createElement('option'); option.value = d.deviceId;
        option.textContent = d.label || 'Camera ' + (i + 1); return option;
      }));
      $('device-camera').value = stream.getVideoTracks()[0].getSettings().deviceId || '';
      try { localStorage.setItem('autosort.camera', $('device-camera').value); } catch { /* Storage is optional. */ }
      const watched = stream.getVideoTracks()[0];
      watched.addEventListener('ended', () => {
        if (stream?.getVideoTracks()[0] !== watched) return;
        generation++; stopCamera();
        if (agent && !agent.closed) void agent.fail(new Error('Camera đã ngắt. Kiểm tra DroidCam rồi kết nối lại.'));
        else log('Camera đã ngắt. Bật lại DroidCam và camera trước khi kết nối.', true);
        render();
      });
      log('Camera đã có hình. Chọn đúng DroidCam trong danh sách nếu đang thấy webcam laptop.');
    } catch (error) {
      stopCamera();
      log(['Camera chưa có hình.', 'Camera không có ảnh mới.'].includes(error.message) ?
        error.message + ' Mở DroidCam và bật camera lại.' :
        'Chưa lấy được hình camera. Cho phép camera trên Chrome, mở DroidCam rồi thử lại.', true);
    }
    finally { busy = false; render(); }
  }
  async function capture() {
    const video = $('device-video');
    const track = stream?.getVideoTracks()[0];
    if (!track || track.readyState !== 'live')
      throw new Error('Camera chưa có hình.');
    let bitmap;
    if (imageCapture) bitmap = await bounded(imageCapture.grabFrame(), 2500, 'Camera không có ảnh mới.');
    else await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => { video.cancelVideoFrameCallback(id); reject(new Error('Camera không có ảnh mới.')); }, 2500);
      const id = video.requestVideoFrameCallback(() => { clearTimeout(timeout); resolve(); });
    });
    const width = bitmap?.width || video.videoWidth, height = bitmap?.height || video.videoHeight;
    if (!width || !height) { bitmap?.close(); throw new Error('Camera chưa có hình.'); }
    const canvas = document.createElement('canvas'), scale = Math.min(1, 1600 / Math.max(width, height));
    canvas.width = Math.round(width * scale); canvas.height = Math.round(height * scale);
    canvas.getContext('2d').drawImage(bitmap || video, 0, 0, canvas.width, canvas.height);
    bitmap?.close();
    for (const quality of [.85, .7, .5]) {
      const image = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
      if (image?.size > 0 && image.size <= 1000000) return image;
    }
    throw new Error('Ảnh camera quá lớn.');
  }
  async function disconnect() {
    if (agent) await agent.close();
    releaseLock?.(); releaseLock = null; agent = null; stopCamera(); render();
  }
  async function connect() {
    if (busy || agent?.active || !port || !stream) return;
    const attempt = generation;
    busy = true; render(); log('Đang kiểm tra cloud và kết nối ESP32…');
    try {
      const health = await request('/health'), ready = await request('/ready');
      if (!health.browser_station_supported || !health.model_ready || !ready.model_ready)
        throw new Error('Cloud/model AI chưa sẵn sàng cho kết nối trình duyệt.');
      if (attempt !== generation) return;
      agent = new BrowserStation({ request, capture, notify: log,
        changed: connected => { if (!connected) { releaseLock?.(); releaseLock = null; } render(); } });
      await new Promise((resolve, reject) => {
        navigator.locks.request('autosort-station-usb', { ifAvailable: true }, async lock => {
          if (!lock) { reject(new Error('Một tab AutoSort khác đang giữ kết nối. Ngắt ở tab đó trước.')); return; }
          try { await agent.connect(port); resolve(); await new Promise(done => { releaseLock = done; }); }
          catch (error) { reject(error); }
        }).catch(reject);
      });
      $('device-dialog').close();
    } catch (error) {
      log(error.message?.includes('Cloud') || error.message?.includes('ESP32') || error.message?.includes('tab AutoSort') ?
        error.message : 'Không kết nối được. Đóng bridge/Serial Monitor, RESET ESP32 rồi thử lại.', true);
      await agent?.close();
    } finally { busy = false; render(); }
  }
  $('btn-devices').addEventListener('click', () => {
    $('device-dialog').showModal();
    const supported = window.isSecureContext && !!navigator.serial && !!navigator.mediaDevices?.getUserMedia
      && !!navigator.locks && !!HTMLVideoElement.prototype.requestVideoFrameCallback;
    $('device-supported').hidden = supported;
    $('device-serial').disabled = $('device-camera-start').disabled = !supported || busy || !!agent?.active;
    if (supported && !$('device-camera').children.length) {
      const option = document.createElement('option'); option.value = ''; option.textContent = 'Cho phép camera để xem danh sách';
      $('device-camera').append(option);
      navigator.mediaDevices.enumerateDevices().then(devices => {
        const cameras = devices.filter(d => d.kind === 'videoinput' && d.label);
        if (cameras.length) {
          $('device-camera').replaceChildren(...cameras.map(d => {
            const item = document.createElement('option'); item.value = d.deviceId; item.textContent = d.label; return item;
          }));
          try {
            const previous = localStorage.getItem('autosort.camera');
            if (cameras.some(d => d.deviceId === previous)) $('device-camera').value = previous;
          } catch { /* Storage is optional. */ }
        }
      }).catch(() => {});
    }
    if (supported && !port) navigator.serial.getPorts().then(ports => {
      if (ports.length === 1 && !port) { port = ports[0]; render(); }
    }).catch(() => {});
  });
  $('device-close').addEventListener('click', () => $('device-dialog').close());
  $('device-dialog').addEventListener('close', () => {
    if (!agent?.active) { generation++; void agent?.close(); stopCamera(); render(); }
  });
  $('device-serial').addEventListener('click', async () => {
    try { port = await navigator.serial.requestPort(); log('Đã chọn ESP32. Bật camera rồi Kết nối trạm.'); render(); }
    catch (error) { if (error.name !== 'NotFoundError') log('Chưa chọn được cổng USB. Kiểm tra dây và quyền Serial.', true); }
  });
  $('device-camera-start').addEventListener('click', camera);
  $('device-camera').addEventListener('change', camera);
  $('device-connect').addEventListener('click', connect);
  $('device-disconnect').addEventListener('click', async () => {
    busy = true; render(); await disconnect(); busy = false;
    log('Đã ngắt thiết bị. RESET ESP32 trước lần kết nối tiếp theo.'); render();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && agent?.active)
      void agent.fail(new Error('Tab điều khiển đã ẩn. Đã ngắt trạm; mở lại tab, RESET ESP32 rồi kết nối lại.'));
  });
  window.addEventListener('beforeunload', event => { if (agent?.active) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('pagehide', () => { void disconnect(); });
  return { disconnect, connected: () => !!agent?.active };
}
