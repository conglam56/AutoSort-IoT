import { createAdminConsole } from './admin.js';
import { canOperate, isAdminRole, roleLabel } from './permissions.js';

/**
 * Authenticated AutoSort monitoring and acknowledged station controls.
 * People use HttpOnly cookie sessions; device keys never enter this client.
 */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const LABEL_NAMES = { GREEN: 'Quất xanh', RIPE: 'Quất chín', REJECT: 'Cần loại', MOCK: 'Chưa phân loại' };
  const END_REASONS = { NORMAL_STOP: 'Dừng bình thường', CONNECTION_LOST: 'Mất kết nối', CONTROLLER_FAULT: 'Lỗi trạm', SERIAL_ERROR: 'Lỗi kết nối ESP32', STOP_UNCONFIRMED: 'Chưa xác nhận dừng', START_FAILED: 'Chưa khởi động thành công', BRIDGE_ERROR: 'Lỗi bộ kết nối' };
  const LABEL_COLORS = { GREEN: '#27815d', RIPE: '#c17b23', REJECT: '#c65b54', MOCK: '#8b99a5' };
  const state = {
    mode: 'live', activeTab: 'tab-live', sessions: [], currentSession: null,
    selectedHistorySessionId: null, selectedFruitId: null, filter: 'ALL', search: '',
    cloudOnline: false, health: null, busy: false, revision: 0,
    threshold: 0.70, lastSync: null, user: null, creating: false, operationToken: null, sessionAction: null, endTarget: null,
    apiBase: location.pathname.startsWith('/dashboard') || location.port === '8000' ? '' : 'http://127.0.0.1:8000'
  };
  const failedImageSources = new Set();
  let adminConsole;
  const isAdmin = () => isAdminRole(state.user);
  const mayOperate = () => canOperate(state.user);

  function updateIdentity(user) {
    state.user = user;
    adminConsole?.identityChanged(user);
    if (state.activeTab === 'tab-admin' && !isAdmin()) switchTab('tab-live');
  }

  function time(value) {
    return new Date(value).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  function date(value) { return new Date(value).toLocaleDateString('vi-VN'); }
  function duration(start, end = Date.now()) {
    const seconds = Math.max(0, Math.floor((new Date(end) - new Date(start)) / 1000));
    return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(v => String(v).padStart(2, '0')).join(':');
  }
  function setText(id, value) { $(id).textContent = value; }
  function safeImage(value) {
    if (typeof value !== 'string') return '';
    value = value.trim();
    if (!value) return '';
    if (/^data:image\/(jpeg|png|webp);base64,[a-z\d+/=]+$/i.test(value)) return value;
    try {
      const url = new URL(value, location.href);
      return ['http:', 'https:', 'file:'].includes(url.protocol) && url.origin === location.origin ? url.href : '';
    } catch { return ''; }
  }
  function appendSnapshotImage(container, fruit, className, alt) {
    const src = safeImage(fruit.image);
    const showUnavailable = message => {
      container.replaceChildren(document.createTextNode(message));
      container.classList.add(className === 'strip-thumb-img' ? 'strip-no-image' : 'table-no-image');
      container.title = message + ' · ' + fruit.id;
    };
    if (!src || (true && fruit.image.startsWith('samples/'))) {
      showUnavailable('Chưa có ảnh'); return;
    }
    if (failedImageSources.has(src)) { showUnavailable('Không tải được ảnh'); return; }
    const image = document.createElement('img');
    image.className = className; image.alt = alt; image.loading = 'lazy';
    image.addEventListener('error', () => {
      failedImageSources.add(src);
      showUnavailable('Không tải được ảnh');
    }, { once: true });
    image.src = src;
    container.append(image);
  }
  function stats(session) {
    const fruits = session?.fruits || [];
    const counts = { GREEN: 0, RIPE: 0, REJECT: 0, MOCK: 0 };
    fruits.forEach(f => counts[Object.hasOwn(counts, f.label) ? f.label : 'MOCK']++);
    const total = fruits.length;
    const classified = counts.GREEN + counts.RIPE + counts.REJECT;
    return {
      counts, total, classified,
      latency: total ? (fruits.reduce((sum, f) => sum + f.inferenceMs, 0) / total).toFixed(1) : null,
      passRate: classified ? ((counts.GREEN + counts.RIPE) / classified * 100).toFixed(1) + '%' : '—',
      ppm: total ? (total / Math.max(0.5, (new Date(session.endTime || Date.now()) - new Date(session.startTime)) / 60000)).toFixed(1) : '0',
      percent: label => total ? (counts[label] / total * 100).toFixed(1) : '0'
    };
  }
  function renderSource() {
    const notice = $('source-notice');
    notice.dataset.source = state.mode;
    notice.setAttribute('aria-busy', String(state.busy));
    setText('source-notice-text', state.busy && !state.lastSync ? 'Đang kết nối máy chủ AI và tải phiên phân loại…'
      : state.cloudOnline
        ? state.health?.model_ready ? 'Đang nhận dữ liệu máy chủ · Tự cập nhật mỗi 5 giây.' : 'Đã kết nối máy chủ · Mô hình chưa sẵn sàng. Kết quả MOCK chưa được phân loại.'
        : state.lastSync ? 'Mất kết nối máy chủ · Đang hiển thị dữ liệu lần đồng bộ cuối. Kiểm tra dịch vụ AI.' : 'Chưa kết nối máy chủ AI. Chạy dịch vụ rồi nhấn “Thử kết nối lại”.');
    setText('source-state', state.busy && !state.lastSync ? 'Đang kết nối' : state.cloudOnline ? 'Đã kết nối' : 'Chưa kết nối');
    const pip = $('cloud-status-pill').querySelector('.pip');
    pip.className = 'pip ' + (state.cloudOnline ? 'online' : 'offline');
    setText('cloud-latency', state.cloudOnline ? state.health?.latency + ' ms' : 'Ngoại tuyến');
    setText('model-ver', state.health?.model_version || 'Chưa xác định');
    setText('footer-source', state.lastSync ? 'Đồng bộ lúc ' + time(state.lastSync) : 'Chưa đồng bộ');
    setText('camera-fps', 'Ảnh từ máy chủ');
    setText('image-source-label', 'Ảnh ghi nhận');
    $('btn-sim-trigger').disabled = state.cloudOnline || state.busy;
    $('btn-sim-trigger').innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-refresh"/></svg>' + (state.busy && !state.lastSync ? 'Đang kết nối…' : state.cloudOnline ? 'Đang tự cập nhật' : 'Thử kết nối lại');
    const operating = mayOperate(), running = state.currentSession?.status === 'RUNNING';
    $('btn-end-session').hidden = !operating || !isAdmin() || !running || state.currentSession.automatic;
    $('btn-end-session').disabled = !operating || !running || state.creating || !state.cloudOnline || state.busy;
    setText('account-name', state.user?.username || 'Khách tham quan');
    setText('account-role', roleLabel(state.user));
    $('session-permission-note').hidden = state.activeTab === 'tab-admin';
    renderStation();
    setText('session-permission-note', running && !state.currentSession.automatic ? 'Phiên cũ được tạo thủ công. Admin cần đóng phiên này trước khi bắt đầu lượt chạy tự động.' : 'Bắt đầu mở phiên mới. Tạm dừng giữ nguyên phiên; Kết thúc dừng trạm và đóng phiên.');
    setText('btn-account', 'Đăng xuất');
    const percent = Math.round(state.threshold * 100);
    const highestConfidence = state.health?.decision_policy === 'highest_confidence';
    $('confidence-threshold').hidden = highestConfidence;
    $('confidence-threshold').style.left = percent + '%';
    $('confidence-threshold').title = 'Ngưỡng phân loại ' + percent + '%';
    setText('threshold-label', highestConfidence ? 'Chọn điểm cao nhất' : 'Ngưỡng đạt ' + percent + '%');
  }
  function renderLive() {
    const session = state.currentSession;
    const summary = stats(session);
    setText('live-session-name', session ? session.name : 'Chưa có phiên');
    setText('live-session-start', session ? time(session.startTime) : '—');
    setText('live-total-count', summary.total);
    setText('session-pass-rate', summary.passRate);
    $('live-ppm-rate').replaceChildren(document.createTextNode(summary.ppm + ' '));
    const unit = document.createElement('span'); unit.className = 'unit'; unit.textContent = 'quả/phút'; $('live-ppm-rate').append(unit);
    setText('session-avg-ppm', summary.ppm + ' quả/phút');
    setText('session-avg-latency', summary.latency ? summary.latency + ' ms' : '—');
    $('session-status-tag').replaceChildren();
    const dot = document.createElement('span'); dot.className = 'pip ' + (session && state.cloudOnline ? 'online' : 'offline'); dot.setAttribute('aria-hidden', 'true');
    $('session-status-tag').append(dot, document.createTextNode(session ? session.status === 'RUNNING' ? 'Đang chạy' : 'Đã kết thúc' : 'Chờ kết nối'));
    const fruit = session?.fruits.find(f => (f.recordId || f.id) === state.selectedFruitId) || session?.fruits.at(-1);
    renderInspection(fruit);
    setText('donut-center-total', summary.total);
    setText('donut-session-tag', session ? session.name : 'Phiên hiện tại');
    for (const label of ['GREEN', 'RIPE', 'REJECT']) {
      const prefix = 'donut-' + label.toLowerCase();
      setText(prefix + '-count', summary.counts[label] + ' quả');
      setText(prefix + '-pct', summary.percent(label) + '%');
      $(prefix + '-bar').style.width = summary.percent(label) + '%';
    }
    $('current-session-donut').setAttribute('aria-label', 'Phân bố ' + summary.total + ' quả: xanh ' + summary.counts.GREEN + ', chín ' + summary.counts.RIPE + ', loại ' + summary.counts.REJECT + ', chưa phân loại ' + summary.counts.MOCK);
    const note = summary.counts.MOCK ? summary.counts.MOCK + ' kết quả MOCK chưa được phân loại. Tỉ lệ đạt chỉ tính trên quả đã phân loại.' : state.mode === 'live' && state.health?.decision_policy === 'highest_confidence' ? 'Chọn nhãn có điểm cao nhất trong vùng nhận diện. Không áp ngưỡng 70% và không ưu tiên riêng nhãn REJECT.' : 'Quả dưới ngưỡng tin cậy được xếp vào khay loại để kiểm tra lại.';
    document.querySelector('.quality-note p').textContent = note;
    drawDonut(summary);
    renderRecent(session?.fruits || []);
    updateClock();
  }
  function renderInspection(fruit) {
    const image = $('latest-fruit-img');
    const src = safeImage(fruit?.image);
    // The API may return a sample placeholder for an unavailable snapshot.
    const failedImage = failedImageSources.has(src);
    const hasImage = Boolean(src) && !failedImage && !fruit.image.startsWith('samples/');
    image.hidden = !hasImage;
    if (hasImage) { if (image.getAttribute('src') !== src) image.src = src; image.alt = LABEL_NAMES[fruit.label] + ', mã quả ' + fruit.id; }
    else image.removeAttribute('src');
    $('camera-empty').hidden = hasImage;
    $('camera-empty').querySelector('strong').textContent = failedImage ? 'Không tải được ảnh' : fruit ? 'Chưa có ảnh ghi nhận' : 'Chờ ảnh đầu tiên';
    $('camera-empty').querySelector('span').textContent = failedImage ? 'Thông tin phân loại vẫn được giữ. Chọn một quả khác để xem ảnh.' : fruit ? 'Máy chủ đã gửi kết quả nhưng chưa có ảnh chụp kèm theo.' : 'Kết quả sẽ xuất hiện khi phiên có dữ liệu.';
    $('ai-overlay-tag').hidden = !fruit;
    const confidence = fruit ? (fruit.confidence * 100).toFixed(1) : null;
    setText('overlay-label-badge', fruit ? fruit.label : '—');
    $('overlay-label-badge').className = 'grade-badge badge-' + (fruit?.label || 'mock').toLowerCase();
    setText('overlay-conf-badge', confidence ? confidence + '%' : '—');
    setText('telemetry-conf', confidence ? confidence + '%' : '—');
    $('telemetry-conf-fill').style.width = (confidence || 0) + '%';
    $('telemetry-conf-fill').style.background = LABEL_COLORS[fruit?.label] || LABEL_COLORS.MOCK;
    $('confidence-meter').setAttribute('aria-valuenow', confidence || '0');
    setText('telemetry-fruit-id', fruit ? '#' + fruit.id : '—');
    setText('telemetry-timestamp', fruit ? time(fruit.timestamp) + ' · ' + date(fruit.timestamp) : '—');
    setText('telemetry-latency', fruit ? fruit.inferenceMs.toFixed(1) + ' ms' : '—');
    setText('telemetry-decision', fruit ? fruit.label === 'MOCK' ? 'Không điều khiển · MOCK' : fruit.servoAction : 'Đang chờ quả');
    setText('inspection-caption', fruit ? 'Ghi nhận · #' + fruit.id + ' · ' + (LABEL_NAMES[fruit.label] || 'Chưa phân loại') : 'Chưa có kết quả trong phiên');
  }
  function drawDonut(summary) {
    const canvas = $('current-session-donut');
    const dpr = window.devicePixelRatio || 1;
    canvas.width = 200 * dpr; canvas.height = 200 * dpr;
    canvas.style.width = '200px'; canvas.style.height = '200px';
    const ctx = canvas.getContext('2d'); ctx.scale(dpr, dpr);
    ctx.beginPath(); ctx.arc(100, 100, 79, 0, Math.PI * 2); ctx.lineWidth = 18; ctx.strokeStyle = '#edf2ee'; ctx.stroke();
    if (!summary.total) return;
    let start = -Math.PI / 2;
    const segments = Object.entries(summary.counts).filter(([, count]) => count > 0);
    segments.forEach(([label, count]) => {
      const slice = count / summary.total * Math.PI * 2;
      const gap = segments.length > 1 ? Math.min(0.065, slice / 4) : 0;
      ctx.beginPath(); ctx.arc(100, 100, 79, start + gap / 2, start + slice - gap / 2);
      ctx.lineWidth = 18; ctx.lineCap = 'butt'; ctx.strokeStyle = LABEL_COLORS[label]; ctx.stroke();
      start += slice;
    });
  }
  function badge(fruit, text) {
    const element = document.createElement('span');
    element.className = 'badge badge-' + fruit.label.toLowerCase();
    element.textContent = text || fruit.label;
    return element;
  }
  function renderRecent(fruits) {
    const strip = $('recent-fruits-strip');
    const focusedId = strip.contains(document.activeElement) ? document.activeElement.dataset.fruitId : null;
    const scrollLeft = strip.scrollLeft;
    strip.replaceChildren();
    const recent = fruits.slice(-10).reverse();
    setText('recent-count', recent.length);
    if (!recent.length) { const empty = document.createElement('p'); empty.className = 'filmstrip-empty'; empty.textContent = 'Chưa có quả trong phiên. Kết quả mới sẽ xuất hiện tại đây.'; strip.append(empty); return; }
    const selected = state.selectedFruitId || recent[0].recordId || recent[0].id;
    recent.forEach(fruit => {
      const key = fruit.recordId || fruit.id;
      const card = document.createElement('button');
      card.className = 'strip-item-card' + (key === selected ? ' selected' : '');
      card.dataset.fruitId = key;
      card.setAttribute('aria-label', 'Xem quả ' + fruit.id + ', ' + (LABEL_NAMES[fruit.label] || 'Chưa phân loại'));
      card.setAttribute('aria-pressed', String(key === selected));
      const wrap = document.createElement('div'); wrap.className = 'strip-thumb-wrap';
      appendSnapshotImage(wrap, fruit, 'strip-thumb-img', '');
      const meta = document.createElement('div'); meta.className = 'strip-meta';
      const id = document.createElement('span'); id.className = 'strip-id'; id.textContent = fruit.id;
      const stamp = document.createElement('span'); stamp.className = 'strip-time'; stamp.textContent = time(fruit.timestamp);
      const tag = badge(fruit, fruit.label + ' ' + (fruit.confidence * 100).toFixed(0) + '%'); tag.classList.add('strip-badge');
      meta.append(id, stamp); card.append(wrap, meta, tag);
      card.addEventListener('click', () => {
        state.selectedFruitId = key;
        renderInspection(fruit);
        strip.querySelectorAll('button').forEach(button => { const active = button === card; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
      });
      strip.append(card);
    });
    strip.scrollLeft = scrollLeft;
    if (focusedId) [...strip.children].find(card => card.dataset.fruitId === focusedId)?.focus({ preventScroll: true });
  }
  function selectedSession() { return state.sessions.find(s => s.id === state.selectedHistorySessionId) || state.currentSession; }
  function renderHistory() {
    const select = $('session-dropdown'); select.replaceChildren();
    state.sessions.slice().reverse().forEach(session => {
      const option = document.createElement('option');
      option.value = session.id; option.textContent = session.name + ' · ' + date(session.startTime) + ' · ' + session.fruits.length + ' quả' + (END_REASONS[session.endReason] ? ' · ' + END_REASONS[session.endReason] : '');
      option.selected = session.id === state.selectedHistorySessionId; select.append(option);
    });
    if (!state.sessions.length) { const option = document.createElement('option'); option.textContent = 'Chưa có phiên'; select.append(option); }
    select.disabled = !state.sessions.length;
    const session = selectedSession(); const summary = stats(session);
    setText('history-table-title', session ? 'Nhật ký · ' + session.name : 'Nhật ký phân loại');
    setText('kpi-total-val', summary.total);
    ['GREEN', 'RIPE', 'REJECT'].forEach(label => { const prefix = 'kpi-' + label.toLowerCase(); setText(prefix + '-val', summary.counts[label]); setText(prefix + '-sub', summary.percent(label) + '% phiên này'); });
    $('btn-export-csv').disabled = !summary.total;
    renderTable();
  }
  function decisionText(fruit) {
    return ({ LOW_CONFIDENCE: 'Độ tin cậy thấp', CLASSIFIED: 'Đã phân loại', MOCK_MODE: 'Chế độ MOCK' })[fruit.decisionReason] || fruit.decisionReason || '—';
  }
  function renderTable() {
    const fruits = selectedSession()?.fruits || [];
    const filtered = fruits.filter(f => (state.filter === 'ALL' || f.label === state.filter) && (!state.search || (f.id + ' ' + f.label + ' ' + (LABEL_NAMES[f.label] || '')).toLowerCase().includes(state.search)));
    const body = $('fruits-table-body'); body.replaceChildren();
    $('table-empty-msg').hidden = filtered.length > 0;
    $('table-empty-msg').querySelector('strong').textContent = fruits.length ? 'Không tìm thấy kết quả' : 'Chưa có kết quả trong phiên';
    $('table-empty-msg').querySelector('p').textContent = fruits.length ? 'Thử mã quả khác hoặc chọn “Tất cả”.' : 'Kết quả sẽ hiển thị khi máy chủ ghi nhận quả mới.';
    setText('table-result-count', filtered.length + ' / ' + fruits.length + ' kết quả');
    filtered.slice().reverse().forEach(fruit => {
      const row = document.createElement('tr');
      const values = ['#' + fruit.id, null, null, (fruit.confidence * 100).toFixed(1) + '%', time(fruit.timestamp) + ' · ' + date(fruit.timestamp), fruit.inferenceMs.toFixed(1) + ' ms', fruit.label === 'MOCK' ? 'Không điều khiển' : fruit.servoAction, decisionText(fruit)];
      values.forEach((value, index) => {
        const cell = document.createElement('td');
        if (index === 1) {
          appendSnapshotImage(cell, fruit, 'table-thumb', 'Quả ' + fruit.id);
        } else if (index === 2) cell.append(badge(fruit));
        else cell.textContent = value;
        row.append(cell);
      });
      body.append(row);
    });
  }
  function switchTab(tab) {
    if (tab === 'tab-admin' && !isAdmin()) return;
    state.activeTab = tab;
    document.querySelectorAll('.nav-btn').forEach(button => {
      const active = button.dataset.tab === tab; button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    document.querySelectorAll('.view-panel').forEach(panel => { panel.hidden = panel.id !== tab; panel.classList.toggle('active', panel.id === tab); });
    const history = tab === 'tab-history'; const admin = tab === 'tab-admin';
    setText('page-title', admin ? 'Quản trị hệ thống' : history ? 'Lịch sử phiên' : 'Tổng quan phân loại');
    setText('page-breadcrumb', admin ? 'Quản trị' : history ? 'Lịch sử phiên' : 'Tổng quan');
    setText('page-subtitle', admin ? 'Quản lý quyền truy cập và theo dõi hoạt động của trạm.' : history ? 'Tra cứu từng kết quả và xuất báo cáo theo phiên.' : 'Một góc nhìn rõ ràng cho từng phiên vận hành.');
    $('header-controls').hidden = admin; $('source-notice').hidden = admin;
    $('session-permission-note').hidden = admin;
    if (admin) adminConsole.show(); else if (history) renderHistory(); else renderLive();
  }
  function updateClock() {
    setText('live-clock', time(Date.now()));
    setText('today-date', new Date().toLocaleDateString('vi-VN', { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' }));
    const session = state.currentSession;
    setText('live-session-uptime', session ? duration(session.startTime, session.endTime || Date.now()) : '00:00:00');
    if (session) {
      const minutes = Math.max(0.5, (new Date(session.endTime || Date.now()) - new Date(session.startTime)) / 60000);
      $('live-ppm-rate').firstChild.textContent = (session.fruits.length / minutes).toFixed(1) + ' ';
    }
  }
  async function mutateSession(kind, target = null) {
    if (state.mode !== 'live' || !isAdmin() || state.creating || kind !== 'end' || state.currentSession?.automatic) return;
    state.creating = true; const revision = state.revision;
    const operationToken = Symbol(); state.operationToken = operationToken;
    if (!state.sessionAction || state.sessionAction.kind !== kind || state.sessionAction.target !== target) state.sessionAction = { kind, target, key: crypto.randomUUID() };
    renderSource();
    try {
      const session = await request('/api/sessions/' + encodeURIComponent(target) + '/end', {
        method: 'POST', timeoutMs: 70000, headers: { 'Idempotency-Key': state.sessionAction.key }
      });
      if (revision !== state.revision) return;
      state.sessionAction = null; state.selectedHistorySessionId = session.id; state.selectedFruitId = null;
      state.revision++; state.busy = false; const refreshedRevision = state.revision;
      await syncServer();
      if (refreshedRevision === state.revision) showToast('Đã đóng phiên cũ. Lượt chạy tiếp theo sẽ tự tạo phiên mới.');
    } catch (error) {
      if (revision !== state.revision || error.status === 401) return;
      if (error.status === 409) state.sessionAction = null;
      showToast(error.detail === 'SESSION_ALREADY_RUNNING' ? 'Đã có phiên đang chạy. Hãy kết thúc phiên đó trước.' : error.status === 403 ? 'Tài khoản không được phép vận hành phiên.' : 'Chưa xác nhận được thao tác. Làm mới dữ liệu trước khi thử lại.', 'error');
      await syncServer();
    } finally { if (state.operationToken === operationToken) { state.creating = false; state.operationToken = null; renderSource(); } }
  }
  function simulate() { syncServer(); }
  function csvCell(value) {
    let text = String(value ?? '');
    if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  }
  function exportCsv() {
    const session = selectedSession();
    if (!session?.fruits.length) return;
    const header = ['STT', 'Mã quả', 'Phân loại AI', 'Độ tin cậy (%)', 'Thời điểm', 'Độ trễ (ms)', 'Hướng dự kiến', 'Lý do', 'Nguồn'];
    const rows = session.fruits.map((f, index) => [index + 1, f.id, f.label, (f.confidence * 100).toFixed(2), time(f.timestamp) + ' ' + date(f.timestamp), f.inferenceMs, f.label === 'MOCK' ? 'Không điều khiển' : f.servoAction, decisionText(f), 'Máy chủ AI']);
    const blob = new Blob(['\uFEFF' + [header, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'AutoSort_' + session.id.replace(/[^a-z0-9_-]/gi, '_') + '.csv'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); showToast('Đã xuất CSV của ' + session.name);
  }
  async function request(path, options = {}) {
    const revision = state.revision, userId = state.user?.id;
    const { timeoutMs = 10000, ...fetchOptions } = options;
    const response = await fetch(state.apiBase + path, { cache: 'no-store', credentials: 'include', signal: AbortSignal.timeout(timeoutMs), ...fetchOptions,
      headers: { ...(fetchOptions.method === 'POST' ? { 'Content-Type': 'application/json', 'X-CSRF-Token': state.user?.csrfToken || '' } : {}), ...fetchOptions.headers } });
    if (!response.ok) {
      const error = new Error('HTTP ' + response.status); error.status = response.status;
      try { const body = await response.json(); error.detail = typeof body.detail === 'string' ? body.detail : ''; } catch { /* A proxy error may not return JSON. */ }
      if (error.status === 401 && path !== '/api/auth/login' && userId && revision === state.revision && userId === state.user?.id) loginExpired();
      throw error;
    }
    return response.json();
  }
  function clearLiveData() {
    failedImageSources.clear(); state.sessions=[]; state.currentSession=null; state.station=null;
    state.lastSync=null; state.cloudOnline=false;
  }
  function loginExpired() {
    clearLiveData(); document.body.classList.add('auth-pending'); location.replace('login.html');
  }
  async function accountAction() {
    try { await request('/api/auth/logout', {method:'POST'}); loginExpired(); }
    catch {showToast('Chưa đăng xuất được. Kiểm tra mạng rồi thử lại.', 'error');}
  }
  function normalizeSession(raw) {
    if (!raw || typeof raw.id !== 'string' || !Array.isArray(raw.fruits) || !Number.isFinite(Date.parse(raw.startTime))) throw new Error('Invalid session');
    return {
      ...raw, name: typeof raw.name === 'string' ? raw.name.replace(/Phiên quất/gi, 'Phiên') : raw.id,
      fruits: raw.fruits.filter(f => f && typeof f.id === 'string' && Number.isFinite(Date.parse(f.timestamp))).map(f => ({
        ...f, label: Object.hasOwn(LABEL_NAMES, f.label) ? f.label : 'MOCK',
        confidence: Number.isFinite(f.confidence) ? Math.min(1, Math.max(0, f.confidence)) : 0,
        inferenceMs: Number.isFinite(f.inferenceMs) ? Math.max(0, f.inferenceMs) : 0,
        image: typeof f.image === 'string' ? f.image : '', servoAction: typeof f.servoAction === 'string' ? f.servoAction : '—'
      }))
    };
  }
  async function syncServer() {
    if(!mayOperate()||state.busy)return;
    state.busy = true; const revision = state.revision; const start = performance.now();
    renderSource();
    try {
      const user = await request('/api/auth/me');
      if (revision !== state.revision) return;
      updateIdentity(user);
      const [health, current, summaries, station] = await Promise.all([request('/health'), request('/api/session/current'), request('/api/sessions'), request('/api/station')]);
      state.station=station;
      if (!Array.isArray(summaries)) throw new Error('Invalid history');
      const currentSession = current ? normalizeSession(current) : null;
      const previous = await Promise.all(summaries.filter(s => s.id !== currentSession?.id).map(s => request('/api/sessions/' + encodeURIComponent(s.id)).then(normalizeSession)));
      if (revision !== state.revision) return;
      state.currentSession = currentSession; state.sessions = currentSession ? [...previous, currentSession] : previous; state.cloudOnline = true;
      state.health = { ...health, latency: Math.round(performance.now() - start) };
      state.threshold = Number.isFinite(health.threshold) && health.model_ready ? Math.min(1, Math.max(0, health.threshold)) : 0.70;
      state.lastSync = Date.now();
      if (!state.sessions.some(s => s.id === state.selectedHistorySessionId)) state.selectedHistorySessionId = currentSession?.id || previous.at(-1)?.id || null;
      renderLive(); if (state.activeTab === 'tab-history') renderHistory();
    } catch (error) {
      if (revision !== state.revision) return;
      if (error.status === 401) { loginExpired(); return; }
      state.cloudOnline = false; state.station=null;
    } finally {
      if (revision === state.revision) { state.busy = false; renderSource(); }
    }
  }

  let commandBusy=false, commandAttempt=null;
  function renderStation() {
    const st=state.station, pending=st?.pending;
    const ready=mayOperate()&&state.cloudOnline&&st?.online&&!pending&&!commandBusy;
    $('btn-start').textContent=st?.state==='PAUSED'?'Tiếp tục':'Bắt đầu';
    $('btn-start').disabled=!ready||!state.health?.model_ready||!['IDLE','PAUSED'].includes(st?.state)||(st?.state==='IDLE'&&state.currentSession?.status==='RUNNING');
    $('btn-pause').disabled=!ready||st?.state!=='RUNNING';
    $('btn-stop').disabled=!mayOperate()||!state.cloudOnline||!st?.online||commandBusy||pending?.action==='STOP'||(!pending&&!['RUNNING','PAUSED'].includes(st?.state));
    const labels={IDLE:'Trạm sẵn sàng · Đang dừng',RUNNING:'Băng chuyền đang vận hành',PAUSED:'Đã tạm dừng · Giữ nguyên phiên',FAULT:'Trạm đang khóa lỗi · Kiểm tra tại trạm và kết nối lại',OFFLINE:'Trạm chưa kết nối · Chạy bridge trên máy tính tại trạm'};
    const text=pending?'Đang chờ ESP32 xác nhận '+({START:'bắt đầu',RESUME:'tiếp tục',PAUSE:'tạm dừng',STOP:'kết thúc'})[pending.action]+'…':!st?.online?'Trạm chưa kết nối · Chạy bridge trên máy tính tại trạm':labels[st.state];
    if(state.currentSession?.status==='RUNNING') {
      const tag=$('session-status-tag');
      const dot=document.createElement('span');dot.className='pip '+(st?.state==='PAUSED'?'paused':st?.online?'online':'offline');dot.setAttribute('aria-hidden','true');
      tag.replaceChildren(dot,document.createTextNode(st?.state==='PAUSED'?'Tạm dừng':st?.online?'Đang vận hành':'Mất kết nối'));
    }
    if($('station-status').textContent!==text)$('station-status').textContent=text;
    if(st?.lastCommand?.status==='FAILED'&&!pending)$('station-status').textContent+=' · Lệnh chưa hoàn tất. Kiểm tra trạm trước khi thử lại.';
  }
  async function sendControl(action) {
    if(commandBusy||!state.station?.online||(state.station.pending&&action!=='STOP'))return;
    if(!commandAttempt||commandAttempt.action!==action||commandAttempt.revision!==state.station.revision)
      commandAttempt={action,revision:state.station.revision,key:crypto.randomUUID()};
    commandBusy=true;renderStation();
    try {
      const command=await request('/api/station/commands',{method:'POST',headers:{'Idempotency-Key':commandAttempt.key},body:JSON.stringify({action,revision:commandAttempt.revision})});
      commandAttempt=null;
      showToast(command.status==='FAILED'?'Lệnh không còn hiệu lực. Trạng thái trạm đang được cập nhật.':command.status==='SUCCEEDED'?'Lệnh này đã được xác nhận.':'Đã gửi lệnh. Đang chờ xác nhận từ trạm.',command.status==='FAILED'?'error':'info');
    } catch(error) {
      if(error.status===409)commandAttempt=null;
      showToast(error.status===403?'Tài khoản không có quyền điều khiển.':'Chưa xác nhận được lệnh. Đang cập nhật trạng thái trạm.','error');
    } finally {commandBusy=false;await syncServer();renderStation();}
  }

  function showToast(message, type = 'info') {
    const toast = document.createElement('div'); toast.className = 'toast toast-' + type; toast.textContent = message;
    $('toast-container').append(toast); setTimeout(() => toast.remove(), 4500);
  }
  function init() {
    adminConsole = createAdminConsole({ request, getUser: () => state.user, onSessionLost: loginExpired, toast: showToast });
    adminConsole.identityChanged(null);
    document.querySelectorAll('.nav-btn').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
    $('btn-sim-trigger').addEventListener('click', simulate);
    $('btn-start').addEventListener('click',()=>sendControl(state.station?.state==='PAUSED'?'RESUME':'START'));
    $('btn-pause').addEventListener('click',()=>sendControl('PAUSE'));
    $('btn-stop').addEventListener('click',()=>sendControl('STOP'));
    $('btn-end-session').addEventListener('click', () => { if (!isAdmin() || state.mode !== 'live' || state.currentSession?.automatic || state.currentSession?.status !== 'RUNNING') return; state.endTarget = state.currentSession.id; setText('end-session-target', state.currentSession.name); $('end-session-dialog').returnValue = ''; $('end-session-dialog').showModal(); });
    $('end-session-dialog').addEventListener('close', () => { if ($('end-session-dialog').returnValue === 'confirm') mutateSession('end', state.endTarget); });
    $('btn-guide').addEventListener('click', () => $('guide-dialog').showModal());
    $('btn-account').addEventListener('click', accountAction);
    $('btn-password').addEventListener('click', () => adminConsole.openPassword());
    $('btn-view-history').addEventListener('click', () => { switchTab('tab-history'); $('tab-history-btn').focus(); });
    $('btn-refresh-history').addEventListener('click', async () => {
      await syncServer();
      renderHistory();
      showToast(state.mode === 'live' && !state.cloudOnline ? 'Chưa kết nối được máy chủ. Kiểm tra dịch vụ AI.' : 'Đã làm mới dữ liệu phiên', state.mode === 'live' && !state.cloudOnline ? 'error' : 'info');
    });
    $('btn-export-csv').addEventListener('click', exportCsv);
    $('session-dropdown').addEventListener('change', event => { state.selectedHistorySessionId = event.target.value; renderHistory(); });
    $('table-search-input').addEventListener('input', event => { state.search = event.target.value.trim().toLowerCase(); renderTable(); });
    document.querySelectorAll('.segment-btn').forEach(button => button.addEventListener('click', () => {
      state.filter = button.dataset.filter;
      document.querySelectorAll('.segment-btn').forEach(item => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); }); renderTable();
    }));
    $('latest-fruit-img').addEventListener('error', () => {
      const image = $('latest-fruit-img');
      const src = image.getAttribute('src');
      if (!src) return;
      failedImageSources.add(src); image.hidden = true; image.removeAttribute('src');
      $('camera-empty').hidden = false;
      $('camera-empty').querySelector('strong').textContent = 'Không tải được ảnh';
      $('camera-empty').querySelector('span').textContent = 'Thông tin phân loại vẫn được giữ. Chọn một quả khác để xem ảnh.';
    });
    request('/api/auth/me').then(user => {
      updateIdentity(user); document.body.classList.remove('auth-pending');
      renderSource(); syncServer();
    }).catch(error => {
      if(error.status===401) loginExpired();
      else {document.body.classList.add('auth-pending');location.replace('login.html');}
    });
    setInterval(updateClock,1000); setInterval(syncServer,5000);
    setInterval(()=>{if(state.user&&!document.hidden)request('/api/station').then(st=>{state.station=st;renderStation();}).catch(()=>{state.station=null;renderStation();});},1000);
    window.addEventListener('pageshow',event=>{if(event.persisted){document.body.classList.add('auth-pending');clearLiveData();request('/api/auth/me').then(user=>{updateIdentity(user);document.body.classList.remove('auth-pending');syncServer();}).catch(loginExpired);}});

  }
  init();
})();
