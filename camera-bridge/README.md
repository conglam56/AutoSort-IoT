# Bridge điện thoại → Cloud AI → ESP32

Camera là điện thoại qua **DroidCam USB/webcam** hoặc dịch vụ snapshot JPEG,
không dùng ESP32-CAM. Có chế độ video mẫu để thử khi chưa có thiết bị.
Xem [hướng dẫn DroidCam và thử offline](../docs/DROIDCAM_SETUP.md).
Bridge nhận lệnh từ dashboard đã đăng nhập và điều khiển ESP32 qua USB Serial.
**Mở bridge chỉ kết nối trạm, motor vẫn dừng.** Xem [WEB_CONTROL.md](../docs/WEB_CONTROL.md).

## Cài và chạy

```powershell
py -3.12 -m venv camera-bridge/.venv
& camera-bridge/.venv/Scripts/python.exe -m pip install -r camera-bridge/requirements.txt
if (!(Test-Path -LiteralPath camera-bridge/.env)) {
    Copy-Item camera-bridge/.env.example camera-bridge/.env
}
```

Mẫu `.env.example` đã có trong Git và mặc định dùng **DroidCam USB trên Windows**
(`webcam`, backend `msmf`). Trước khi chạy, thay `SERIAL_PORT` bằng cổng ESP32
thật và `DEVICE_API_KEY` bằng key thiết bị hiện có của cloud, nhận riêng từ
người quản lý dự án. Key này không phải mật khẩu Admin/Operator. Xác nhận lại
`CAMERA_INDEX` trên từng laptop; số 1 chỉ là giá trị đã thử trên máy dự án.
Lệnh trên giữ nguyên `.env` nếu đã có; không đưa `.env` riêng lên Git.

Cấu hình `.env` (không commit key/mật khẩu):

| Biến | Giá trị cần điền |
|---|---|
| CAMERA_SOURCE | `webcam` cho DroidCam, `phone` cho URL JPEG, `video` chỉ để thử |
| CAMERA_INDEX / CAMERA_BACKEND | Index webcam đã xác nhận bằng `camera_check.py`; backend `auto`, `dshow`, `msmf` |
| PHONE_IP_WEBCAM_URL | Chỉ dùng với `phone`: URL snapshot JPEG điện thoại, ví dụ http://192.168.1.15:8080/shot.jpg |
| CAMERA_VIDEO_PATH | Chỉ dùng với `video`: file video trên laptop |
| SERIAL_PORT | Cổng ESP32, ví dụ COM3 |
| SERIAL_BAUD_RATE | 115200, phải khớp firmware |
| CAMERA_ID | Định danh ổn định, ví dụ phone_cam01 |
| CLOUD_INFER_URL | https://autosort-iot-java.onrender.com/infer |
| DEVICE_API_KEY | Key thiết bị riêng từ cloud, không phải mật khẩu đăng nhập |
| JOB_TIMEOUT_SECONDS | Mặc định 20, tối đa 25 với firmware watchdog AI 30 giây |

Với `phone`, điện thoại và PC cần truy cập cùng mạng nội bộ. URL phải trả JPEG,
không phải trang xem camera hay MJPEG. Với `webcam`, DroidCam Client cung cấp
camera trên laptop; không cần URL điện thoại. Ảnh gửi API tối đa 1.000.000
byte và 25 megapixel. Video mẫu không được dùng cho chế độ điều khiển motor.

```powershell
& camera-bridge/.venv/Scripts/python.exe camera-bridge/bridge.py
```

Bridge kiểm tra `/ready`, `/health`, model ONNX thật và API chống trùng trước
khi kết nối ESP32. Backend cần schema **v5**, firmware mới phải trả
`CONTROLLER:IDLE` sau `BRIDGE:CONNECT`. Sau đó đăng nhập web để Bắt đầu,
Tạm dừng/Tiếp tục hoặc Kết thúc. Không mở Serial Monitor đồng thời.

## Nếu bridge dừng ngay khi khởi động

