const form = document.getElementById('login-form');
const button = document.getElementById('login-submit');
const error = document.getElementById('login-error');
form.addEventListener('submit', async event => {
  event.preventDefault();
  button.disabled = true; button.textContent = 'Đang đăng nhập…'; error.hidden = true;
  try {
    const response = await fetch('/api/auth/login', { method: 'POST', credentials: 'include', cache: 'no-store',
      signal: AbortSignal.timeout(60000), headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({username: document.getElementById('login-username').value.trim(), password: document.getElementById('login-password').value}) });
    if (!response.ok) {
      error.textContent = response.status === 401 ? 'Tên đăng nhập hoặc mật khẩu không đúng.' : response.status === 429 ? 'Bạn đã thử quá nhiều lần. Vui lòng thử lại sau 15 phút.' : 'Chưa kết nối được máy chủ. Vui lòng thử lại.';
      error.hidden = false; return;
    }
    location.replace('index.html');
  } catch {
    error.textContent = 'Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.'; error.hidden = false;
  } finally {
    document.getElementById('login-password').value = '';
    button.disabled = false; button.textContent = 'Đăng nhập';
  }
});
fetch('/api/auth/me', {credentials:'include',cache:'no-store',signal:AbortSignal.timeout(10000)})
  .then(response => {if(response.ok) location.replace('index.html');}).catch(() => {});
