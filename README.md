# AutoSort IoT — Băng chuyền phân loại nông sản bằng Cloud AI

Luồng vận hành: **đăng nhập trước khi vào dashboard**, không còn demo công
khai. Chạy bridge để kết nối trạm rồi điều khiển bằng **Bắt đầu / Tạm dừng /
Tiếp tục / Kết thúc** trên web. Bắt đầu mở phiên, Tạm dừng giữ phiên, Kết thúc
đóng phiên sau xác nhận firmware. Xem [WEB_CONTROL.md](docs/WEB_CONTROL.md).
Cần backend schema v5 và cập nhật bridge/firmware đồng bộ;
xem [hướng dẫn triển khai](docs/RENDER_DEPLOY.md) để kiểm tra bản đang chạy.

Backend HTTP dùng **Java 21 / Spring Boot**, PostgreSQL và Spring Security.
AI ONNX chạy bằng Python worker nội bộ. Phần cứng và model cần được kiểm thử
bằng camera tại trạm trước khi kết luận toàn bộ hệ thống hoạt động thực tế.

Luồng chuẩn hóa và huấn luyện **một detector ba lớp** từ bộ bàn giao mới nằm ở
[AI_DETECTION_TRAINING.md](docs/AI_DETECTION_TRAINING.md). Pipeline classification
cũ vẫn được giữ để tái tạo; ba detector một lớp không thể thay trực tiếp vào nó.
Model thử nghiệm unified-v1 đã được train và đánh giá; xem
[kết quả cùng giới hạn](docs/AI_DETECTION_RESULTS.md). Model được bàn giao riêng,
không tự động cài vào dịch vụ cloud.

Mục tiêu cuối: IR phát hiện quả → ESP32 điều khiển dừng đúng vị trí → Điện thoại (IP Webcam) chụp JPEG → Máy tính gửi Internet tới Cloud → AI phân loại GREEN / RIPE / REJECT → ESP32 điều khiển băng chuyền & 2 servo gạt → Dashboard hiển thị kết quả.

## Cấu trúc

| Thư mục | Người phụ trách | Hiện trạng |
|---|---|---|
| `backend/` | Cloud & Web | Spring Boot: API, dashboard, auth/admin, PostgreSQL và idempotency |
| `cloud-ai/` | AI | Python ONNX worker nội bộ; trả `MOCK` khi chưa cài model hợp lệ vào `cloud-ai/model/` |
| `training/` | A — AI & Cloud | Notebook Colab, kiểm tra dataset, train YOLO11, export ONNX và kiểm tra parity |
| `tests/` | Cả nhóm | Kiểm thử confidence, xử lý ảnh, chuyển dữ liệu và đóng gói |
| `esp32-controller/` | B — IoT | Firmware USB Serial đã ghép giao thức bridge; cần nạp và hiệu chỉnh trên băng tải thực |
| `camera-bridge/` | B — IoT | Python lấy ảnh từ điện thoại và gọi Cloud Spring Boot |
| `dashboard/` | C — Web | Đã hoàn thiện giao diện giám sát thời gian thực, quản lý phiên và xuất CSV |
| `hardware/` | B — IoT | Chờ tài liệu phần cứng chính thức từ thành viên phụ trách |
| `docs/` | Cả nhóm | Hướng dẫn train/deploy và nguồn dữ liệu |

**Camera của dự án là điện thoại, không phải ESP32-CAM.** ESP32 DevKit chỉ đọc
cảm biến và điều khiển motor/servo. Thư mục giữ chỗ `esp32-camera/` đã được bỏ.
Bridge có cấu hình `.env`, kiểm tra model thật, retry HTTP có chống ghi trùng và
nhật ký trigger để tránh gửi lại lệnh. Xem [hướng dẫn camera điện thoại và giao thức
bàn giao firmware](camera-bridge/README.md).
Firmware từ bộ bàn giao phần cứng đã được chuyển sang USB Serial tại
[`esp32-controller/AutoSortSerial`](esp32-controller/README.md), có CONTROL/ACK,
heartbeat và watchdog AI. Mỗi lượt chỉ xử lý một quả, chưa xác nhận vận hành
thực trên cơ khí của nhóm.
Phiên dữ liệu [tạo khi Bắt đầu trên web, đóng sau Kết thúc](docs/WEB_CONTROL.md);
Tạm dừng/Tiếp tục giữ nguyên phiên. Tính năng cần backend schema v5, bridge và firmware
được cập nhật đồng bộ; kiểm tra `/health.web_control_supported=true` trước khi vận hành.

## Bắt đầu ngay (Người A)

1. Cài Java 21, Maven 3.9+, Python 3.12 và PostgreSQL.
2. Cài phụ thuộc Python cho AI worker bằng `pip install -r cloud-ai/requirements.txt`.
3. Cấu hình `backend/.env`, build/chạy Spring Boot theo [`backend/README.md`](backend/README.md).
4. Mở `http://127.0.0.1:8000/dashboard/` và đăng nhập. Camera Bridge cần `DEVICE_API_KEY`.
5. Gửi `kumquat-dataset-only.zip` cho người phụ trách huấn luyện; gói chỉ chứa dataset, không kèm code train. Nếu dùng notebook có sẵn của dự án, xem cách đóng gói riêng trong [`docs/AI_TRAIN_DEPLOY.md`](docs/AI_TRAIN_DEPLOY.md).

Chỉ giữ một dataset tại **`datasets/kumquat/`**, gồm **1.347 ảnh** đã rà soát:
126 ảnh đổi sang `REJECT` theo tiêu chí loại cả quả xấu ngoại hình, 414 ảnh
cách ly. **`kumquat-dataset-only.zip`** là bản nén để gửi người phụ trách train.
Nhật ký và ảnh loại nằm trong `docs/dataset-review-2026-10-27.zip`; các thư mục
bản gốc, bản trung gian và bản giải nén trùng đã được dọn. Xem
[kết quả và giới hạn](docs/DATASET_REVIEW.md).
Xem [nguồn và cách tạo lại dữ liệu](docs/PUBLIC_DATASET.md), cùng
[hướng dẫn train và chạy API](docs/AI_TRAIN_DEPLOY.md).

Chạy kiểm thử từ thư mục gốc sau khi cài các phụ thuộc của `cloud-ai`:

```powershell
.\cloud-ai\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Cài `cloud-ai/requirements-dev.txt` cho kiểm thử Python. Đặt
`AUTOSORT_TEST_DATABASE_URL` rồi chạy `mvn -f backend/pom.xml verify` để kiểm thử
API Java với PostgreSQL riêng; xem [`backend/README.md`](backend/README.md).

## Các bước phát triển về sau

- A: chạy huấn luyện, kiểm tra PyTorch–ONNX và đưa model vào API. Luồng ảnh hiện dùng HTTP request/response có Idempotency-Key.
- B: bàn giao firmware và tài liệu phần cứng chính thức, thống nhất giao thức với Camera Bridge để kiểm thử tích hợp.
- C: lắp cơ khí, dựng Dashboard, thu thập dữ liệu thực và kiểm thử.

**An toàn:** `MOCK` không phải GREEN/RIPE/REJECT; tuyệt đối không để ESP32 gạt servo từ phản hồi MOCK. Không commit mật khẩu Wi-Fi, token hay thông tin thanh toán. Nguồn servo/motor cần được kiểm tra riêng.
