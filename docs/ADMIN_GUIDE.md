# Quản trị dashboard AutoSort

Đăng nhập bằng tài khoản `admin`, sau đó chọn **Quản trị** trong thanh điều hướng.
Trang này quản lý dữ liệu trên máy chủ, độc lập với nguồn mô phỏng của trang Tổng quan.

## Quyền

| Chức năng | Khách | Người dùng (`viewer`) | Quản trị viên (`admin`) |
|---|---|---|---|
| Xem dữ liệu mẫu | Có | Có | Có |
| Xem dữ liệu thực tế, lịch sử và xuất CSV | Không | Có | Có |
| Tạo phiên mới hoặc thêm quả mô phỏng | Không | Không | Có |
| Quản lý tài khoản, xem nhật ký quản trị | Không | Không | Có |
| Đổi mật khẩu của mình | Không | Có | Có |

Nút tạo phiên bị ẩn với khách/người dùng, có chốt kiểm tra trong trình xử lý
giao diện và API. Đọc `/api/session/current` không tạo phiên mới; trả `null`
nếu chưa có phiên. API key thiết bị vẫn chỉ dùng để gửi ảnh tới `/infer`.

## Tài khoản

- **Thêm tài khoản:** tên 3–64 ký tự gồm chữ, số, `.`, `_`, `-`; tự chuyển thành
  chữ thường. Mật khẩu từ 12 đến 256 ký tự. Vai trò mặc định là Người dùng.
- **Quyền / trạng thái:** đổi giữa admin/viewer, hoặc bỏ chọn Cho phép đăng nhập
  để khóa tài khoản. Tài khoản đã khóa vẫn giữ lịch sử hoạt động.
- **Đặt lại mật khẩu:** admin nhập mật khẩu mới cho tài khoản khác. Không hiển thị
  hoặc khôi phục mật khẩu cũ. Các thiết bị của tài khoản đó bị đăng xuất.
- **Đăng xuất thiết bị:** thu hồi mọi phiên đăng nhập của tài khoản, không khóa
  tài khoản; họ có thể đăng nhập lại bằng mật khẩu hiện tại.
- **Đổi mật khẩu:** dùng nút trong khu vực tài khoản cho chính mình; cần mật khẩu
  hiện tại, mật khẩu mới và xác nhận. Mọi phiên đăng nhập của mình bị thu hồi.

Không thể tự hạ quyền hoặc tự khóa tài khoản đang sử dụng. Luôn phải có ít nhất
một admin hoạt động. Chốt này áp dụng trong giao dịch PostgreSQL, kể cả khi hai
admin thao tác đồng thời; CLI cũng không được khóa admin hoạt động cuối cùng.
Khóa/mở hoặc thay đổi quyền sẽ thu hồi các phiên đăng nhập hiện có ngay lập tức.

Tài khoản không bị xóa vĩnh viễn trong giao diện; dùng khóa để bảo toàn nhật ký.
Admin không cần quyền truy cập trực tiếp database để quản lý tài khoản trên cloud.

## Nhật ký hoạt động

Mục **Nhật ký hoạt động** có lọc nhóm đăng nhập, tài khoản, phiên phân loại và
phân trang 25 dòng. Mỗi thao tác quản trị ghi người thực hiện, tài khoản liên quan,
thời điểm và IP. Mật khẩu, cookie và API key không được đưa vào nhật ký.

## API

- `GET /api/admin/users?search=&limit=25&offset=0`
- `POST /api/admin/users`: `username`, `password`, `role`.
- `POST /api/admin/users/{id}/settings`: `role`, `active`.
- `POST /api/admin/users/{id}/password`: `password` mới.
- `POST /api/admin/users/{id}/revoke-sessions`.
- `GET /api/admin/audit-logs?kind=all&limit=25&offset=0`.
- `POST /api/auth/password`: `current_password`, `new_password`.

Các POST cần cookie phiên, Origin được phép và `X-CSRF-Token`. API kiểm tra lại
tài khoản và phiên đăng nhập ngay trong giao dịch ghi, không chỉ dựa vào quyền
đã đọc trước đó. Khi bị đổi quyền/khóa, người dùng không thể tiếp tục dùng cookie cũ.
Lỗi 401 yêu cầu đăng nhập lại; 403 là thiếu quyền/CSRF; 409 là trùng tên hoặc thao
tác bị chặn để bảo toàn quyền quản trị. Không cần thay đổi schema database v1.
