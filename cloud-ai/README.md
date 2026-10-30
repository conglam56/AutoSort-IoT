# ONNX worker nội bộ

Backend HTTP hiện ở [`backend/`](../backend/README.md), viết bằng Java Spring Boot.
Thư mục này giữ **AI Python**, ảnh mẫu và vị trí model để không đổi pipeline train.
Không chạy Uvicorn hoặc FastAPI nữa.

`worker.py` nhận JSON từng dòng qua stdin, trả JSON từng dòng qua stdout;
Spring Boot sở hữu tiến trình này. Worker chỉ làm health/suy luận, không mở cổng
mạng, không xác thực người dùng và không kết nối PostgreSQL.
Không chạy worker như một API public riêng.

Đặt `best.onnx` cùng `classes.json` vào `cloud-ai/model/` và khởi động lại backend.
Input là NCHW float32 `(1,3,imgsz,imgsz)`; thứ tự lớp trong `classes.json` phải
đủ `GREEN`, `RIPE`, `REJECT`. Worker hỗ trợ hai hợp đồng:

- `task=classify` (mặc định cho metadata cũ): đầu ra xác suất `(1,3)`, xử lý
  EXIF/RGB, resize bilinear và center crop như trước. Không softmax lần hai.
- `task=detect`, `output_format=yolo11_raw`: đầu ra `(1,7,anchors)`, letterbox
  OpenCV, class-aware NMS và quyết định cho một quả trong ROI. REJECT đủ tin cậy
  được ưu tiên trên cùng quả. Chỉ khung đạt ngưỡng (mặc định >= 70%) được xét
  khi kiểm tra nhiều mục tiêu; khung dưới ngưỡng không phủ quyết quả đã đạt.
  GREEN/RIPE cùng một quả lấy nhãn có điểm cao nhất đã đạt ngưỡng.
  Nhiều mục tiêu đủ ngưỡng hoặc độ tin cậy thấp chuyển
  nhánh REJECT với `decision_reason=LOW_CONFIDENCE` và `decision_detail` cụ thể.

Không đổi tên một detector một lớp thành model ba lớp. Chuẩn bị dữ liệu và
train/export detector theo [AI_DETECTION_TRAINING.md](../docs/AI_DETECTION_TRAINING.md).

Thiếu model/metadata hoặc nạp lỗi: trả rõ `MOCK`, không giả nhãn thật. Camera
Bridge chỉ khởi động với model ONNX thật và từ chối điều khiển từ `MOCK`.
Worker dùng ONNX CPU một thread; Java giới hạn và đóng tiến trình khi dừng.

```powershell
& cloud-ai/.venv312/Scripts/python.exe -m pip install -r cloud-ai/requirements.txt
```

Chạy hệ thống theo [hướng dẫn backend](../backend/README.md).
Train/export/parity xem [AI_TRAIN_DEPLOY.md](../docs/AI_TRAIN_DEPLOY.md).
Giao thức điện thoại/ESP32 xem [camera-bridge](../camera-bridge/README.md).
