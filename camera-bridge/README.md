# Camera điện thoại → Cloud AI → ESP32 controller

Camera là **điện thoại cài ứng dụng cung cấp ảnh snapshot JPEG** (ví dụ IP Webcam).
ESP32 DevKit chỉ đọc cảm biến và điều khiển băng tải/servo qua USB Serial.
Dự án không dùng ESP32-CAM; thư mục giữ chỗ `esp32-camera/` đã được bỏ.

```text
ESP32 -- TRIGGER:<boot-id>:<counter> --> Python Bridge
Điện thoại -- JPEG qua Wi-Fi nội bộ --> Python Bridge
Python Bridge -- HTTPS POST /infer --> Render (ONNX + PostgreSQL)
Python Bridge <-- JSON đúng mã quả -- Render
ESP32 <-- SORT:GREEN / SORT:RIPE / SORT:REJECT -- Python Bridge
```

## Cài đặt và cấu hình

Từ thư mục gốc, dùng Python 3.12:

```powershell
py -3.12 -m venv camera-bridge/.venv
& camera-bridge/.venv/Scripts/python.exe -m pip install -r camera-bridge/requirements.txt
Copy-Item camera-bridge/.env.example camera-bridge/.env
```

Sửa `.env` của **camera-bridge**:

- `PHONE_IP_WEBCAM_URL`: URL ảnh JPEG từ điện thoại, ví dụ `http://192.168.1.15:8080/shot.jpg`.
  Điện thoại và máy chạy bridge phải truy cập được nhau trong mạng nội bộ.
  Đây phải là URL snapshot, không phải trang xem camera hoặc luồng MJPEG/video.
- `SERIAL_PORT`: cổng ESP32 thực tế trong Device Manager, ví dụ `COM3`.
- `SERIAL_BAUD_RATE`: mặc định `115200`; phải khớp firmware.
- `CAMERA_ID`: định danh ổn định của camera, mặc định `phone_cam01`.
- `CLOUD_INFER_URL`: mặc định `https://autosort-iot.onrender.com/infer`.
- `DEVICE_API_KEY`: key thiết bị từ cấu hình riêng của cloud, không phải mật khẩu admin.
  Không đưa `.env`, key hoặc mật khẩu vào Git. URL không chứa tài khoản/mật khẩu.

Ảnh phải là JPEG hợp lệ, tối đa **1.000.000 byte**, tối đa **25 megapixel**.
Giảm độ phân giải/chất lượng JPEG trong ứng dụng điện thoại nếu ảnh quá lớn.
Ảnh dùng để phân loại được gửi lên cloud; bridge không chạy model AI tại chỗ.

**Bản bridge này cần API hiện tại và schema v3.** Xem bước nâng schema trong
[`docs/RENDER_DEPLOY.md`](../docs/RENDER_DEPLOY.md). API cũ không công bố
`idempotency_supported=true` nên bridge sẽ từ chối khởi động; không thử gửi lại
POST vào một API chưa hỗ trợ chống trùng.

Operator/Admin phải tạo phiên dữ liệu RUNNING trước khi nhận quả. Sau khi kết thúc phiên, ảnh mới nhận 409 và bridge dùng nhánh lỗi REJECT hiện có; đây không phải lệnh START/STOP thiết bị.

Trước khi mở Serial, bridge kiểm tra `/ready` và `/health`: database sẵn sàng,
`mode=onnx`, `model_ready=true`, `idempotency_supported=true`.
Nếu cloud vẫn `MOCK`, bridge thoát và chưa nhận quả. Thời gian đánh thức cloud
khi khởi động mặc định 90 giây, độc lập với thời gian chờ từng quả.

```powershell
# Có ESP32: không tự chuyển chế độ nếu lỗi Serial.
& camera-bridge/.venv/Scripts/python.exe camera-bridge/bridge.py

# Chỉ kiểm tra camera điện thoại + model thật trên cloud bằng phím Enter.
# Chế độ này không mở cổng Serial và không điều khiển máy.
& camera-bridge/.venv/Scripts/python.exe camera-bridge/bridge.py --manual
```

## Giao thức bàn giao cho người làm phần cứng

Mỗi dòng Serial kết thúc bằng `\n`, nội dung ASCII, tốc độ mặc định 115200.
Các dòng log khác của firmware được bỏ qua. Dòng không hoàn chỉnh hoặc quá dài
làm bridge dừng để kiểm tra kết nối; không nối các mảnh thành trigger giả.

| Chiều | Dòng | Ý nghĩa |
|---|---|---|
| ESP32 → bridge | `TRIGGER:<boot-id>:<counter>` | Quả đã dừng ở vị trí chụp; nhận một quả mỗi lần |
| bridge → ESP32 | `SORT:GREEN` | Kết quả GREEN, thực hiện cổng 1 theo firmware |
| bridge → ESP32 | `SORT:RIPE` | Kết quả RIPE, thực hiện cổng 2 theo firmware |
| bridge → ESP32 | `SORT:REJECT` | Nhãn loại hoặc nhánh xử lý lỗi; đi khay loại theo firmware |

