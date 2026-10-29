# AutoSort backend — Java 21 / Spring Boot 3.5

Spring Boot phục vụ toàn bộ HTTP API, dashboard, Spring Security, cookie/CSRF,
quản trị tài khoản, PostgreSQL và giao dịch chống ghi trùng. Không còn FastAPI.
`cloud-ai/worker.py` là tiến trình Python ONNX nội bộ, giao tiếp stdin/stdout với
Java; không mở cổng HTTP, không có database, tài khoản hoặc API công khai riêng.
Camera Bridge trên máy tính vẫn dùng Python và lấy JPEG từ **điện thoại**.

## Chạy trên máy phát triển

Cần Java 21, Maven 3.9+, Python 3.12 và PostgreSQL. Từ root repository:

```powershell
py -3.12 -m venv cloud-ai/.venv312
& cloud-ai/.venv312/Scripts/python.exe -m pip install -r cloud-ai/requirements.txt
Copy-Item backend/.env.example backend/.env
mvn -f backend/pom.xml package -DskipTests
java -jar backend/target/autosort-backend-1.0.0.jar
```

Chỉnh `.env` trước khi chạy: `DATABASE_URL`, `DEVICE_API_KEY`, mật khẩu bootstrap
và `PYTHON_BIN` trỏ tới Python đã cài requirements. Maven/Java chạy từ root repo
để tìm `backend/.env`, worker và model theo đường dẫn mặc định.
Biến môi trường của tiến trình có ưu tiên cao hơn file `.env`.
Backend không đọc `.env` của camera-bridge hay file mật khẩu cloud.

- PostgreSQL trống: bật `INITIALIZE_DATABASE=true`, đặt mật khẩu bootstrap riêng
  12–256 ký tự. Tạo schema v2 và admin một lần trong giao dịch.
- Database cũ v1: bật `MIGRATE_DATABASE=true` để thêm bảng biên nhận v2.
- Database đã có admin: giữ nguyên tài khoản, hash mật khẩu và phiên đăng nhập.
  Argon2id do Python tạo được Spring Security đọc trực tiếp.
- Sau khi khởi tạo/migration thành công, có thể tắt hai cờ và gỡ mật khẩu bootstrap.
  Không có tài khoản hoặc mật khẩu mặc định.

Mở `http://127.0.0.1:8000/dashboard/`. `/health` có `backend=spring-boot`;
`/ready` kiểm tra PostgreSQL/schema. Chưa có model vẫn hiển thị `MOCK` rõ ràng.
Khi dùng Render, cookie phải Secure và origins HTTPS; xem
[hướng dẫn triển khai Docker và chuyển dịch vụ](../docs/RENDER_DEPLOY.md).

## API tương thích

Giữ nguyên URL và JSON mà dashboard và bridge dùng:

- `/api/auth/login`, `/me`, `/logout`, `/password`.
- `/api/admin/users`, `/{id}/settings`, `/{id}/password`, `/{id}/revoke-sessions`.
- `/api/admin/audit-logs`, `/api/audit-logs` (đường dẫn tương thích).
- `/api/session/current`, `/api/sessions`, `/api/sessions/{id}`, `/api/sessions/new`.
- `POST /infer`: multipart `fruit_id`, `camera_id`, `image`, header `X-API-Key`
  và `Idempotency-Key` tùy chọn. Ảnh JPEG tối đa 1.000.000 byte, 25 megapixel.

Viewer chỉ đọc/xuất dữ liệu. Admin mới được tạo phiên và quản trị tài khoản.
GET không tự tạo phiên. Mọi POST từ tài khoản cần Origin được phép và CSRF token
trong database; `/infer` xác thực riêng bằng key thiết bị.
Cookie `autosort_session` HttpOnly, SameSite=Lax, hết hạn sau 8 giờ. Token chỉ
lưu dưới dạng SHA-256 trong DB; không dùng JSESSIONID hoặc JWT/localStorage.
Spring Security chạy stateless HTTP nhưng phiên ứng dụng vẫn thu hồi được trong DB.

Các giao dịch thay đổi tài khoản kiểm tra lại cookie và role dưới cùng advisory
lock như bản Python. Đổi quyền/khóa/reset mật khẩu thu hồi phiên ngay; không tự
hạ quyền/khóa bản thân và không được làm mất admin hoạt động cuối cùng.
Login giới hạn 10 lần/tên và 30 lần/IP trong 15 phút, lưu bộ đếm PostgreSQL.

Idempotency lưu kết quả và biên nhận cùng giao dịch, tồn tại qua restart/rollover;
key cũ với ảnh hoặc định danh khác trả 409. Ảnh dưới 300 KB được giữ trong DB,
ảnh lớn hơn chỉ lưu metadata. Snapshot và lịch sử thực tế vẫn ở cloud.

Proxy headers xử lý bằng Tomcat RemoteIpValve với danh sách proxy nội bộ mặc định,
không tin mọi X-Forwarded-For do client gửi. Nếu đổi môi trường mạng cần đối chiếu
`server.tomcat.remoteip.internal-proxies` với proxy thực tế trước khi triển khai.

## Kiểm thử

```powershell
& cloud-ai/.venv312/Scripts/python.exe -m pip install -r cloud-ai/requirements-dev.txt
& cloud-ai/.venv312/Scripts/python.exe -m unittest discover -s tests -v
$env:AUTOSORT_TEST_DATABASE_URL = '<URL PostgreSQL localhost kiểm thử>'
$env:AUTOSORT_TEST_PYTHON = (Resolve-Path cloud-ai/.venv312/Scripts/python.exe).Path
mvn -f backend/pom.xml verify
```

Test Java tích hợp dùng schema `autosort_java_test_<uuid>` riêng, tự xóa sau test,
không sửa bảng ứng dụng. Chỉ cho phép localhost; role kiểm thử cần CREATE SCHEMA.
Không đặt URL kiểm thử thì nhóm tích hợp PostgreSQL được báo skipped; test tương
thích Argon2/cấu hình vẫn chạy. CI cấp PostgreSQL riêng, chạy Python + Java và
build Docker. Các test dùng camera/Serial giả lập; vẫn cần bàn giao thiết bị/model
thật để kiểm thử toàn hệ thống.
