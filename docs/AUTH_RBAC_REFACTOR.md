# Bàn giao refactor Authentication/RBAC — schema v3

## 1. Vấn đề tìm thấy

Cookie HttpOnly/SameSite, token SHA-256, Argon2id, Origin/CSRF, rate limit và chốt
admin cuối cùng đã có và được giữ. Viewer chỉ đọc, quyền tạo phiên gắn riêng Admin.
Tạo phiên tự kết thúc phiên cũ; chưa có API kết thúc riêng. Nhận ảnh tự tạo phiên
RUNNING khi không có phiên, nên không tồn tại cửa sổ ghi dữ liệu do Operator quyết định.
Frontend cần xử lý 401 tập trung và phân biệt Guest/Demo với phiên vận hành thật.

## 2. Ma trận quyền cuối

| Chức năng | Guest | Operator | Admin |
|---|---|---|---|
| Demo công khai | Có | Có | Có |
| Dữ liệu thật, lịch sử, CSV thật | Không | Có | Có |
| Tạo/kết thúc phiên dữ liệu | Không | Có | Có |
| Đổi mật khẩu bản thân | Không | Có | Có |
| Quản trị tài khoản, role, khóa/mở, reset/revoke | Không | Không | Có |
| Nhật ký quản trị | Không | Không | Có |

Guest không có bản ghi role trong database. Camera Bridge xác thực riêng bằng
X-API-Key; cookie người dùng không thay được key. CSV xuất tại trình duyệt từ dữ
liệu đã tải; không có endpoint xuất file riêng cần mở công khai.

## 3. Backend và vòng đời

AccessPolicy tập trung isAdmin/canOperate. Spring Security chặn trực tiếp mọi API
thật; giao dịch ghi kiểm tra lại tài khoản, role và token dưới khóa để chống thu hồi
đồng thời. Body/header giả role không có giá trị cấp quyền.

- POST `/api/sessions/new`: Operator/Admin, Origin+CSRF. Có RUNNING → 409
  `SESSION_ALREADY_RUNNING`, không tự hoàn tất phiên cũ.
- POST `/api/sessions/{id}/end`: RUNNING → COMPLETED, ghi endTime. Gọi lại giữ nguyên
  timestamp, không ghi lặp audit. Phiên không tồn tại → 404, trạng thái sai → 409.
- Start/end nhận Idempotency-Key tùy chọn. Biên nhận gắn actor, thao tác và phiên;
  key cũ dùng sai actor/thao tác/đích → 409. Replay không tạo phiên mới.
- GET current trả null nếu không có phiên, không ghi database.
- POST `/infer` cần RUNNING đã được tạo chủ động, nếu không trả 409
  `SESSION_NOT_RUNNING` và không gọi AI. Biên nhận ảnh cũ vẫn replay được sau khi
  kết thúc, không ghi thêm quả.
- Inference/end dùng cùng khóa phiên và giao dịch: ảnh hoàn tất ghi trước khi đóng
  hoặc bị từ chối sau khi đóng. Không ghi vào COMPLETED hay tự chuyển ảnh sang phiên mới.
- Audit tạo/kết thúc ghi actor, UUID phiên trong action, thời điểm và IP.
  Chỉ dùng RUNNING/COMPLETED, tối đa một RUNNING cho một trạm hiện có.

## 4. Frontend

Giữ CSS/phong cách cũ. permissions.js chỉ phục vụ trình bày; backend là nơi cấp quyền.
Guest xem Demo có nhãn rõ, không có nút phiên thật/admin. Operator vào dữ liệu thật
sau login, có tạo/kết thúc/CSV; Admin có thêm trang tài khoản và nhật ký.
Login/refresh dùng `/api/auth/me`, không tin role từ localStorage. Token và dữ liệu
thật không ghi localStorage. Logout/401 xóa dữ liệu thật, bảng admin và dialog rồi
về Demo/Login. Revision/identity guard chặn phản hồi cũ tái đưa dữ liệu sau logout.
401 hiển thị hết phiên; 403 báo thiếu quyền/CSRF, không tự nâng role.

## 5. Migration, kiểm tra và rollback

