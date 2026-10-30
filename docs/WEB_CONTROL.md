# Điều khiển băng chuyền từ web

Đây là luồng thay thế việc tự bật motor khi mở bridge. Trang vào chỉ có
**đăng nhập**, không còn chế độ demo công khai hoặc nút chuyển sang mô phỏng.
Tên phiên cũ chứa “Phiên quất” được hiển thị thành “Phiên”; không sửa/xóa
lịch sử gốc trong PostgreSQL.

## Vận hành

1. Nạp firmware mới vào ESP32, giữ `Controller.h` và `StationConfig.h` cùng
   thư mục sketch. Xem [chu trình](STATION_CYCLE.md) và [hiệu chỉnh](STATION_CALIBRATION.md).
2. Bật DroidCam USB/webcam hoặc snapshot JPEG trên điện thoại, kiểm tra
   [nguồn camera](DROIDCAM_SETUP.md), `.env` của bridge và cổng COM.
3. Chạy `camera-bridge/bridge.py`. Bridge kiểm tra cloud, kết nối ESP32 và
   đăng ký trạm; **motor vẫn dừng**, chưa tạo phiên dữ liệu.
4. Mở dashboard và đăng nhập Admin hoặc Operator. Khi trạm sẵn sàng:

| Nút | Hành vi sau khi firmware xác nhận |
|---|---|
| Bắt đầu | Tạo phiên mới, chạy băng chuyền |
| Tạm dừng | Dừng motor, giữ nguyên phiên và tiến độ quả đang xử lý |
| Tiếp tục | Chạy tiếp cùng phiên; dùng vị trí/timer đang giữ |
| Kết thúc | Dừng motor, thu servo, về trạng thái chờ và đóng phiên |

Khi đang tạm dừng, nút Bắt đầu đổi thành **Tiếp tục**. Các lần dừng nội bộ
để chụp/chờ AI không phải thao tác Tạm dừng từ người vận hành và không tạo
phiên mới. Thời gian phiên trên web là thời gian từ bắt đầu đến kết thúc,
bao gồm thời gian tạm dừng.

Dashboard hiển thị **đang chờ ESP32 xác nhận** sau khi gửi lệnh. Gửi HTTP
thành công chưa có nghĩa motor đã chạy. Bắt đầu/Tạm dừng/Tiếp tục được khóa
khi có lệnh đang dở; **Kết thúc có thể thay thế lệnh đang chờ**, kể cả Bắt đầu.
Lệnh cũ không được phát lại khi đã bị thay thế hoặc quá hạn.

Kết thúc có thể dừng giữa lúc một quả chưa ra khay. Kiểm tra/lấy quả đang dở
trước khi bắt đầu phiên mới. Đây vẫn là phần cứng **một quả mỗi lượt dispatch**,
không bổ sung hàng đợi nhiều quả. COUNTS của ESP32 là log tích lũy từ lúc
reset; số liệu phiên trên web lấy từ PostgreSQL.

Đóng tab/đăng xuất không tự dừng băng chuyền. Dùng Kết thúc để dừng chủ động.
Ctrl+C tại bridge vẫn dừng/khóa firmware, nhưng lần chạy tiếp cần kết nối lại
và reset board nếu board không tự reset khi mở COM. Sau Kết thúc bình thường
trên web, bridge còn kết nối và có thể Bắt đầu phiên mới, không cần reset.

## Khi tạm dừng

Firmware giữ trạng thái trước khi dừng và thời gian đã đi tới camera/cổng gạt.
Tạm dừng ở giữa hành trình servo giữ nguyên góc hiện tại; Tiếp tục mới đếm
tiếp thời gian giữ góc. Các timer dùng `millis()` được bù khoảng tạm dừng.

Chụp/gọi AI chạy ở worker riêng trên PC; vòng đọc Serial và nhận điều khiển
vẫn hoạt động. Nếu AI hoàn tất khi đang tạm dừng, kết quả được giữ cho đúng
run/đúng mã quả; nó **không tự khởi động motor**. Kết quả đến sau Kết thúc
không được chuyển cho phiên mới hoặc làm chạy lại trạm.

Timing là mô hình thời gian, chưa có encoder xác định vị trí. Cần thử trên
băng tải thật để hiệu chỉnh quán tính dừng, góc servo, khoảng thoát và nguồn.

## Kết nối, lỗi và quyền

- Chỉ tài khoản Admin/Operator đang hoạt động, cookie hợp lệ và CSRF đúng
  mới gửi được lệnh web. Device key nằm trên PC, không nằm trong trình duyệt.
