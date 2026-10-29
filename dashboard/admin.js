import { isAdminRole, roleLabel } from './permissions.js';
/** Account administration uses server permissions; secrets stay only in open forms. */
export function createAdminConsole({ request, getUser, onSessionLost, toast }) {
  const $ = id => document.getElementById(id);
  const state = { identity: '', section: 'users', usersOffset: 0, auditOffset: 0, usersTotal: 0, auditTotal: 0, epoch: 0, usersRequest: 0, auditRequest: 0, saving: false, edit: null, reset: null, revoke: null };
  const limit = 25;
  const dialogs = ['admin-create-dialog', 'admin-edit-dialog', 'admin-reset-dialog', 'own-password-dialog', 'admin-revoke-dialog'];
  const messages = {
    USERNAME_EXISTS: 'Tên đăng nhập đã tồn tại. Hãy chọn tên khác.', ACCOUNT_NOT_FOUND: 'Tài khoản không còn trong danh sách. Hãy làm mới dữ liệu.',
    LAST_ADMIN_REQUIRED: 'Hệ thống phải còn ít nhất một quản trị viên đang hoạt động.', CANNOT_CHANGE_OWN_ACCESS: 'Bạn không thể tự đổi quyền hoặc khóa tài khoản đang dùng.',
    USE_OWN_PASSWORD_FORM: 'Dùng nút “Đổi mật khẩu” cho tài khoản của bạn.', USE_LOGOUT: 'Dùng nút “Đăng xuất” cho tài khoản của bạn.',
    CURRENT_PASSWORD_INCORRECT: 'Mật khẩu hiện tại không đúng.', PASSWORD_UNCHANGED: 'Mật khẩu mới phải khác mật khẩu hiện tại.'
  };
  const actions = { 'login.succeeded': 'Đăng nhập thành công', 'login.failed': 'Đăng nhập thất bại', logout: 'Đăng xuất', 'session.created': 'Tạo phiên dữ liệu', 'session.completed': 'Kết thúc phiên dữ liệu',
    'account.created': 'Thêm tài khoản', 'account.role_changed': 'Đổi quyền', 'account.enabled': 'Mở tài khoản', 'account.disabled': 'Khóa tài khoản',
    'account.password_reset': 'Đặt lại mật khẩu', 'account.password_changed': 'Đổi mật khẩu', 'account.sessions_revoked': 'Đăng xuất thiết bị',
    'account.bootstrap': 'Khởi tạo quản trị viên', 'account.create-user': 'Thêm tài khoản bằng công cụ quản trị', 'account.reset-password': 'Đặt lại mật khẩu bằng công cụ quản trị', 'account.disable-user': 'Khóa tài khoản bằng công cụ quản trị' };
  const isAdmin = () => isAdminRole(getUser());
  function clearError(id) { $(id).hidden = true; $(id).textContent = ''; }
  function errorText(error) {
    return messages[error.detail] || (error.status === 422 ? 'Kiểm tra tên đăng nhập và mật khẩu (tối thiểu 12 ký tự).' : error.status === 429 ? 'Bạn đã thử quá nhiều lần. Vui lòng đợi 15 phút.' : error.status === 403 ? 'Bạn không có quyền thực hiện thao tác này hoặc CSRF đã thay đổi. Hãy tải lại trang.' : 'Chưa nhận được xác nhận từ máy chủ. Làm mới dữ liệu trước khi thử lại.');
  }
  function showError(id, message) { $(id).textContent = message; $(id).hidden = false; $(id).focus(); }
  function handleError(id, error) { if (error.status === 401) onSessionLost(); else showError(id, errorText(error)); }
  function stamp(value) { const d = new Date(value); return Number.isFinite(d.getTime()) ? d.toLocaleString('vi-VN') : '—'; }
  function cell(row, text) { const td = document.createElement('td'); td.textContent = text; row.append(td); return td; }
  function empty(body, columns, message) { body.replaceChildren(); const row = document.createElement('tr'); const td = cell(row, message); td.colSpan = columns; td.className = 'admin-empty'; body.append(row); }
  function openDialog(id) { if (state.saving || !getUser() || (id !== 'own-password-dialog' && !isAdmin())) return; const dialog = $(id); dialog.querySelector('form').reset(); dialog.querySelectorAll('.form-error').forEach(p => { p.hidden = true; p.textContent = ''; }); dialog.showModal(); }
  function button(text, action, account, disabled = false) {
    const el = document.createElement('button'); el.type = 'button'; el.className = 'btn btn-neutral admin-row-action'; el.textContent = text;
    el.disabled = disabled; el.setAttribute('aria-label', text + ' — ' + account.username);
    if (disabled) el.title = 'Dùng mục Đổi mật khẩu hoặc Đăng xuất cho tài khoản của bạn.';
    el.addEventListener('click', action); return el;
  }
  function renderUsers(data) {
    const body = $('admin-users-body'); body.replaceChildren();
    if (!data.users.length) empty(body, 6, 'Không tìm thấy tài khoản phù hợp.');
    for (const account of data.users) {
      const row = document.createElement('tr'); const self = account.id === getUser()?.id;
      cell(row, account.username + (self ? ' · Bạn' : ''));
      cell(row, account.role === 'viewer' ? 'Chờ cấp quyền · tài khoản cũ' : roleLabel(account));
      const status = document.createElement('span'); status.className = 'account-status ' + (account.active ? 'is-active' : 'is-disabled'); status.textContent = account.active ? 'Đang hoạt động' : 'Đã khóa';
      const statusCell = document.createElement('td'); statusCell.append(status); row.append(statusCell);
      cell(row, account.activeSessions + ' phiên'); cell(row, stamp(account.createdAt));
      const controls = document.createElement('td'); const group = document.createElement('div'); group.className = 'admin-row-actions';
      group.append(button('Quyền / trạng thái', () => { state.edit = account; openDialog('admin-edit-dialog'); $('admin-edit-target').textContent = account.username + (account.role === 'viewer' ? ' · Đã khóa, chọn quyền mới trước khi mở.' : ''); $('admin-edit-role').value = account.role === 'admin' ? 'admin' : 'operator'; $('admin-edit-active').checked = account.active; }, account, self));
      group.append(button('Đặt lại mật khẩu', () => { state.reset = account; openDialog('admin-reset-dialog'); $('admin-reset-target').textContent = account.username; }, account, self));
      group.append(button('Đăng xuất thiết bị', () => { state.revoke = account; openDialog('admin-revoke-dialog'); $('admin-revoke-target').textContent = 'Đăng xuất mọi thiết bị của ' + account.username + '. Tài khoản vẫn được giữ.'; }, account, self || !account.activeSessions));
      controls.append(group); row.append(controls); body.append(row);
    }
    $('admin-users-summary').textContent = data.total + ' tài khoản · Operator vận hành, Admin quản trị';
    pagination('users', data.total, data.users.length);
  }
  function pagination(kind, total, count) {
    const offset = state[kind + 'Offset']; state[kind + 'Total'] = total;
    $('admin-' + kind + '-page').textContent = total ? (offset + 1) + '–' + (offset + count) + ' / ' + total : '0 kết quả';
    $('admin-' + kind + '-prev').disabled = offset === 0;
    $('admin-' + kind + '-next').disabled = offset + limit >= total;
  }
  async function loadUsers() {
    if (!isAdmin()) return;
    const epoch = state.epoch; const serial = ++state.usersRequest; clearError('admin-error'); $('admin-users-panel').setAttribute('aria-busy', 'true');
    try {
      const query = new URLSearchParams({ search: $('admin-user-search').value.trim(), offset: state.usersOffset, limit });
      const data = await request('/api/admin/users?' + query);
      if (epoch !== state.epoch || serial !== state.usersRequest) return;
      if (data.total && state.usersOffset >= data.total) { state.usersOffset = Math.floor((data.total - 1) / limit) * limit; return loadUsers(); }
      renderUsers(data);
    } catch (error) { if (epoch === state.epoch && serial === state.usersRequest) handleError('admin-error', error); }
    finally { if (epoch === state.epoch && serial === state.usersRequest) $('admin-users-panel').setAttribute('aria-busy', 'false'); }
  }
  async function loadAudit() {
    if (!isAdmin()) return;
    const epoch = state.epoch; const serial = ++state.auditRequest; clearError('admin-error'); $('admin-audit-panel').setAttribute('aria-busy', 'true');
    try {
      const query = new URLSearchParams({ kind: $('admin-audit-filter').value, offset: state.auditOffset, limit });
      const data = await request('/api/admin/audit-logs?' + query);
      if (epoch !== state.epoch || serial !== state.auditRequest) return;
      const body = $('admin-audit-body'); body.replaceChildren();
      if (!data.logs.length) empty(body, 5, 'Chưa có hoạt động trong mục này.');
      for (const entry of data.logs) {
        const row = document.createElement('tr'); const [action, target] = entry.action.split(':', 2);
        [stamp(entry.created_at), actions[action] || action, entry.username || 'Hệ thống / khách', target || '—', entry.ip_address].forEach(value => cell(row, value)); body.append(row);
      }
      pagination('audit', data.total, data.logs.length);
    } catch (error) { if (epoch === state.epoch && serial === state.auditRequest) handleError('admin-error', error); }
    finally { if (epoch === state.epoch && serial === state.auditRequest) $('admin-audit-panel').setAttribute('aria-busy', 'false'); }
  }
  function section(kind) {
    state.section = kind;
    for (const name of ['users', 'audit']) { const active = kind === name; $('admin-' + name + '-panel').hidden = !active; $('admin-' + name + '-tab').setAttribute('aria-pressed', String(active)); $('admin-' + name + '-tab').className = 'btn ' + (active ? 'btn-action' : 'btn-neutral'); }
    if (kind === 'users') loadUsers(); else loadAudit();
  }
  async function submit(event, errorId, operation, success, after) {
    event.preventDefault(); if (state.saving || !getUser()) return;
    clearError(errorId); const form = event.currentTarget; const epoch = state.epoch;
    let pending;
    try { pending = operation(); } catch (error) { showError(errorId, error.message); return; }
    state.saving = true; form.setAttribute('aria-busy', 'true'); form.querySelectorAll('input,select,button').forEach(el => { el.disabled = true; });
    try {
      await pending;
      if (epoch !== state.epoch) return;
      form.closest('dialog').close(); form.reset(); toast(success);
      if (after) after(); else { await loadUsers(); if (state.section === 'audit') await loadAudit(); }
    } catch (error) { if (epoch === state.epoch) handleError(errorId, error); }
    finally { state.saving = false; form.setAttribute('aria-busy', 'false'); form.querySelectorAll('input,select,button').forEach(el => { el.disabled = false; }); }
  }
  function matching(first, confirm) { const password = $(first).value; if (password !== $(confirm).value) throw new Error('Hai mật khẩu chưa khớp. Vui lòng nhập lại.'); return password; }
  function post(path, body) { return request(path, { method: 'POST', body: JSON.stringify(body), timeoutMs: 60000 }); }
  $('admin-create-user').addEventListener('click', () => openDialog('admin-create-dialog'));
  $('admin-users-tab').addEventListener('click', () => section('users')); $('admin-audit-tab').addEventListener('click', () => section('audit'));
  $('admin-refresh-users').addEventListener('click', loadUsers); $('admin-refresh-audit').addEventListener('click', loadAudit);
  let searchTimer;
  $('admin-user-search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.usersOffset = 0; loadUsers(); }, 250); });
  $('admin-audit-filter').addEventListener('change', () => { state.auditOffset = 0; loadAudit(); });
  for (const kind of ['users', 'audit']) for (const direction of ['prev', 'next']) $('admin-' + kind + '-' + direction).addEventListener('click', () => { state[kind + 'Offset'] = Math.max(0, state[kind + 'Offset'] + (direction === 'next' ? limit : -limit)); if (kind === 'users') loadUsers(); else loadAudit(); });
  for (const id of dialogs) {
    $(id).addEventListener('cancel', event => { if (state.saving) event.preventDefault(); });
    $(id).addEventListener('close', () => { $(id).querySelector('form').reset(); });
  }
  document.querySelectorAll('[data-close-dialog]').forEach(el => el.addEventListener('click', () => { if (!state.saving) $(el.dataset.closeDialog).close(); }));
  $('admin-create-form').addEventListener('submit', event => submit(event, 'admin-create-error', () => post('/api/admin/users', { username: $('admin-new-username').value.trim().toLowerCase(), password: matching('admin-new-password', 'admin-new-password-confirm'), role: $('admin-new-role').value }), 'Đã tạo tài khoản.'));
  $('admin-edit-form').addEventListener('submit', event => submit(event, 'admin-edit-error', () => post('/api/admin/users/' + state.edit.id + '/settings', { role: $('admin-edit-role').value, active: $('admin-edit-active').checked }), 'Đã lưu quyền và trạng thái tài khoản.'));
  $('admin-reset-form').addEventListener('submit', event => submit(event, 'admin-reset-error', () => post('/api/admin/users/' + state.reset.id + '/password', { password: matching('admin-reset-password', 'admin-reset-confirm') }), 'Đã đặt lại mật khẩu và đăng xuất các thiết bị.'));
  $('admin-revoke-form').addEventListener('submit', event => submit(event, 'admin-revoke-error', () => post('/api/admin/users/' + state.revoke.id + '/revoke-sessions', {}), 'Đã đăng xuất các thiết bị của tài khoản.'));
  $('own-password-form').addEventListener('submit', event => submit(event, 'own-password-error', () => post('/api/auth/password', { current_password: $('own-current-password').value, new_password: matching('own-new-password', 'own-new-confirm') }), 'Đã đổi mật khẩu. Hãy đăng nhập lại.', onSessionLost));
  return {
    show() { if (isAdmin()) section(state.section); },
    openPassword() { openDialog('own-password-dialog'); },
    identityChanged(user) {
      const key = user ? user.id + ':' + user.role : '';
      $('tab-admin-btn').hidden = !isAdminRole(user); $('btn-password').hidden = !user;
      if (state.identity === key) return;
      state.identity = key; state.epoch++; state.usersRequest++; state.auditRequest++; state.usersOffset = 0; state.auditOffset = 0;
      state.edit = state.reset = state.revoke = null;
      for (const id of ['admin-edit-target', 'admin-reset-target', 'admin-revoke-target']) $(id).textContent = ''; $('admin-users-body').replaceChildren(); $('admin-audit-body').replaceChildren(); clearError('admin-error');
      $('admin-user-search').value = ''; $('admin-audit-filter').value = 'all';
      $('admin-users-summary').textContent = 'Đang tải tài khoản…'; $('admin-users-page').textContent = ''; $('admin-audit-page').textContent = '';
      for (const id of dialogs) { if ($(id).open) $(id).close(); $(id).querySelector('form').reset(); }
    }
  };
}
