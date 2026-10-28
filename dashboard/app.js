/**
 * AutoSort monitoring. Demo records stay in this browser.
 * People use HttpOnly cookie sessions; device keys never enter this client.
 */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const DEMO_KEY = 'autosort_demo_sessions_v2';
  const SAMPLE_IMAGES = {
    GREEN: ['samples/green_1.jpg', 'samples/green_2.jpg', 'samples/green_3.jpg'],
    RIPE: ['samples/ripe_1.jpg', 'samples/ripe_2.jpg', 'samples/ripe_3.jpg'],
    REJECT: ['samples/reject_1.jpg', 'samples/reject_2.jpg', 'samples/reject_3.jpg']
  };
  const LABEL_NAMES = { GREEN: 'Quất xanh', RIPE: 'Quất chín', REJECT: 'Cần loại', MOCK: 'Chưa phân loại' };
  const LABEL_COLORS = { GREEN: '#27815d', RIPE: '#c17b23', REJECT: '#c65b54', MOCK: '#8b99a5' };
  const state = {
    mode: 'demo', activeTab: 'tab-live', sessions: [], currentSession: null,
    selectedHistorySessionId: null, selectedFruitId: null, filter: 'ALL', search: '',
    cloudOnline: false, health: null, busy: false, revision: 0,
    threshold: 0.70, lastSync: null, user: null, creating: false,
    apiBase: location.pathname.startsWith('/dashboard') || location.port === '8000' ? '' : 'http://127.0.0.1:8000'
  };
  let demoSessions = [];
  let storageWarningShown = false;

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
    if (/^data:image\/(jpeg|png|webp);base64,[a-z\d+/=]+$/i.test(value)) return value;
    try {
      const url = new URL(value, location.href);
      return ['http:', 'https:', 'file:'].includes(url.protocol) && url.origin === location.origin ? url.href : '';
    } catch { return ''; }
  }
  function saveDemo() {
    try { localStorage.setItem(DEMO_KEY, JSON.stringify(demoSessions)); }
    catch {
      if (!storageWarningShown) showToast('Không lưu được trên trình duyệt. Dữ liệu phiên này chỉ giữ khi trang còn mở.', 'error');
      storageWarningShown = true;
    }
  }
  function loadDemo() {
    try {
      const saved = JSON.parse(localStorage.getItem(DEMO_KEY));
      if (Array.isArray(saved) && saved.length && saved.every(s => s && typeof s.id === 'string' && typeof s.name === 'string' && Number.isFinite(Date.parse(s.startTime)) && Array.isArray(s.fruits))) {
        demoSessions = saved.map(normalizeSession);
      }
    } catch { /* An unavailable or invalid local store does not block the UI. */ }
    if (!demoSessions.length) {
      const now = Date.now();
      const day = new Date().toISOString().slice(0, 10).replaceAll('-', '');
      demoSessions = [48, 32].map((count, index) => {
        const start = now - (index === 0 ? 4 * 3600000 : 25 * 60000);
        const session = {
          id: 'DEMO-' + day + '-' + (index + 1), name: 'Phiên quất 0' + (index + 1),
          startTime: new Date(start).toISOString(),
          endTime: index === 0 ? new Date(start + 45 * 60000).toISOString() : null,
          status: index === 0 ? 'COMPLETED' : 'RUNNING', fruits: []
        };
        session.fruits = Array.from({ length: count }, (_, i) => makeDemoFruit(session, i + 1, start + (i + 1) * 21000));
        return session;
      });
      saveDemo();
    }
    state.sessions = demoSessions;
    state.currentSession = demoSessions.at(-1);
    state.selectedHistorySessionId = state.currentSession.id;
  }
  function makeDemoFruit(session, index, timestamp = Date.now()) {
    // Stable sample distribution makes screenshots and demonstrations repeatable.
    const label = ['RIPE', 'GREEN', 'RIPE', 'GREEN', 'RIPE', 'REJECT'][index % 6];
    const confidence = label === 'REJECT' ? 0.54 + (index % 12) / 100 : 0.92 + (index % 7) / 100;
    return {
      id: 'F' + String(index).padStart(4, '0'), sessionId: session.id, label, confidence,
      timestamp: new Date(timestamp).toISOString(), inferenceMs: Number((15.2 + (index % 6) * 0.7).toFixed(1)),
      image: SAMPLE_IMAGES[label][index % 3],
      decisionReason: label === 'REJECT' ? 'LOW_CONFIDENCE' : 'CLASSIFIED',
      servoAction: label === 'GREEN' ? 'Cổng 1 · Khay xanh' : label === 'RIPE' ? 'Cổng 2 · Khay chín' : 'Cuối băng · Khay loại'
    };
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
    const demo = state.mode === 'demo';
    const notice = $('source-notice');
    notice.dataset.source = state.mode;
    notice.setAttribute('aria-busy', String(!demo && state.busy));
    setText('source-notice-text', demo
      ? 'Chế độ mô phỏng · Ảnh và số liệu mẫu để trải nghiệm giao diện.'
      : state.busy && !state.lastSync ? 'Đang kết nối máy chủ AI và tải phiên phân loại…'
      : state.cloudOnline
        ? state.health?.model_ready ? 'Đang nhận dữ liệu máy chủ · Tự cập nhật mỗi 5 giây.' : 'Đã kết nối máy chủ · Mô hình chưa sẵn sàng. Kết quả MOCK chưa được phân loại.'
        : state.lastSync ? 'Mất kết nối máy chủ · Đang hiển thị dữ liệu lần đồng bộ cuối. Kiểm tra dịch vụ AI.' : 'Chưa kết nối máy chủ AI. Chạy dịch vụ rồi nhấn “Thử kết nối lại”.');
    setText('source-state', demo ? 'Demo' : state.busy && !state.lastSync ? 'Đang kết nối' : state.cloudOnline ? 'Đã kết nối' : 'Chưa kết nối');
    const pip = $('cloud-status-pill').querySelector('.pip');
    pip.className = 'pip ' + (state.cloudOnline ? 'online' : 'offline');
    setText('cloud-latency', demo ? 'Chế độ demo' : state.cloudOnline ? state.health?.latency + ' ms' : 'Ngoại tuyến');
    setText('model-ver', demo ? 'Dữ liệu mẫu' : state.health?.model_version || 'Chưa xác định');
    setText('footer-source', demo ? 'Dữ liệu mô phỏng' : state.lastSync ? 'Đồng bộ lúc ' + time(state.lastSync) : 'Chưa đồng bộ');
    setText('camera-fps', demo ? 'Ảnh mô phỏng' : 'Ảnh từ máy chủ');
    setText('image-source-label', demo ? 'Ảnh mẫu' : 'Ảnh ghi nhận');
    $('btn-sim-trigger').disabled = !demo && (state.cloudOnline || state.busy);
    $('btn-sim-trigger').innerHTML = demo ? '<svg class="icon" aria-hidden="true"><use href="#i-play"/></svg>Mô phỏng một quả' : '<svg class="icon" aria-hidden="true"><use href="#i-refresh"/></svg>' + (state.busy && !state.lastSync ? 'Đang kết nối…' : state.cloudOnline ? 'Đang tự cập nhật' : 'Thử kết nối lại');
    $('btn-new-session').disabled = state.creating || (!demo && (state.user?.role !== 'admin' || !state.cloudOnline || state.busy));
    $('btn-new-session').title = demo ? 'Tạo phiên mô phỏng mới' : state.user?.role === 'admin' ? 'Bắt đầu phiên mới trên máy chủ' : 'Chỉ quản trị viên có quyền tạo phiên thực tế';
    setText('account-name', state.user?.username || 'Khách tham quan');
    setText('account-role', state.user ? state.user.role === 'admin' ? 'Quản trị viên' : 'Người xem' : 'Dữ liệu mô phỏng');
    setText('btn-account', state.user ? 'Đăng xuất' : 'Đăng nhập máy chủ');
    const percent = Math.round(state.threshold * 100);
    $('confidence-threshold').style.left = percent + '%';
    $('confidence-threshold').title = 'Ngưỡng phân loại ' + percent + '%';
    setText('threshold-label', 'Ngưỡng đạt ' + percent + '%');
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
    const dot = document.createElement('span'); dot.className = 'pip ' + (session && (state.mode === 'demo' || state.cloudOnline) ? 'online' : 'offline'); dot.setAttribute('aria-hidden', 'true');
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
    const note = summary.counts.MOCK ? summary.counts.MOCK + ' kết quả MOCK chưa được phân loại. Tỉ lệ đạt chỉ tính trên quả đã phân loại.' : 'Quả dưới ngưỡng tin cậy được xếp vào khay loại để kiểm tra lại.';
    document.querySelector('.quality-note p').textContent = note;
    drawDonut(summary);
    renderRecent(session?.fruits || []);
    updateClock();
  }
  function renderInspection(fruit) {
    const image = $('latest-fruit-img');
    const src = safeImage(fruit?.image);
    // The API may return a sample placeholder for an unavailable snapshot.
    const hasImage = Boolean(src) && (state.mode === 'demo' || !fruit.image.startsWith('samples/'));
    image.hidden = !hasImage;
    if (hasImage) { image.src = src; image.alt = LABEL_NAMES[fruit.label] + ', mã quả ' + fruit.id; }
    else image.removeAttribute('src');
    $('camera-empty').hidden = hasImage;
    $('camera-empty').querySelector('strong').textContent = fruit ? 'Chưa có ảnh ghi nhận' : 'Chờ ảnh đầu tiên';
    $('camera-empty').querySelector('span').textContent = fruit ? 'Máy chủ đã gửi kết quả nhưng chưa có ảnh chụp kèm theo.' : state.mode === 'demo' ? 'Nhấn “Mô phỏng một quả” để bắt đầu.' : 'Kết quả sẽ xuất hiện khi phiên có dữ liệu.';
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
    setText('inspection-caption', fruit ? (state.mode === 'demo' ? 'Mô phỏng' : 'Ghi nhận') + ' · #' + fruit.id + ' · ' + (LABEL_NAMES[fruit.label] || 'Chưa phân loại') : 'Chưa có kết quả trong phiên');
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
      const src = safeImage(fruit.image);
      if (src && (state.mode === 'demo' || !fruit.image.startsWith('samples/'))) {
        const image = document.createElement('img'); image.className = 'strip-thumb-img'; image.src = src; image.alt = ''; image.loading = 'lazy'; wrap.append(image);
      } else { wrap.classList.add('strip-no-image'); wrap.textContent = 'Chưa có ảnh'; }
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
      option.value = session.id; option.textContent = session.name + ' · ' + date(session.startTime) + ' · ' + session.fruits.length + ' quả';
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
    $('table-empty-msg').querySelector('p').textContent = fruits.length ? 'Thử mã quả khác hoặc chọn “Tất cả”.' : state.mode === 'demo' ? 'Thêm một quả mô phỏng từ trang Tổng quan để bắt đầu.' : 'Kết quả sẽ hiển thị khi máy chủ ghi nhận quả mới.';
    setText('table-result-count', filtered.length + ' / ' + fruits.length + ' kết quả' + (state.mode === 'demo' ? ' · Dữ liệu mô phỏng' : ''));
    filtered.slice().reverse().forEach(fruit => {
      const row = document.createElement('tr');
      const values = ['#' + fruit.id, null, null, (fruit.confidence * 100).toFixed(1) + '%', time(fruit.timestamp) + ' · ' + date(fruit.timestamp), fruit.inferenceMs.toFixed(1) + ' ms', fruit.label === 'MOCK' ? 'Không điều khiển' : fruit.servoAction, decisionText(fruit)];
      values.forEach((value, index) => {
        const cell = document.createElement('td');
        if (index === 1) {
          const src = safeImage(fruit.image);
          if (src && (state.mode === 'demo' || !fruit.image.startsWith('samples/'))) { const image = document.createElement('img'); image.src = src; image.alt = 'Quả ' + fruit.id; image.className = 'table-thumb'; image.loading = 'lazy'; cell.append(image); }
          else cell.textContent = '—';
        } else if (index === 2) cell.append(badge(fruit));
        else cell.textContent = value;
        row.append(cell);
      });
      body.append(row);
    });
  }
  function switchTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll('.nav-btn').forEach(button => {
      const active = button.dataset.tab === tab; button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    document.querySelectorAll('.view-panel').forEach(panel => { panel.hidden = panel.id !== tab; panel.classList.toggle('active', panel.id === tab); });
    const history = tab === 'tab-history';
    setText('page-title', history ? 'Lịch sử phiên' : 'Tổng quan phân loại');
    setText('page-breadcrumb', history ? 'Lịch sử phiên' : 'Tổng quan');
    setText('page-subtitle', history ? 'Tra cứu từng kết quả và xuất báo cáo theo phiên.' : 'Một góc nhìn rõ ràng cho từng phiên vận hành.');
    if (history) renderHistory(); else renderLive();
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
  async function createSession() {
    if (state.mode !== 'demo') {
      if (state.creating) return;
      state.creating = true; renderSource();
      try {
        const session = await request('/api/sessions/new', { method: 'POST' });
        state.selectedHistorySessionId = session.id; state.selectedFruitId = null; await syncServer();
        showToast('Đã tạo phiên mới trên máy chủ.');
      } catch (error) { showToast(error.status === 403 ? 'Tài khoản không có quyền tạo phiên hoặc phiên đăng nhập đã thay đổi.' : 'Không tạo được phiên. Hãy kiểm tra kết nối rồi tải lại dữ liệu.', 'error'); }
      finally { state.creating = false; renderSource(); }
      return;
    }
    const now = new Date();
    if (state.currentSession) { state.currentSession.endTime = now.toISOString(); state.currentSession.status = 'COMPLETED'; }
    const session = { id: 'DEMO-' + now.getTime(), name: 'Phiên quất ' + String(demoSessions.length + 1).padStart(2, '0'), startTime: now.toISOString(), endTime: null, status: 'RUNNING', fruits: [] };
    demoSessions.push(session); state.sessions = demoSessions; state.currentSession = session; state.selectedHistorySessionId = session.id; state.selectedFruitId = null;
    saveDemo(); renderLive(); renderHistory(); showToast('Đã tạo ' + session.name + '. Dữ liệu cũ được giữ trong lịch sử.');
  }
  function simulate() {
    if (state.mode !== 'demo') { syncServer(); return; }
    state.currentSession.fruits.push(makeDemoFruit(state.currentSession, state.currentSession.fruits.length + 1));
    state.selectedFruitId = null; saveDemo(); renderLive(); renderHistory();
    const fruit = state.currentSession.fruits.at(-1); showToast('Đã mô phỏng #' + fruit.id + ' · ' + LABEL_NAMES[fruit.label]);
  }
  function csvCell(value) {
    let text = String(value ?? '');
    if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  }
  function exportCsv() {
    const session = selectedSession();
    if (!session?.fruits.length) return;
    const header = ['STT', 'Mã quả', 'Phân loại AI', 'Độ tin cậy (%)', 'Thời điểm', 'Độ trễ (ms)', 'Hướng dự kiến', 'Lý do', 'Nguồn'];
    const rows = session.fruits.map((f, index) => [index + 1, f.id, f.label, (f.confidence * 100).toFixed(2), time(f.timestamp) + ' ' + date(f.timestamp), f.inferenceMs, f.label === 'MOCK' ? 'Không điều khiển' : f.servoAction, decisionText(f), state.mode === 'demo' ? 'Mô phỏng' : 'Máy chủ AI']);
    const blob = new Blob(['\uFEFF' + [header, ...rows].map(row => row.map(csvCell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'AutoSort_' + session.id.replace(/[^a-z0-9_-]/gi, '_') + '.csv'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); showToast('Đã xuất CSV của ' + session.name);
  }
  async function request(path, options = {}) {
    const response = await fetch(state.apiBase + path, { cache: 'no-store', credentials: 'include', signal: AbortSignal.timeout(10000), ...options,
      headers: { ...(options.method === 'POST' ? { 'Content-Type': 'application/json', 'X-CSRF-Token': state.user?.csrfToken || '' } : {}), ...options.headers } });
    if (!response.ok) { const error = new Error('HTTP ' + response.status); error.status = response.status; throw error; }
    return response.json();
  }
  function openLogin() {
    $('login-error').hidden = true;
    if (!$('login-dialog').open) $('login-dialog').showModal();
  }
  function clearLiveData() {
    state.sessions = []; state.currentSession = null; state.selectedHistorySessionId = null;
    state.selectedFruitId = null; state.lastSync = null; state.health = null; state.cloudOnline = false;
  }
  function loginExpired() {
    state.user = null; state.revision++; state.busy = false; clearLiveData();
    renderSource(); renderLive(); renderHistory(); openLogin();
  }
  async function submitLogin(event) {
    event.preventDefault(); $('btn-login-submit').disabled = true; $('btn-login-demo').disabled = true; $('login-error').hidden = true;
    try {
      state.user = await request('/api/auth/login', { method: 'POST', body: JSON.stringify({ username: $('login-username').value.trim(), password: $('login-password').value }) });
      $('login-dialog').close(); $('data-source').value = 'live'; changeMode();
      showToast('Đã đăng nhập. Đang tải dữ liệu máy chủ.');
    } catch (error) {
      $('login-error').textContent = error.status === 401 ? 'Tên đăng nhập hoặc mật khẩu không đúng.' : error.status === 429 ? 'Bạn đã thử quá nhiều lần. Vui lòng đợi 15 phút.' : 'Chưa đăng nhập được. Kiểm tra máy chủ và cấu hình kết nối.';
      $('login-error').hidden = false;
    } finally { $('login-password').value = ''; $('btn-login-submit').disabled = false; $('btn-login-demo').disabled = false; }
  }
  async function accountAction() {
    if (!state.user) { openLogin(); return; }
    $('btn-account').disabled = true;
    try {
      await request('/api/auth/logout', { method: 'POST' });
      state.user = null; $('data-source').value = 'demo'; changeMode(); showToast('Đã đăng xuất khỏi máy chủ.');
    } catch (error) {
      if (error.status === 401) loginExpired();
      else showToast('Chưa đăng xuất được. Hãy kiểm tra kết nối và thử lại.', 'error');
    } finally { $('btn-account').disabled = false; }
  }
  function normalizeSession(raw) {
    if (!raw || typeof raw.id !== 'string' || !Array.isArray(raw.fruits) || !Number.isFinite(Date.parse(raw.startTime))) throw new Error('Invalid session');
    return {
      ...raw, name: typeof raw.name === 'string' ? raw.name : raw.id,
      fruits: raw.fruits.filter(f => f && typeof f.id === 'string' && Number.isFinite(Date.parse(f.timestamp))).map(f => ({
        ...f, label: Object.hasOwn(LABEL_NAMES, f.label) ? f.label : 'MOCK',
        confidence: Number.isFinite(f.confidence) ? Math.min(1, Math.max(0, f.confidence)) : 0,
        inferenceMs: Number.isFinite(f.inferenceMs) ? Math.max(0, f.inferenceMs) : 0,
        image: typeof f.image === 'string' ? f.image : '', servoAction: typeof f.servoAction === 'string' ? f.servoAction : '—'
      }))
    };
  }
  async function syncServer() {
    if (state.mode !== 'live' || state.busy || ($('login-dialog').open && !state.user)) return;
    state.busy = true; const revision = state.revision; const start = performance.now();
    renderSource();
    try {
      const user = await request('/api/auth/me');
      if (revision !== state.revision) return;
      state.user = user;
      const [health, current, summaries] = await Promise.all([request('/health'), request('/api/session/current'), request('/api/sessions')]);
      if (!Array.isArray(summaries)) throw new Error('Invalid history');
      const currentSession = normalizeSession(current);
      const previous = await Promise.all(summaries.filter(s => s.id !== currentSession.id).map(s => request('/api/sessions/' + encodeURIComponent(s.id)).then(normalizeSession)));
      if (revision !== state.revision) return;
      state.currentSession = currentSession; state.sessions = [...previous, currentSession]; state.cloudOnline = true;
      state.health = { ...health, latency: Math.round(performance.now() - start) };
      state.threshold = Number.isFinite(health.threshold) && health.model_ready ? Math.min(1, Math.max(0, health.threshold)) : 0.70;
      state.lastSync = Date.now();
      if (!state.sessions.some(s => s.id === state.selectedHistorySessionId)) state.selectedHistorySessionId = currentSession.id;
      renderLive(); if (state.activeTab === 'tab-history') renderHistory();
    } catch (error) {
      if (revision !== state.revision) return;
      if (error.status === 401) { loginExpired(); return; }
      state.cloudOnline = false;
    } finally {
      if (revision === state.revision) { state.busy = false; renderSource(); }
    }
  }
  function changeMode() {
    state.revision++; state.busy = false; state.mode = $('data-source').value;
    state.selectedFruitId = null; state.cloudOnline = false; state.lastSync = null; state.health = null; state.threshold = 0.70;
    state.filter = 'ALL'; state.search = ''; $('table-search-input').value = '';
    document.querySelectorAll('.segment-btn').forEach(button => { const active = button.dataset.filter === 'ALL'; button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active)); });
    if (state.mode === 'demo') loadDemo(); else { state.sessions = []; state.currentSession = null; state.selectedHistorySessionId = null; syncServer(); }
    renderSource(); renderLive(); renderHistory();
  }
  function showToast(message, type = 'info') {
    const toast = document.createElement('div'); toast.className = 'toast toast-' + type; toast.textContent = message;
    $('toast-container').append(toast); setTimeout(() => toast.remove(), 4500);
  }
  function init() {
    document.querySelectorAll('.nav-btn').forEach(button => button.addEventListener('click', () => switchTab(button.dataset.tab)));
    $('data-source').addEventListener('change', changeMode);
    $('btn-sim-trigger').addEventListener('click', simulate);
    $('btn-new-session').addEventListener('click', () => { setText('session-dialog-title', state.mode === 'demo' ? 'Bắt đầu phiên mô phỏng mới?' : 'Bắt đầu phiên mới trên máy chủ?'); $('session-dialog').returnValue = ''; $('session-dialog').showModal(); });
    $('session-dialog').addEventListener('close', () => { if ($('session-dialog').returnValue === 'confirm') createSession(); });
    $('btn-guide').addEventListener('click', () => $('guide-dialog').showModal());
    $('btn-account').addEventListener('click', accountAction);
    $('login-form').addEventListener('submit', submitLogin);
    const returnToDemo = () => { $('login-password').value = ''; $('data-source').value = 'demo'; changeMode(); };
    $('btn-login-demo').addEventListener('click', () => { $('login-dialog').close(); returnToDemo(); });
    $('login-dialog').addEventListener('cancel', event => { if ($('btn-login-submit').disabled) event.preventDefault(); else returnToDemo(); });
    $('btn-view-history').addEventListener('click', () => { switchTab('tab-history'); $('tab-history-btn').focus(); });
    $('btn-refresh-history').addEventListener('click', async () => {
      if (state.mode === 'live') await syncServer();
      else {
        const selected = state.selectedHistorySessionId;
        loadDemo();
        if (state.sessions.some(session => session.id === selected)) state.selectedHistorySessionId = selected;
        renderLive();
      }
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
    $('latest-fruit-img').addEventListener('error', () => { $('latest-fruit-img').hidden = true; $('camera-empty').hidden = false; $('camera-empty').querySelector('strong').textContent = 'Không tải được ảnh'; $('camera-empty').querySelector('span').textContent = 'Chọn một quả khác hoặc kiểm tra lại nguồn ảnh.'; });
    loadDemo(); renderSource(); renderLive(); renderHistory();
    request('/api/auth/me').then(user => { state.user = user; renderSource(); }).catch(() => {});
    setInterval(updateClock, 1000);
    setInterval(() => { if (!document.hidden) syncServer(); }, 5000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) syncServer(); });
  }
  init();
})();
