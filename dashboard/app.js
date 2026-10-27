/**
 * AutoSort IoT — Dashboard Application Logic
 * Feature: Live Session Monitoring, Donut Chart, Session Archives & CSV Export
 */

(function () {
  'use strict';

  // --- SAMPLE ASSET IMAGES ---
  const SAMPLE_IMAGES = {
    GREEN: [
      'samples/green_1.jpg',
      'samples/green_2.jpg',
      'samples/green_3.jpg'
    ],
    RIPE: [
      'samples/ripe_1.jpg',
      'samples/ripe_2.jpg',
      'samples/ripe_3.jpg'
    ],
    REJECT: [
      'samples/reject_1.jpg',
      'samples/reject_2.jpg',
      'samples/reject_3.jpg'
    ]
  };

  // --- STATE MANAGEMENT ---
  const state = {
    activeTab: 'tab-live',
    currentSession: null,
    sessions: [],
    selectedHistorySessionId: null,
    tableFilter: 'ALL',
    tableSearch: '',
    cloudOnline: false,
    cloudLatency: 18,
    backendApiBase: window.location.origin.includes('8000') ? '' : 'http://127.0.0.1:8000',
    timerInterval: null
  };

  // --- DOM SELECTORS ---
  const DOM = {
    tabs: document.querySelectorAll('.nav-tab-btn'),
    tabContents: document.querySelectorAll('.tab-content'),
    liveClock: document.getElementById('live-clock'),
    cloudStatusPill: document.getElementById('cloud-status-pill'),
    cloudLatency: document.getElementById('cloud-latency'),
    btnSimTrigger: document.getElementById('btn-sim-trigger'),
    btnNewSession: document.getElementById('btn-new-session'),
    btnExportCsv: document.getElementById('btn-export-csv'),
    btnRefreshHistory: document.getElementById('btn-refresh-history'),

    // Live Tab Elements
    liveSessionName: document.getElementById('live-session-name'),
    liveSessionStart: document.getElementById('live-session-start'),
    liveSessionUptime: document.getElementById('live-session-uptime'),
    liveTotalCount: document.getElementById('live-total-count'),
    livePpmRate: document.getElementById('live-ppm-rate'),

    latestFruitImg: document.getElementById('latest-fruit-img'),
    aiOverlayTag: document.getElementById('ai-overlay-tag'),
    overlayLabelBadge: document.getElementById('overlay-label-badge'),
    overlayConfBadge: document.getElementById('overlay-conf-badge'),
    telemetryConf: document.getElementById('telemetry-conf'),
    telemetryConfFill: document.getElementById('telemetry-conf-fill'),
    telemetryFruitId: document.getElementById('telemetry-fruit-id'),
    telemetryTimestamp: document.getElementById('telemetry-timestamp'),
    telemetryLatency: document.getElementById('telemetry-latency'),
    telemetryDecision: document.getElementById('telemetry-decision'),

    currentSessionDonut: document.getElementById('current-session-donut'),
    donutCenterTotal: document.getElementById('donut-center-total'),
    donutSessionTag: document.getElementById('donut-session-tag'),
    donutGreenCount: document.getElementById('donut-green-count'),
    donutGreenPct: document.getElementById('donut-green-pct'),
    donutGreenBar: document.getElementById('donut-green-bar'),
    donutRipeCount: document.getElementById('donut-ripe-count'),
    donutRipePct: document.getElementById('donut-ripe-pct'),
    donutRipeBar: document.getElementById('donut-ripe-bar'),
    donutRejectCount: document.getElementById('donut-reject-count'),
    donutRejectPct: document.getElementById('donut-reject-pct'),
    donutRejectBar: document.getElementById('donut-reject-bar'),
    sessionAvgPpm: document.getElementById('session-avg-ppm'),
    sessionAvgLatency: document.getElementById('session-avg-latency'),
    sessionPassRate: document.getElementById('session-pass-rate'),

    recentFruitsStrip: document.getElementById('recent-fruits-strip'),

    // History Tab Elements
    sessionDropdown: document.getElementById('session-dropdown'),
    historyTableTitle: document.getElementById('history-table-title'),
    kpiTotalVal: document.getElementById('kpi-total-val'),
    kpiGreenVal: document.getElementById('kpi-green-val'),
    kpiGreenSub: document.getElementById('kpi-green-sub'),
    kpiRipeVal: document.getElementById('kpi-ripe-val'),
    kpiRipeSub: document.getElementById('kpi-ripe-sub'),
    kpiRejectVal: document.getElementById('kpi-reject-val'),
    kpiRejectSub: document.getElementById('kpi-reject-sub'),
    tableSearchInput: document.getElementById('table-search-input'),
    tableFilterPills: document.getElementById('table-filter-pills'),
    fruitsTableBody: document.getElementById('fruits-table-body'),
    tableEmptyMsg: document.getElementById('table-empty-msg'),

    toastContainer: document.getElementById('toast-container')
  };

  // --- INITIALIZATION ---
  function init() {
    setupEventListeners();
    loadStoredSessions();
    startClock();
    checkBackendHealth();
    renderLiveView();
    renderHistoryView();
  }

  // --- SESSIONS STORE & SEED DATA ---
  function loadStoredSessions() {
    const saved = localStorage.getItem('autosort_sessions');
    if (saved) {
      try {
        state.sessions = JSON.parse(saved);
      } catch (e) {
        state.sessions = [];
      }
    }

    // If no sessions exist, generate realistic seed demo data
    if (!state.sessions || state.sessions.length === 0) {
      state.sessions = generateInitialSeedSessions();
      saveSessions();
    }

    // Set current active session (last one or new one)
    state.currentSession = state.sessions[state.sessions.length - 1];
    state.selectedHistorySessionId = state.currentSession.id;
  }

  function saveSessions() {
    localStorage.setItem('autosort_sessions', JSON.stringify(state.sessions));
  }

  function generateInitialSeedSessions() {
    const now = new Date();

    // Session 1 (Past completed run)
    const s1Start = new Date(now.getTime() - 4 * 3600000);
    const s1End = new Date(s1Start.getTime() + 42 * 60000);
    const s1Fruits = generateSeedFruits('SES-20261027-01', 45, s1Start);

    // Session 2 (Current active session)
    const s2Start = new Date(now.getTime() - 25 * 60000);
    const s2Fruits = generateSeedFruits('SES-20261027-02', 28, s2Start);

    return [
      {
        id: 'SES-20261027-01',
        name: 'Phiên #01 — ' + formatDateShort(s1Start),
        startTime: s1Start.toISOString(),
        endTime: s1End.toISOString(),
        status: 'COMPLETED',
        fruits: s1Fruits
      },
      {
        id: 'SES-20261027-02',
        name: 'Phiên #02 — ' + formatDateShort(s2Start),
        startTime: s2Start.toISOString(),
        endTime: null,
        status: 'RUNNING',
        fruits: s2Fruits
      }
    ];
  }

  function generateSeedFruits(sessionId, count, startTime) {
    const fruits = [];
    const labels = ['GREEN', 'RIPE', 'RIPE', 'RIPE', 'GREEN', 'REJECT'];
    let curTime = new Date(startTime.getTime());

    for (let i = 1; i <= count; i++) {
      curTime = new Date(curTime.getTime() + (Math.floor(Math.random() * 8) + 3) * 1000);
      const label = labels[Math.floor(Math.random() * labels.length)];
      const conf = label === 'REJECT'
        ? Number((Math.random() * 0.25 + 0.40).toFixed(4))
        : Number((Math.random() * 0.10 + 0.89).toFixed(4));
      const lat = Number((Math.random() * 8 + 14).toFixed(1));
      const imgList = SAMPLE_IMAGES[label];
      const imgSrc = imgList[i % imgList.length];

      fruits.push({
        id: `F${String(i).padStart(4, '0')}`,
        sessionId: sessionId,
        label: label,
        confidence: conf,
        timestamp: curTime.toISOString(),
        inferenceMs: lat,
        image: imgSrc,
        decisionReason: conf >= 0.70 ? 'CLASSIFIED' : 'LOW_CONFIDENCE',
        servoAction: label === 'GREEN' ? 'Gạt Cổng 1 (Green)' : label === 'RIPE' ? 'Gạt Cổng 2 (Ripe)' : 'Trôi Cuối (Reject)'
      });
    }
    return fruits;
  }

  // --- EVENT LISTENERS ---
  function setupEventListeners() {
    // Tab Switching
    DOM.tabs.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        switchTab(targetTab);
      });
    });

    // Quick Actions
    DOM.btnSimTrigger.addEventListener('click', () => {
      simulateFruitClassification();
    });

    DOM.btnNewSession.addEventListener('click', () => {
      createNewSession();
    });

    // History Tab Controls
    DOM.sessionDropdown.addEventListener('change', (e) => {
      state.selectedHistorySessionId = e.target.value;
      renderHistoryView();
    });

    DOM.btnRefreshHistory.addEventListener('click', () => {
      checkBackendHealth();
      renderHistoryView();
      showToast('Đã làm mới dữ liệu lịch sử thành công', 'info');
    });

    DOM.btnExportCsv.addEventListener('click', () => {
      exportCurrentSessionCsv();
    });

    // History Filter Pills
    DOM.tableFilterPills.querySelectorAll('.filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        DOM.tableFilterPills.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        state.tableFilter = pill.getAttribute('data-filter');
        renderHistoryTable();
      });
    });

    // History Search Box
    DOM.tableSearchInput.addEventListener('input', (e) => {
      state.tableSearch = e.target.value.trim().toLowerCase();
      renderHistoryTable();
    });
  }

  function switchTab(tabId) {
    state.activeTab = tabId;
    DOM.tabs.forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });
    DOM.tabContents.forEach(content => {
      content.classList.toggle('active', content.id === tabId);
    });

    if (tabId === 'tab-live') {
      renderLiveView();
    } else {
      renderHistoryView();
    }
  }

  // --- CLOCK & UPTIME ---
  function startClock() {
    function update() {
      const now = new Date();
      DOM.liveClock.textContent = now.toLocaleTimeString('vi-VN');

      // Update Uptime for running session
      if (state.currentSession && state.currentSession.startTime) {
        const start = new Date(state.currentSession.startTime);
        const diffMs = Math.max(0, now - start);
        const secs = Math.floor((diffMs / 1000) % 60);
        const mins = Math.floor((diffMs / (1000 * 60)) % 60);
        const hours = Math.floor(diffMs / (1000 * 60 * 60));
        DOM.liveSessionUptime.textContent =
          `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
      }
    }
    update();
    setInterval(update, 1000);
  }

  // --- NEW SESSION CREATION ---
  function createNewSession() {
    const now = new Date();

    // Close previous session
    if (state.currentSession) {
      state.currentSession.endTime = now.toISOString();
      state.currentSession.status = 'COMPLETED';
    }

    const nextIndex = state.sessions.length + 1;
    const newSessionId = `SES-${now.getFullYear()}${String(now.getMonth()+1).padStart(2,'0')}${String(now.getDate()).padStart(2,'0')}-${String(nextIndex).padStart(2,'0')}`;

    const newSession = {
      id: newSessionId,
      name: `Phiên #${String(nextIndex).padStart(2, '0')} — ${formatDateShort(now)}`,
      startTime: now.toISOString(),
      endTime: null,
      status: 'RUNNING',
      fruits: []
    };

    state.sessions.push(newSession);
    state.currentSession = newSession;
    state.selectedHistorySessionId = newSession.id;
    saveSessions();

    renderLiveView();
    renderHistoryView();
    showToast(`Đã khởi tạo ${newSession.name}!`, 'success');
  }

  // --- SIMULATION MODE ---
  function simulateFruitClassification() {
    if (!state.currentSession) {
      createNewSession();
    }

    const nextNum = state.currentSession.fruits.length + 1;
    const fruitId = `F${String(nextNum).padStart(4, '0')}`;
    const labels = ['GREEN', 'RIPE', 'RIPE', 'GREEN', 'RIPE', 'REJECT'];
    const chosenLabel = labels[Math.floor(Math.random() * labels.length)];

    const conf = chosenLabel === 'REJECT'
      ? Number((Math.random() * 0.25 + 0.42).toFixed(4))
      : Number((Math.random() * 0.08 + 0.91).toFixed(4));

    const latency = Number((Math.random() * 7 + 15).toFixed(1));
    const now = new Date();
    const imgs = SAMPLE_IMAGES[chosenLabel];
    const imageSrc = imgs[nextNum % imgs.length];

    const fruit = {
      id: fruitId,
      sessionId: state.currentSession.id,
      label: chosenLabel,
      confidence: conf,
      timestamp: now.toISOString(),
      inferenceMs: latency,
      image: imageSrc,
      decisionReason: conf >= 0.70 ? 'CLASSIFIED' : 'LOW_CONFIDENCE',
      servoAction: chosenLabel === 'GREEN' ? 'Gạt Cổng 1 (Green)' : chosenLabel === 'RIPE' ? 'Gạt Cổng 2 (Ripe)' : 'Trôi Cuối (Reject)'
    };

    state.currentSession.fruits.push(fruit);
    saveSessions();

    renderLiveView();
    showToast(`Phát hiện quả ${fruit.id}: ${fruit.label} (${(conf * 100).toFixed(1)}%)`, 'info');
  }

  // --- RENDER LIVE VIEW (TAB 1) ---
  function renderLiveView() {
    const session = state.currentSession;
    if (!session) return;

    // Session Banner
    DOM.liveSessionName.textContent = session.name;
    const startTimeObj = new Date(session.startTime);
    DOM.liveSessionStart.textContent = startTimeObj.toLocaleTimeString('vi-VN');
    DOM.liveTotalCount.textContent = session.fruits.length;

    // Calculate PPM
    const now = new Date();
    const durationMins = Math.max(0.5, (now - startTimeObj) / 60000);
    const ppm = (session.fruits.length / durationMins).toFixed(1);
    DOM.livePpmRate.innerHTML = `${ppm} <small>PPM</small>`;
    DOM.sessionAvgPpm.textContent = `${ppm} PPM`;

    // Latest Fruit Feed
    const latestFruit = session.fruits.length > 0 ? session.fruits[session.fruits.length - 1] : null;

    if (latestFruit) {
      DOM.latestFruitImg.src = latestFruit.image;
      DOM.latestFruitImg.alt = `Quả ${latestFruit.id} - ${latestFruit.label}`;

      // Overlay Tag
      DOM.overlayLabelBadge.textContent = latestFruit.label;
      DOM.overlayLabelBadge.className = `overlay-badge badge-${latestFruit.label.toLowerCase()}`;
      DOM.overlayConfBadge.textContent = `${(latestFruit.confidence * 100).toFixed(1)}%`;

      // Telemetry Section
      const confPct = (latestFruit.confidence * 100).toFixed(1);
      DOM.telemetryConf.textContent = `${confPct}%`;
      DOM.telemetryConfFill.style.width = `${Math.min(100, Math.max(0, confPct))}%`;
      DOM.telemetryConfFill.style.background = latestFruit.confidence >= 0.70
        ? (latestFruit.label === 'GREEN' ? 'var(--color-green)' : 'var(--color-ripe)')
        : 'var(--color-reject)';

      DOM.telemetryFruitId.textContent = `#${latestFruit.id}`;
      DOM.telemetryTimestamp.textContent = formatDateTimeFull(new Date(latestFruit.timestamp));
      DOM.telemetryLatency.textContent = `${latestFruit.inferenceMs} ms`;
      DOM.telemetryDecision.textContent = latestFruit.servoAction;
    } else {
      DOM.telemetryFruitId.textContent = '#--';
      DOM.telemetryTimestamp.textContent = '--:--:--';
      DOM.telemetryLatency.textContent = '-- ms';
      DOM.telemetryDecision.textContent = 'Đang chờ quả...';
      DOM.telemetryConf.textContent = '0.0%';
      DOM.telemetryConfFill.style.width = '0%';
    }

    // Category Breakdown Counts
    const counts = calculateSessionStats(session.fruits);
    const total = session.fruits.length;

    DOM.donutCenterTotal.textContent = total;
    DOM.donutSessionTag.textContent = session.name.split('—')[0].trim();

    DOM.donutGreenCount.textContent = `${counts.green} quả`;
    DOM.donutGreenPct.textContent = `${counts.greenPct}%`;
    DOM.donutGreenBar.style.width = `${counts.greenPct}%`;

    DOM.donutRipeCount.textContent = `${counts.ripe} quả`;
    DOM.donutRipePct.textContent = `${counts.ripePct}%`;
    DOM.donutRipeBar.style.width = `${counts.ripePct}%`;

    DOM.donutRejectCount.textContent = `${counts.reject} quả`;
    DOM.donutRejectPct.textContent = `${counts.rejectPct}%`;
    DOM.donutRejectBar.style.width = `${counts.rejectPct}%`;

    DOM.sessionAvgLatency.textContent = counts.avgLatency ? `${counts.avgLatency} ms` : '-- ms';
    DOM.sessionPassRate.textContent = total > 0 ? `${((counts.green + counts.ripe) / total * 100).toFixed(1)}%` : '100%';

    // Draw Donut Chart
    drawDonutChart(DOM.currentSessionDonut, counts);

    // Recent 10 Fruits Strip
    renderRecentFruitsStrip(session.fruits);
  }

  // --- DRAW CANVAS DONUT CHART ---
  function drawDonutChart(canvas, counts) {
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    const width = 220;
    const height = 220;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;

    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const centerX = width / 2;
    const centerY = height / 2;
    const radius = 90;
    const lineWidth = 24;

    const total = counts.green + counts.ripe + counts.reject;

    if (total === 0) {
      // Empty placeholder ring
      ctx.beginPath();
      ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
      ctx.lineWidth = lineWidth;
      ctx.strokeStyle = '#1E293B';
      ctx.stroke();
      return;
    }

    const segments = [
      { count: counts.green, color: '#10B981' },
      { count: counts.ripe, color: '#F59E0B' },
      { count: counts.reject, color: '#EF4444' }
    ];

    let startAngle = -Math.PI / 2;
    const gap = (segments.filter(s => s.count > 0).length > 1) ? 0.04 : 0;

    segments.forEach(seg => {
      if (seg.count === 0) return;
      const sliceAngle = (seg.count / total) * Math.PI * 2;
      const endAngle = startAngle + sliceAngle;

      ctx.beginPath();
      ctx.arc(centerX, centerY, radius, startAngle + gap / 2, endAngle - gap / 2);
      ctx.lineWidth = lineWidth;
      ctx.strokeStyle = seg.color;
      ctx.lineCap = 'round';
      ctx.stroke();

      startAngle = endAngle;
    });
  }

  // --- RECENT 10 FRUITS STRIP ---
  function renderRecentFruitsStrip(fruits) {
    if (!DOM.recentFruitsStrip) return;
    DOM.recentFruitsStrip.innerHTML = '';

    if (!fruits || fruits.length === 0) {
      DOM.recentFruitsStrip.innerHTML = '<div class="strip-empty-placeholder">Đang chờ quả quất đầu tiên qua băng chuyền...</div>';
      return;
    }

    // Show last 10 fruits in reverse order (newest first)
    const recent = fruits.slice(-10).reverse();

    recent.forEach(fruit => {
      const card = document.createElement('div');
      card.className = 'strip-item-card';

      const timeStr = new Date(fruit.timestamp).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      card.innerHTML = `
        <div class="strip-thumb-wrap">
          <img src="${fruit.image}" alt="Quả ${fruit.id}" class="strip-thumb-img">
        </div>
        <div class="strip-meta">
          <span class="strip-id mono">${fruit.id}</span>
          <span class="strip-time mono">${timeStr}</span>
        </div>
        <div class="strip-badge badge-${fruit.label.toLowerCase()}">
          ${fruit.label} ${(fruit.confidence * 100).toFixed(0)}%
        </div>
      `;
      DOM.recentFruitsStrip.appendChild(card);
    });
  }

  // --- RENDER HISTORY VIEW (TAB 2) ---
  function renderHistoryView() {
    populateSessionDropdown();

    const selectedSession = state.sessions.find(s => s.id === state.selectedHistorySessionId) || state.currentSession;
    if (!selectedSession) return;

    DOM.historyTableTitle.textContent = `Danh Sách Chi Tiết Từng Quả — ${selectedSession.name}`;

    // KPI Counters for Selected Session
    const stats = calculateSessionStats(selectedSession.fruits);
    const total = selectedSession.fruits.length;

    DOM.kpiTotalVal.textContent = total;
    DOM.kpiGreenVal.textContent = stats.green;
    DOM.kpiGreenSub.textContent = `${stats.greenPct}% tổng sản lượng`;

    DOM.kpiRipeVal.textContent = stats.ripe;
    DOM.kpiRipeSub.textContent = `${stats.ripePct}% tổng sản lượng`;

    DOM.kpiRejectVal.textContent = stats.reject;
    DOM.kpiRejectSub.textContent = `${stats.rejectPct}% tổng sản lượng`;

    renderHistoryTable(selectedSession);
  }

  function populateSessionDropdown() {
    DOM.sessionDropdown.innerHTML = '';

    state.sessions.slice().reverse().forEach(session => {
      const opt = document.createElement('option');
      opt.value = session.id;
      const count = session.fruits.length;
      const statusLabel = session.status === 'RUNNING' ? '🟢 Đang chạy' : '✓ Hoàn thành';
      opt.textContent = `${session.name} (${count} quả) — ${statusLabel}`;
      if (session.id === state.selectedHistorySessionId) {
        opt.selected = true;
      }
      DOM.sessionDropdown.appendChild(opt);
    });
  }

  function renderHistoryTable(sessionObj) {
    const session = sessionObj || state.sessions.find(s => s.id === state.selectedHistorySessionId);
    if (!session) return;

    DOM.fruitsTableBody.innerHTML = '';

    // Apply Filter & Search
    let filtered = session.fruits.slice();

    if (state.tableFilter !== 'ALL') {
      filtered = filtered.filter(f => f.label === state.tableFilter);
    }

    if (state.tableSearch) {
      filtered = filtered.filter(f =>
        f.id.toLowerCase().includes(state.tableSearch) ||
        f.label.toLowerCase().includes(state.tableSearch)
      );
    }

    if (filtered.length === 0) {
      DOM.tableEmptyMsg.style.display = 'block';
      return;
    }

    DOM.tableEmptyMsg.style.display = 'none';

    // Render in reverse chronological order
    filtered.slice().reverse().forEach(f => {
      const tr = document.createElement('tr');
      const timeStr = formatDateTimeFull(new Date(f.timestamp));

      tr.innerHTML = `
        <td class="mono font-bold text-primary">#${f.id}</td>
        <td>
          <img src="${f.image}" alt="${f.id}" class="table-thumb">
        </td>
        <td>
          <span class="badge badge-${f.label.toLowerCase()}">${f.label}</span>
        </td>
        <td class="mono font-semibold">${(f.confidence * 100).toFixed(2)}%</td>
        <td class="mono text-muted">${timeStr}</td>
        <td class="mono">${f.inferenceMs} ms</td>
        <td class="text-secondary">${f.servoAction}</td>
        <td>
          <span class="badge badge-neutral">${f.decisionReason}</span>
        </td>
      `;
      DOM.fruitsTableBody.appendChild(tr);
    });
  }

  // --- STATS CALCULATION HELPER ---
  function calculateSessionStats(fruits) {
    const total = fruits ? fruits.length : 0;
    if (total === 0) {
      return { green: 0, ripe: 0, reject: 0, greenPct: 0, ripePct: 0, rejectPct: 0, avgLatency: 0 };
    }

    let green = 0, ripe = 0, reject = 0, totalLat = 0;
    fruits.forEach(f => {
      if (f.label === 'GREEN') green++;
      else if (f.label === 'RIPE') ripe++;
      else if (f.label === 'REJECT') reject++;
      totalLat += (f.inferenceMs || 0);
    });

    return {
      green,
      ripe,
      reject,
      greenPct: ((green / total) * 100).toFixed(1),
      ripePct: ((ripe / total) * 100).toFixed(1),
      rejectPct: ((reject / total) * 100).toFixed(1),
      avgLatency: (totalLat / total).toFixed(1)
    };
  }

  // --- CSV EXPORT GENERATOR ---
  function exportCurrentSessionCsv() {
    const session = state.sessions.find(s => s.id === state.selectedHistorySessionId);
    if (!session || !session.fruits || session.fruits.length === 0) {
      showToast('Không có dữ liệu trong phiên này để xuất CSV', 'error');
      return;
    }

    // CSV Header with UTF-8 BOM
    let csvContent = '\uFEFF';
    csvContent += 'STT,Mã Quả,Phân Loại AI,Độ Tin Cậy (%),Thời Gian Chụp,Độ Trễ (ms),Hành Động Servo,Lý Do Quyết Định\n';

    session.fruits.forEach((f, idx) => {
      const timeFormatted = formatDateTimeFull(new Date(f.timestamp)).replace(',', '');
      const row = [
        idx + 1,
        `"${f.id}"`,
        `"${f.label}"`,
        `"${(f.confidence * 100).toFixed(2)}"`,
        `"${timeFormatted}"`,
        `"${f.inferenceMs}"`,
        `"${f.servoAction}"`,
        `"${f.decisionReason}"`
      ].join(',');
      csvContent += row + '\n';
    });

    // Create Download Link
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `AutoSort_BaoCao_${session.id}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    showToast(`Đã xuất file báo cáo AutoSort_BaoCao_${session.id}.csv!`, 'success');
  }

  // --- BACKEND HEALTH CHECK ---
  async function checkBackendHealth() {
    try {
      const t0 = performance.now();
      const res = await fetch(`${state.backendApiBase}/health`, { method: 'GET', cache: 'no-store' });
      const t1 = performance.now();

      if (res.ok) {
        const data = await res.json();
        state.cloudOnline = true;
        state.cloudLatency = Math.round(t1 - t0);

        DOM.cloudStatusPill.querySelector('.status-indicator').className = 'status-indicator online';
        DOM.cloudLatency.textContent = `${state.cloudLatency}ms`;
        DOM.cloudStatusPill.setAttribute('title', `Cloud AI Online (Mode: ${data.mode || 'onnx'})`);
        if (data.model_version) {
          document.getElementById('model-ver').textContent = data.model_version;
        }
      } else {
        throw new Error('Server not OK');
      }
    } catch (e) {
      state.cloudOnline = false;
      DOM.cloudStatusPill.querySelector('.status-indicator').className = 'status-indicator offline';
      DOM.cloudLatency.textContent = 'MOCK / DEMO';
      DOM.cloudStatusPill.setAttribute('title', 'Cloud AI chưa kết nối. Đang chạy chế độ Giả Lập / Mock');
    }
  }

  // --- TOAST NOTIFICATIONS ---
  function showToast(message, type = 'info') {
    if (!DOM.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icon = type === 'success' ? '✅' : type === 'error' ? '⚠️' : 'ℹ️';
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    DOM.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  // --- DATE FORMATTING HELPERS ---
  function formatDateShort(d) {
    return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
  }

  function formatDateTimeFull(d) {
    const time = d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const date = formatDateShort(d);
    return `${time} - ${date}`;
  }

  // Run on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
