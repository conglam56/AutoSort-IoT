# Phiên tự động theo lượt chạy bridge

**Luồng này đã được thay thế bởi [điều khiển từ web](WEB_CONTROL.md), schema v5.**
Bridge mới chờ Bắt đầu trên web, không tự bật khi mở chương trình. Phần dưới
ghi lại thiết kế v4 trước đó để tham chiếu; không dùng làm hướng dẫn vận hành mới.

Quy tắc đã chốt: **chạy bridge trên PC để bật trạm, Ctrl+C để dừng**.
Dashboard giám sát và xem lịch sử, không cần bấm tạo/kết thúc phiên.
Không suy ra trạng thái từ riêng motor đang quay: các lần motor dừng ngắn
để chụp/chờ AI vẫn nằm trong cùng lượt chạy và cùng phiên dữ liệu.

## Trình tự

1. Bridge kiểm tra database/model ONNX và tạo một run UUID mới trên cloud.
   Cloud tạo đúng một phiên RUNNING cho UUID đó. Tạo phiên phải thành công
   trước khi bridge gửi READY cho ESP32; lỗi cloud thì không arm motor.
2. ESP32 xác nhận `CONTROLLER:RUNNING:<session-id>` sau khi áp dụng đầu ra PWM.
   Đây là xác nhận firmware, không phải cảm biến xác nhận motor quay.
   Nếu thiếu xác nhận, bridge gửi STOP và kết thúc run với lý do lỗi phù hợp.
3. Trigger từ IR chụp ảnh điện thoại và gọi `/infer` với `X-Run-Id`.
   Kết quả được gắn đúng phiên của lượt chạy. Không tạo phiên theo từng quả.
4. Ctrl+C: gửi `BRIDGE:STOP`, đợi firmware trả `FAULT:BRIDGE_STOP`, sau đó
   kết thúc phiên với `NORMAL_STOP`. Chạy lại bridge tạo UUID và phiên mới.
5. Nếu firmware báo lỗi, bridge thoát và ghi `CONTROLLER_FAULT`. Nếu ghi
   Serial bị thiếu byte/lỗi, không gửi lại hoặc nối thêm lệnh STOP vào dòng
   có thể còn dang dở; watchdog firmware xử lý độc lập. Cloud ghi `SERIAL_ERROR`
   hoặc `STOP_UNCONFIRMED`, không gắn nhãn dừng bình thường.

Trong phần cứng hiện tại, chỉ đưa **một quả mỗi lượt dispatch**. Kết thúc
phiên không chứng minh quả đang đi đã vào khay; firmware STOP thu servo và
dừng motor, người vận hành xử lý quả dở trước khi chạy lại.

## Mất điện, kill tiến trình hoặc mất mạng

Bridge gửi heartbeat cloud khoảng 10 giây khi rảnh; inference/chụp ảnh dùng
ngân sách 20 giây mặc định. Cloud dùng lease **90 giây** để không đóng phiên
nhầm trong một lần chờ AI. Khi thiếu heartbeat quá hạn, tác vụ nền khoảng
mỗi 10 giây và các truy vấn phiên sẽ kết thúc run với `CONNECTION_LOST`.
Đây là thời điểm cloud xác định mất liên lạc, không phải thời điểm motor
thực sự ngừng. Scheduler/cloud Free không bảo đảm đóng đúng một giây cố định.

Lỗi mạng lúc đóng phiên có thể khiến bridge chưa nhận được xác nhận: nó ghi
log và lease sẽ kết thúc phiên sau đó. Phiên cũ không được tái sử dụng.
Mất kết nối ESP32 lúc WAIT_AI vẫn theo watchdog độc lập của firmware (30 giây,
đưa quả dở về khay loại rồi khóa). Thời gian này khác với lease dữ liệu cloud.

## API và chống trùng

Các API `/device/runs/{uuid}/start`, `/heartbeat`, `/stop` yêu cầu device key
qua `X-API-Key`; tài khoản đăng nhập không thay thế device key. Key chỉ ở
`.env` trên PC, không đưa vào dashboard hoặc firmware.

- START/STOP gửi lại cùng UUID không tạo hoặc kết thúc thêm phiên khác.
- STOP tới trước START tạo tombstone; START đến muộn không mở lại run đó.
- UUID đã đóng không được mở lại. Run khác không được chiếm một phiên đang chạy.
- Ảnh của run cũ không được ghi vào phiên mới. Replay receipt đã commit vẫn
  trả đúng kết quả cũ; không ghi lại quả hoặc đổi session. Bridge còn kiểm tra
  `run_id` trong kết quả trước khi dùng nhãn.
- Lệnh SORT vẫn không có ID/ACK cho từng quả; không tuyên bố servo exactly-once.
  START/STOP chỉ có xác nhận trạng thái điều khiển ở mức firmware.

Phiên tự động do bridge quản lý, API end bằng tài khoản không được đóng nó
khi motor có thể còn chạy. API tạo phiên cũ giữ tương thích cho client cũ,
nhưng dashboard đã bỏ nút tạo mới. Nếu còn phiên thủ công từ bản cũ, Admin
có nút **Đóng phiên cũ** để chuyển sang vận hành tự động; lịch sử giữ nguyên.
Bridge không tự kết thúc phiên cũ của người khác để chiếm trạm.

`--manual` cũng tự tạo phiên riêng tên **Thử ảnh điện thoại**, không mở Serial
hoặc bật băng tải. Một heartbeat nền riêng giữ phiên trong lúc chờ Enter;
Ctrl+C kết thúc phiên thử. Không trộn thử ảnh với phiên băng tải đang chạy.

## Triển khai đồng bộ

Bản này cần **backend schema v4 + bridge mới + firmware mới**. Hiện việc sửa
và kiểm thử là cục bộ; không tự deploy hoặc ghi vào PostgreSQL production.

1. Deploy backend mới với `MIGRATE_DATABASE=true`. Migration
   `V4__automatic_device_runs.sql` chỉ thêm bảng/cột, không xóa lịch sử hoặc
   đổi mật khẩu. Lần tạo database mới vẫn dùng INITIALIZE_DATABASE như trước.
2. Kiểm tra `/ready` và `/health` có `automatic_sessions_supported=true`.
3. Nạp firmware mới, giữ `Controller.h` cùng sketch. Chạy bridge mới với
   `.env` hiện có, kiểm tra camera/cổng COM/device key, trạm trống rồi bắt đầu.
4. Trên dashboard không bấm tạo phiên. Theo dõi phiên mới tự xuất hiện;
   Ctrl+C và kiểm tra phiên chuyển vào lịch sử, lý do dừng bình thường.

Rollback ứng dụng không xóa cột/bảng v4; dữ liệu cũ tiếp tục được giữ. Không
dùng bridge tự động với API cũ chưa có `/device/runs`.

## Kiểm thử

Kiểm thử Java/PostgreSQL dùng cụm localhost và schema riêng: auth thiết bị,
START đồng thời/gửi lại, STOP trước START, hết lease, ảnh đến muộn qua lượt
chạy mới, receipt replay và bảo toàn phiên thủ công cũ. Test bridge kiểm tra
READY sau cloud, STOP khi Ctrl+C, thiếu ACK, lỗi Serial và không nhân đôi lệnh.
E2E chạy Java + ORT thật + PostgreSQL với ảnh/camera/Serial fixture; không dùng
model accuracy hay hoạt động cơ khí làm kết luận từ fixture này. UI kiểm tra
Admin/Operator, phiên tự động/phiên cũ, lý do mất kết nối và màn hình 375 px.