Migration: `backend/src/main/resources/db/migration/V3__operator_roles_and_session_lifecycle.sql`.
Bật `MIGRATE_DATABASE=true` khi khởi động backend để nâng v1/v2 lên v3. Database
mới cần INITIALIZE_DATABASE và bootstrap riêng như trước. Tắt cờ sau khi xác minh.
Không bật cờ thì backend từ chối database cũ với hướng dẫn rõ ràng.
Lần refactor này không áp dụng migration lên database cloud.

Sao lưu bằng pg_dump trước khi nâng; không đưa DSN/mật khẩu vào Git/chat. Ghi lại
số tài khoản theo role, số phiên/kết quả và admin hoạt động. Sau nâng kiểm tra:

```sql
SELECT version FROM schema_version ORDER BY version;
SELECT role,active,count(*) FROM app_users GROUP BY role,active;
SELECT count(*) FROM app_users WHERE role='viewer' AND active; -- 0
SELECT count(*) FROM auth_sessions s JOIN app_users u ON u.id=s.user_id WHERE u.role='viewer'; -- 0
SELECT count(*) FROM sorting_sessions;
SELECT count(*) FROM fruit_results;
```

Viewer cũ được giữ nguyên username/hash/FK/lịch sử, role giữ `viewer` nhưng active=false,
token bị thu hồi và snapshot previous_active lưu ở legacy_viewer_quarantine.
Không tự đổi sang Operator. Constraint chỉ cho admin/operator, cộng ngoại lệ legacy
`viewer AND NOT active`. Backend không xác thực role ngoài Admin/Operator.
Admin thấy “Chờ cấp quyền · tài khoản cũ”, chọn rõ role mới và trạng thái rồi lưu.
API tạo/sửa không chấp nhận viewer/guest; không tồn tại quyền Viewer hoạt động.

Rollback: dừng writer v3, giữ backup, dùng psql ON_ERROR_STOP=1 chạy file
`backend/src/main/resources/db/rollback/V3__operator_roles_and_session_lifecycle.sql`,
rồi chạy artifact backend v2. Operator chuyển về Viewer **đã khóa**; Viewer legacy
vẫn khóa; token liên quan bị thu hồi. Không phục hồi quyền tự động. Hash, tài khoản,
session, kết quả và audit giữ nguyên; bảng metadata/biên nhận v3 được giữ làm bằng
chứng. Schema version trở về v2; không chạy mã v3 trên schema đã rollback.
Admin phải rà quyền trước khi mở lại tài khoản. Test có kiểm tra bảo toàn dữ liệu,
rollback và nâng lại.

## 6. File thay đổi

- Backend: AccessPolicy.java, AuthService.java, Security.java, AdminController.java,
  ApiController.java, SortingService.java, Db.java; migration/rollback v3.
- Frontend: dashboard/permissions.js, app.js, admin.js, index.html, style.css.
- Test: BackendIntegrationTest.java và tests/integration_spring_bridge.py.
- Tài liệu: backend/README.md, ADMIN_GUIDE.md, RENDER_DEPLOY.md, dashboard/README.md,
  camera-bridge/README.md và báo cáo này.

## 7. Kiểm thử

Maven verify chạy PostgreSQL localhost trong schema UUID riêng, không sửa bảng ứng dụng.
Bao gồm Guest 401, Operator vận hành/Admin 403, Admin CRUD, giả role, Origin/CSRF,
logout/thu hồi, account khóa, migration Viewer, rollback, start/end lặp và đồng thời,
ảnh sau khi kết thúc và replay biên nhận cũ. Python unittest kiểm tra AI/bridge.
E2E chạy JAR, HTTP thật, ONNX fixture và bridge; camera/Serial là fixture.
Kiểm tra browser bổ sung Guest/Operator/Admin, refresh/logout/hết phiên và ảnh chụp.
Số test và kết quả thực tế được ghi trong tin nhắn bàn giao sau khi chạy.

## 8. Giới hạn

Tạo/kết thúc phiên chỉ quản lý ghi dữ liệu. Không gửi START/STOP cho ESP32 và không
xác nhận motor/servo đã chạy/dừng. Bridge giữ giao thức hiện có; 409 không có phiên
đi vào nhánh lỗi REJECT đang có. Cần phối hợp giữ/dừng quả và watchdog với nhóm phần
cứng trước khi đổi phiên. Chưa có ACK actuator để chứng minh quả đã vào đúng khay.
Chưa có model đã train hoặc phần cứng thật để kiểm thử cơ khí. Cloud chưa được nâng v3.
