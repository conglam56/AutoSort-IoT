# AutoSort IoT — Dashboard giám sát

Dashboard HTML/CSS/JavaScript thuần, không cần npm hoặc bước build.

## Chạy thử

Từ thư mục gốc repository:

```powershell
python -m http.server 8765 --bind 127.0.0.1 --directory dashboard
```

Mở http://127.0.0.1:8765/. Mặc định là **Mô phỏng**, với hai phiên mẫu.
Ảnh và số liệu mẫu luôn được ghi rõ trên giao diện.

Khi chạy FastAPI, dashboard cũng có tại http://127.0.0.1:8000/dashboard/.
Chọn **Nguồn → Máy chủ AI** để đọc các phiên trên dịch vụ. Trang được phục vụ
tại `/dashboard/` dùng API cùng origin; bản static chạy riêng dùng
`http://127.0.0.1:8000`.

## Sử dụng

- **Tổng quan:** số quả ghi nhận, tỉ lệ đạt, năng suất trung bình, độ trễ AI,
  ảnh và confidence của quả được chọn, phân bố chất lượng.
- **Dòng quả gần đây:** nhấn một trong 10 ảnh để xem lại kết quả trong khu vực chụp ảnh.
- **Mô phỏng một quả:** chỉ admin được thêm bản ghi mẫu vào phiên demo, không gọi phần cứng.
- **Phiên mới:** chỉ admin được xác nhận kết thúc phiên hiện tại và tạo phiên rỗng;
  phiên cũ vẫn có trong lịch sử.
- **Lịch sử phiên:** chọn phiên, tìm mã quả hoặc nhãn, lọc loại quả và xuất CSV UTF-8.
- **Máy chủ AI:** tự đọc dữ liệu mỗi 5 giây khi tab đang hiển thị. Khi mất kết nối,
  dữ liệu lần cuối được giữ và thông báo rõ chưa đồng bộ.
- **Cách sử dụng:** hướng dẫn ngắn trong thanh điều hướng desktop.
- **Quản trị:** admin thêm tài khoản, tìm kiếm/phân trang, đổi quyền,
  khóa/mở tài khoản, đặt lại mật khẩu, đăng xuất các thiết bị và xem nhật ký.
- **Đổi mật khẩu:** mọi tài khoản đã đăng nhập đều đổi được mật khẩu của mình
  sau khi nhập đúng mật khẩu hiện tại; phải đăng nhập lại sau đó.

Dữ liệu demo được lưu riêng bằng khóa `autosort_demo_sessions_v2` trong
localStorage. Khóa `autosort_sessions` của bản giao diện cũ được giữ nguyên.
Dữ liệu từ máy chủ không trộn vào kho demo và không lưu lại trong trình duyệt.
Khi trình duyệt không cho lưu, giao diện vẫn chạy và hiển thị thông báo.

## Giới hạn vận hành

Chế độ máy chủ yêu cầu đăng nhập. Viewer và khách không được tạo phiên ở cả
chế độ máy chủ lẫn mô phỏng. Tải lại trang tự khôi phục nguồn máy chủ khi có
phiên đăng nhập hợp lệ. API đọc phiên hiện tại trả `null` nếu chưa có phiên,
không tự tạo phiên khi người dùng chỉ xem. Trang không gửi lệnh tay gạt,
không POST `/infer`, không điều khiển băng chuyền.

Kết quả `MOCK` được hiển thị là chưa phân loại, không tính vào tỉ lệ đạt
và không hiển thị hướng tay gạt hợp lệ. Khi API chỉ gửi đường dẫn ảnh mẫu thay
cho snapshot thật, dashboard hiển thị trạng thái chưa có ảnh.

Các endpoint đọc:

- `GET /health`
- `GET /api/session/current`
- `GET /api/sessions`
- `GET /api/sessions/{id}`

Xác thực: `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`.
Cookie HttpOnly và CSRF được API kiểm tra; dữ liệu nhạy cảm không lưu localStorage.
Chỉ admin được `POST /api/sessions/new`. PostgreSQL lưu lịch sử bền vững.
Xem cấu hình và cách tạo tài khoản trong [hướng dẫn API](../cloud-ai/README.md).
Chi tiết quản trị và phân quyền: [ADMIN_GUIDE.md](../docs/ADMIN_GUIDE.md).

## Giao diện

Định hướng theo `ui-ux-pro-max` và `frontend-design`: nền xám sáng,
xanh thực vật làm màu thao tác, cam quất và đỏ đất cho các lớp phân loại.
Font Be Vietnam Pro có hỗ trợ tiếng Việt, có fallback hệ thống khi không có mạng.
Icon SVG dùng cùng nét vẽ; giao diện không có thư viện/CDN JavaScript.

Bố cục chuyển từ sidebar và hai cột trên desktop sang điều hướng ngang và
một cột trên điện thoại. Bảng có vùng cuộn riêng, các điều khiển có focus bàn phím,
dialog hỗ trợ Escape và CSS tôn trọng `prefers-reduced-motion`.