ID sau `TRIGGER:` dài 1–96 ký tự gồm chữ, số, `.`, `_`, `:`, `-`.
`boot-id` phải mới mỗi lần firmware khởi động; `counter` tăng cho từng quả trong
lần khởi động đó. ID **không được dùng lại**, kể cả sau reset.
Nếu gửi lại trigger của cùng quả, dùng nguyên ID đó.

Bridge vẫn đọc `TRIGGER` cũ để tương thích khi tích hợp, nhưng **không thể phân
biệt trigger cũ bị gửi lặp với một quả mới** khi thiếu ID. Firmware nên chuyển sang
trigger có ID để chống trùng đầy đủ. Bridge không sửa hoặc thay thế firmware nhóm bạn.

Firmware phải dừng quả ở vị trí chụp, chỉ cho **một quả đang chờ**, không gửi
trigger của quả tiếp theo trước khi xử lý xong lệnh hiện tại.
Không gửi trigger hàng loạt vào bộ đệm Serial. Lệnh `SORT` giữ định dạng cũ,
chưa có ACK/ID trong phản hồi; không tuyên bố điều khiển servo “exactly once”.

## Mã quả và chống trùng

- Bridge tạo `request_id` UUID mới và `fruit_id=F-<request_id>`; log và nhật ký
  nối `trigger_id` của ESP32 với mã quả nhìn thấy trên dashboard.
- Khi HTTP timeout/mất kết nối hoặc trả 429/500/502/503/504, gửi lại **cùng ảnh,
  cùng fruit_id/camera_id và cùng header `Idempotency-Key`**. Không chụp lại trong
  lần thử lại. Tối đa 3 lần, có chờ tăng dần và tôn trọng Retry-After dạng số giây.
- API lưu kết quả và biên nhận trong **cùng giao dịch PostgreSQL**. Một key hợp lệ
  chỉ ghi một quả, kể cả gửi đồng thời, đổi phiên phân loại hoặc khởi động lại API.
  Dùng key cũ với ảnh/mã quả/camera khác bị trả 409. Key là định danh của một
  yêu cầu, không phải mật khẩu hoặc phương thức xác thực.
- Nhật ký `.local/bridge-state.sqlite3` chỉ giữ định danh/trạng thái điều phối,
  không lưu ảnh, key, mật khẩu hoặc chạy phân tích AI. PostgreSQL cloud vẫn giữ
  dữ liệu phân loại. Giữ file nhật ký qua các lần khởi động, không commit lên Git.
- Trigger có ID đã được nhận sẽ không chụp hoặc gửi lệnh Serial lần nữa. Nếu
  bridge tắt giữa chừng, trạng thái còn `processing`: không tự chạy lại. Người
  vận hành phải kiểm tra/xử lý quả đang dở trước khi cho trạm chạy tiếp.

## Timeout, lỗi và giới hạn điều khiển

`JOB_TIMEOUT_SECONDS` mặc định 20 giây cho chụp ảnh và các lần gọi cloud.
Mỗi lần đọc HTTP tối đa `CLOUD_REQUEST_TIMEOUT_SECONDS` (mặc định 5 giây) và
không vượt thời gian còn lại tại lúc gửi. Kết quả đến sau hạn bị bỏ.
Timeout HTTP là timeout chờ kết nối/đọc, không phải bảo đảm thời gian thực cứng;
firmware phải có watchdog độc lập khi chờ PC/cloud và chốt cách xử lý an toàn.
Ngân sách này phải được thống nhất với thời gian dừng băng tải trước khi chạy máy.

Không gửi nhãn `MOCK` hoặc nhãn tùy ý xuống ESP32. Sai mã quả/request/camera,
JSON lỗi, confidence không hợp lệ hoặc model MOCK đều trở thành nhánh lỗi REJECT.
Nhánh lỗi chỉ được log trong bridge, **không giả thành dự đoán AI trong database**.
Nếu HTTP đã commit nhưng bridge không nhận được kết quả đúng hạn, dashboard có
thể ghi nhãn AI khác với nhánh lỗi thực tế. Hiện chưa có ACK servo để xác nhận
quả đã tới đúng khay; số liệu dashboard là kết quả suy luận, không phải xác nhận cơ khí.

Lỗi mở/đọc/ghi Serial, ghi thiếu byte hoặc lỗi nhật ký khiến bridge dừng với mã lỗi.
Không tự kết nối lại và không gửi lại lệnh vì ESP32 có thể đã nhận một phần/toàn bộ.
Khi bấm Ctrl+C, bridge đóng kết nối; việc đưa trạm về trạng thái an toàn thuộc
watchdog/firmware. Chốt hành vi của `SORT:REJECT` và watchdog với người làm phần cứng.

## Kiểm thử trên máy phát triển

Cài `cloud-ai/requirements-dev.txt`, rồi chạy `python -m unittest discover -s tests -v`.
Các test bridge dùng JPEG thật, HTTP và Serial giả lập. Test PostgreSQL dùng
`AUTOSORT_TEST_DATABASE_URL` và schema tạm riêng, kiểm tra gửi trùng đồng thời,
rollover/restart, rollback và phản hồi mất sau khi cloud đã lưu.
Các test này không thay thế chạy camera điện thoại và băng tải thực tế.
