# AutoSort IoT — Băng chuyền phân loại quả quất bằng Cloud AI

**Đây là bộ khung của dự án cho 3 thành viên, không phải hệ thống đã hoàn thiện.**

Mục tiêu cuối: IR phát hiện quả → ESP32 điều khiển dừng đúng vị trí → Điện thoại (IP Webcam) chụp JPEG → Máy tính gửi Internet tới Cloud → AI phân loại GREEN / RIPE / REJECT → ESP32 điều khiển băng chuyền & 2 servo gạt → Dashboard hiển thị kết quả.

## Cấu trúc

| Thư mục | Người phụ trách | Hiện trạng |
|---|---|---|
| `cloud-ai/` | A — AI & Cloud | FastAPI có luồng suy luận ONNX; hiện trả `MOCK` vì chưa có model đã train |
| `training/` | A — AI & Cloud | Notebook Colab, kiểm tra dataset, train YOLO11, export ONNX và kiểm tra parity |
| `tests/` | Cả nhóm | Kiểm thử confidence, xử lý ảnh, chuyển dữ liệu và đóng gói |
| `esp32-controller/` | B — IoT | Chờ tích hợp firmware chính thức do thành viên phần cứng quản lý |
| `camera-bridge/` | B — IoT | Script Python lấy ảnh từ Điện thoại (IP Webcam) và gọi Cloud FastAPI |
| `dashboard/` | C — Web | Đã hoàn thiện giao diện giám sát thời gian thực, quản lý phiên và xuất CSV |
| `hardware/` | B — IoT | Chờ tài liệu phần cứng chính thức từ thành viên phụ trách |
| `docs/` | Cả nhóm | Hướng dẫn train/deploy và nguồn dữ liệu |

## Bắt đầu ngay (Người A)

1. Mở thư mục **`cloud-ai`** trong VS Code hoặc chuyển Terminal tới nó.
2. Trong PowerShell, chạy:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Cấu hình PostgreSQL và `.env`, chạy `manage.py init-db`, tạo tài khoản rồi
   khởi động API theo [`cloud-ai/README.md`](cloud-ai/README.md).
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

Cài `cloud-ai/requirements-dev.txt` để có thư viện kiểm thử HTTP. Đặt
`AUTOSORT_TEST_DATABASE_URL` để chạy thêm kiểm thử xác thực với PostgreSQL thật;
xem cách chạy trong [`cloud-ai/README.md`](cloud-ai/README.md).

## Các bước phát triển về sau

- A: chạy huấn luyện, kiểm tra PyTorch–ONNX, đưa model vào API và bổ sung MQTT/định danh request.
- B: bàn giao firmware và tài liệu phần cứng chính thức, thống nhất giao thức với Camera Bridge để kiểm thử tích hợp.
- C: lắp cơ khí, dựng Dashboard, thu thập dữ liệu thực và kiểm thử.

**An toàn:** `MOCK` không phải GREEN/RIPE/REJECT; tuyệt đối không để ESP32 gạt servo từ phản hồi MOCK. Không commit mật khẩu Wi-Fi, token hay thông tin thanh toán. Nguồn servo/motor cần được kiểm tra riêng.
