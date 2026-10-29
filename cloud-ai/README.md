# ONNX worker nội bộ

Backend HTTP hiện ở [`backend/`](../backend/README.md), viết bằng Java Spring Boot.
Thư mục này giữ **AI Python**, ảnh mẫu và vị trí model để không đổi pipeline train.
Không chạy Uvicorn hoặc FastAPI nữa.

`worker.py` nhận JSON từng dòng qua stdin, trả JSON từng dòng qua stdout;
Spring Boot sở hữu tiến trình này. Worker chỉ làm health/suy luận, không mở cổng
mạng, không xác thực người dùng và không kết nối PostgreSQL.
Không chạy worker như một API public riêng.

Đặt `best.onnx` cùng `classes.json` vào `cloud-ai/model/` và khởi động lại backend.
Model cần input NCHW float32 `(1,3,imgsz,imgsz)` và đầu ra xác suất `(1,3)` theo
đúng thứ tự `classes.json`: đủ `GREEN`, `RIPE`, `REJECT`. Không softmax lần hai.
Xử lý ảnh vẫn dùng `inference.py`: EXIF/RGB, resize bilinear giữ tỷ lệ, center crop,
float32 chia 255. Confidence dưới ngưỡng chuyển `REJECT`.

Thiếu model/metadata hoặc nạp lỗi: trả rõ `MOCK`, không giả nhãn thật. Camera
Bridge chỉ khởi động với model ONNX thật và từ chối điều khiển từ `MOCK`.
Worker dùng ONNX CPU một thread; Java giới hạn và đóng tiến trình khi dừng.

```powershell
& cloud-ai/.venv312/Scripts/python.exe -m pip install -r cloud-ai/requirements.txt
```

Chạy hệ thống theo [hướng dẫn backend](../backend/README.md).
Train/export/parity xem [AI_TRAIN_DEPLOY.md](../docs/AI_TRAIN_DEPLOY.md).
Giao thức điện thoại/ESP32 xem [camera-bridge](../camera-bridge/README.md).