Bridge ghi lần lượt: kiểm tra cloud, mở Serial, chờ ESP32 và trạm đã kết nối.
Với `BridgeError`, dòng cuối có nguyên nhân cụ thể thay vì chỉ tên exception.
HTTP 401/403 khi đăng ký trạm: kiểm tra device key khớp cloud. Lỗi xung đột
`BRIDGE_ALREADY_CONNECTED`: kiểm tra còn bridge khác đang giữ trạm.
Không gửi `.env` hoặc key vào log/chat để chẩn đoán.

Firmware Arduino `Serial.println` trả CRLF. Bridge nhận cả LF và CRLF cho
bắt tay IDLE; không chấp nhận dòng chưa có newline. Nếu ESP32 đã bị khóa lỗi
từ lượt thử thất bại, dừng bridge, kiểm tra trạm tại chỗ, reset ESP32 bằng EN
hoặc kết nối lại USB rồi chạy bridge mới. Không dùng lệnh web để bỏ qua lỗi
đang khóa. Khi nạp firmware hoặc mở Serial Monitor, đóng bridge trước để
tránh hai chương trình chiếm cùng cổng COM.

USB có thể trả một dòng thành nhiều đoạn sau mỗi timeout đọc 100 ms. Bridge
ghép các đoạn tới newline, tối đa 128 byte và 1 giây kể từ đoạn đầu; đoạn
chưa đủ không được xử lý thành ACK/TRIGGER. Trong lúc ghép, bridge vẫn kiểm
tra deadline ACK và gửi heartbeat, ưu tiên hoàn tất dòng trước HTTP polling.
Lỗi dòng quá dài hoặc quá 1 giây vẫn dừng trạm; không bỏ giới hạn hoặc gửi
lại lệnh servo để thử lại.

## Điều khiển và kết quả

- Mỗi kết nối bridge có agent UUID riêng, được kiểm tra lease trên cloud.
- Mỗi lệnh web có command UUID, hạn 15 giây và ACK của firmware.
- Bắt đầu tạo một run/phiên mới trước khi gửi START; Kết thúc đóng phiên sau ACK IDLE.
- Tạm dừng giữ cùng phiên và timer; AI xong không tự chạy lại motor.
- RESULT có run UUID + counter, không đưa kết quả cũ vào lượt mới.
- Chỉ luồng chính ghi/đọc Serial. Chụp ảnh/gọi cloud chạy ở worker riêng để
  vẫn nhận điều khiển trong lúc AI đang xử lý. Không gửi lại một lệnh Serial
  có trạng thái ghi/ACK chưa chắc chắn.
- Lỗi Serial/PWM, thiếu ACK hoặc hết lease làm kênh điều khiển dừng/khóa.
  Xử lý quả dở, reset ESP32 và chạy lại bridge; không xóa nhật ký để chạy lại quả cũ.
- Ctrl+C là dừng bridge tại chỗ, khóa firmware; cách kết thúc vận hành bình
  thường là Kết thúc trên web để bridge còn online và có thể mở phiên mới.

Nhật ký `.local/bridge-state.sqlite3` chống xử lý lặp trigger qua restart;
PostgreSQL cloud vẫn lưu kết quả phân loại. Retry HTTP cùng ảnh/fruit_id/camera_id,
Idempotency-Key và X-Run-Id; không chụp lại ảnh khi retry, không gửi MOCK xuống máy.

## Thử ảnh khi chưa lắp trạm

```powershell
& camera-bridge/.venv/Scripts/python.exe camera-bridge/bridge.py --manual
```

Chế độ này không mở COM hoặc điều khiển motor, tự mở phiên thử ảnh riêng và
dùng Enter để chụp. Ctrl+C đóng phiên thử. Không dùng cùng lúc với phiên băng tải.

## Kiểm thử và giới hạn

Các test Python dùng HTTP/Serial fixture; E2E dùng Java, ONNX và PostgreSQL
thật với camera/Serial giả lập. Chưa thay thế thử băng tải/điện thoại thực.
Web không phải cơ cấu dừng khẩn cấp; chưa có encoder/cảm biến ở khay để xác
nhận chuyển động hoặc quả đã được gạt đúng. Mỗi lượt chỉ một quả trên băng tải.