- Bridge có agent UUID mới mỗi lần kết nối. Một bridge đang online giữ quyền
  kết nối trạm; bridge khác không chiếm trạm. Agent cũ không được ACK hoặc
  nhận lệnh của agent mới.
- Kênh cloud dùng HTTP polling, lệnh hết hạn sau 15 giây. Mỗi lần gửi lại
  cùng Idempotency-Key trả biên nhận cũ; không tạo thêm lệnh motor.
- Firmware chỉ ACK sau khi áp dụng đầu ra PWM. Đây là xác nhận phần mềm điều
  khiển, không phải cảm biến chứng minh motor quay/quả đã vào đúng khay.
- Bridge đọc/ghi Serial ở một luồng duy nhất, không gửi lại lệnh đã ghi đủ
  nhưng chưa biết kết quả. Nếu ghi thiếu byte, không nối thêm STOP vào dòng
  có thể dang dở; watchdog ESP32 xử lý độc lập.
- Mất heartbeat trạm trên cloud khoảng 15 giây làm kênh offline và đóng phiên
  với lý do mất kết nối. Job AI riêng vẫn có deadline và lease dữ liệu v4
  90 giây làm lớp dự phòng. Mất heartbeat ESP32 ngoài WAIT_AI dùng watchdog
  5 giây; WAIT_AI dùng watchdog riêng 30 giây.
- Nếu lỗi/không nhận được ACK, web hiển thị lỗi hoặc chưa xác nhận. Kiểm tra
  tại trạm rồi kết nối lại; không giả là đã dừng bình thường. Điều khiển qua
  mạng không thay thế cơ cấu dừng khẩn cấp tại chỗ.

## Giao thức Serial mới

```text
bridge -> ESP32: BRIDGE:CONNECT
ESP32 -> bridge: CONTROLLER:IDLE
bridge -> ESP32: CONTROL:<command-uuid-hex>:START:<run-uuid-hex>
ESP32 -> bridge: ACK:<command-uuid-hex>:RUNNING
ESP32 -> bridge: TRIGGER:<run-uuid-hex>:<counter>
bridge -> ESP32: RESULT:<run-uuid-hex>:<counter>:GREEN|RIPE|REJECT
bridge -> ESP32: CONTROL:<command-uuid-hex>:PAUSE|RESUME|STOP:<run-uuid-hex>
ESP32 -> bridge: ACK:<command-uuid-hex>:PAUSED|RUNNING|IDLE|REJECTED
```

Mỗi dòng ASCII kết thúc newline, 115200 baud, tối đa 127 ký tự trước newline.
Lệnh web có ID chống áp dụng lặp trong một lượt kết nối; RESULT có run ID và
counter. Không nhận SORT cũ không có ID khi đang ở chế độ web. Không tuyên bố
servo exactly-once khi mất nguồn hoặc khi không có cảm biến ở khay.

## Backend và triển khai

Trạng thái trạm được lưu trong `station_state`, lệnh/biên nhận trong
`station_commands`. Thao tác điều khiển dùng khóa riêng, không phải chờ cùng
khóa enqueue với tác vụ AI. Tạo/đóng phiên vẫn giữ giao dịch PostgreSQL và
chống ghi kết quả sang phiên mới như v4.

- Web: GET `/api/station`, POST `/api/station/commands` với action, revision,
  Idempotency-Key, cookie và X-CSRF-Token.
- Bridge: `/device/station/{agent}/register`, `/poll`, `/ack/{command}`, `/fault`,
  bảo vệ bởi X-API-Key.
- Schema **v5**: migration `V5__web_station_control.sql` chỉ thêm bảng, không
  xóa lịch sử/tài khoản/model. Dùng `MIGRATE_DATABASE=true` khi deploy.
- Sau deploy, `/health` phải có `web_control_supported=true`. Cần cập nhật
  backend, bridge và firmware cùng nhau. Không dùng gói firmware v4 cũ cho
  bridge web mới. Model v1 và dữ liệu huấn luyện cũ không bị thay đổi.

Bản này đã được kiểm thử cục bộ; xác nhận `/health.web_control_supported=true`
trên dịch vụ sau mỗi lần triển khai trước khi vận hành. Kiểm thử gồm
Java/PostgreSQL thật, C++ state machine, build ESP32, Python agent, Chrome
desktop/mobile và E2E web → bridge → ONNX → PostgreSQL → Serial fixture.
Camera, motor/servo và cảm biến thật chưa được kiểm thử trong lượt này.
