# AutoSort IoT — Băng chuyền phân loại quả quất bằng Cloud AI

**Đây là bộ khung của dự án cho 3 thành viên, không phải hệ thống đã hoàn thiện.**

Mục tiêu cuối: IR phát hiện quả → ESP32 điều khiển dừng đúng vị trí → Điện thoại (IP Webcam) chụp JPEG → Máy tính gửi Internet tới Cloud → AI phân loại GREEN / RIPE / REJECT → ESP32 điều khiển băng chuyền & 2 servo gạt → Dashboard hiển thị kết quả.

## Cấu trúc

| Thư mục | Người phụ trách | Hiện trạng |
|---|---|---|
| `cloud-ai/` | A — AI & Cloud | FastAPI có luồng suy luận ONNX; hiện trả `MOCK` vì chưa có model đã train |
| `training/` | A — AI & Cloud | Notebook Colab, kiểm tra dataset, train YOLO11, export ONNX và kiểm tra parity |
| `tests/` | Cả nhóm | Kiểm thử confidence, xử lý ảnh, chuyển dữ liệu và đóng gói |
| `esp32-controller/` | B — IoT | Chưa viết firmware motor, IR, 2 servo qua Serial USB |
| `camera-bridge/` | B — IoT | Script Python lấy ảnh từ Điện thoại (IP Webcam) và gọi Cloud FastAPI |
| `dashboard/` | C — Web | Đã hoàn thiện giao diện giám sát thời gian thực, quản lý phiên và xuất CSV |
| `hardware/` | C và B | Chứa sơ đồ đấu dây (`wiring.md`), bố trí cơ khí (`layout.md`) |
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
5. Để train, mở [`training/AutoSort_Train.ipynb`](training/AutoSort_Train.ipynb) trên Colab và tải `autosort-training.zip` lên khi được hỏi.

Chỉ dùng dataset `datasets/kumquat/` đã lọc: 1.761 ảnh thuộc `GREEN`, `RIPE`,
`REJECT`. Dataset đã được đưa vào Git để cả nhóm lấy về huấn luyện; ZIP Colab
và các trọng số `.pt` vẫn được bỏ qua.
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
- B: hoàn thiện camera upload HTTPS, ESP32 đọc IR và điều khiển motor/servo, timeout chống gạt nhầm.
- C: lắp cơ khí, dựng Dashboard, thu thập dữ liệu thực và kiểm thử.

**An toàn:** `MOCK` không phải GREEN/RIPE/REJECT; tuyệt đối không để ESP32 gạt servo từ phản hồi MOCK. Không commit mật khẩu Wi-Fi, token hay thông tin thanh toán. Nguồn servo/motor cần được kiểm tra riêng.
