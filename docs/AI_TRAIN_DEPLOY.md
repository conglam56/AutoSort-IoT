# Hướng Dẫn Huấn Luyện AI Và Triển Khai ONNX Lên Cloud Cho AutoSort IoT

Tài liệu này cung cấp quy trình từng bước từ việc tổ chức dataset quất, huấn luyện mô hình YOLO11 Classification trên Google Colab GPU miễn phí, xuất mô hình ONNX Runtime và tích hợp vào FastAPI Web Service trên Render Free.

---

## 1. Tổng Quan Kiến Trúc

```
+-------------------------------------------------------------+
| Giai Đoạn 1: Chuẩn Bị & Huấn Luyện (Google Colab / Local)   |
|                                                             |
|   ZIP COCO nguồn (989 ảnh)                                 |
|        │                                                    |
|        ▼ (import_roboflow.py: cắt quả, lọc, giữ tập nguồn)    |
|   datasets/kumquat/                                         |
|        │                                                    |
|        ▼ (train.py: YOLO11n-cls, 224x224, 30 epochs)        |
|   runs/autosort/yolo11-cls/weights/best.pt                  |
|        │                                                    |
|        ▼ (export_onnx.py: PyTorch -> ONNX & classes.json)   |
|   cloud-ai/model/best.onnx + classes.json                   |
+-------------------------------------------------------------+
                                │
                                ▼ Push code + model lên GitHub
+-------------------------------------------------------------+
| Giai Đoạn 2: Cloud Suy Luận (Render Free Web Service)       |
|                                                             |
|   FastAPI (main.py) + ONNX Runtime (CPU)                    |
|   - Đo bộ nhớ và thời gian xử lý với model thực tế         |
|   - Luồng CPU đơn: intra_op_num_threads = 1                |
|   - Tự động fallback MOCK nếu chưa có model                 |
+-------------------------------------------------------------+
```

---

## 2. Dataset Hiện Có

Chỉ dùng `datasets/kumquat/`, gồm 1.761 ảnh đã lọc và chia tập:

```text
datasets/kumquat/
├── train/  (1.505 ảnh)
├── val/    (193 ảnh)
└── test/   (63 ảnh)
```

Mỗi tập có ba nhãn `GREEN`, `RIPE`, `REJECT`. Không cần tạo `dataset-goc/`,
`dataset_raw/` hoặc chia dữ liệu lại trước khi train. Các bản trung gian đã được dọn.
Chi tiết nguồn, số lượng theo nhãn và cách tái tạo nằm trong
[PUBLIC_DATASET.md](PUBLIC_DATASET.md).

Đã có sẵn `autosort-training.zip` và `training/AutoSort_Train.ipynb`. Mở notebook
trên Colab, chọn T4 GPU và chạy từng ô để bắt đầu huấn luyện.

---

## 3. Huấn Luyện Trên Google Colab

Gói `autosort-training.zip` đã được tạo. Chỉ chạy lệnh sau khi cần đóng gói lại,
với tên đầu ra mới nếu gói cũ vẫn còn:
```powershell
python training/package_colab.py --dataset datasets/kumquat --output autosort-training.zip
```

1. Mở [Google Colab](https://colab.research.google.com/) và tải notebook
   `training/AutoSort_Train.ipynb` lên.
2. Chọn **Runtime → Change runtime type → T4 GPU** nếu khả dụng.
3. Chạy từng ô từ trên xuống. Chọn `autosort-training.zip` khi notebook yêu cầu.
4. Notebook kiểm tra dataset, huấn luyện 30 epochs, xuất ONNX và đối chiếu ba ảnh mẫu.
5. Nếu các bước đạt, tải `autosort-model-artifacts.zip` về. Gói chứa `best.pt`,
   `best.onnx`, `classes.json`, kết quả train và thông tin nguồn dữ liệu.

Đường dẫn run mới nhất nằm trong `runs/autosort/latest_run.json`; notebook tự
đọc đường dẫn này để tránh dùng nhầm model của lần chạy trước. Nếu không có GPU,
notebook dùng CPU và quá trình huấn luyện sẽ chậm hơn.

---

## 4. Kiểm Thử Parity (PyTorch vs ONNX)

Sau khi tải các file về, đặt `best.onnx` và `classes.json` vào thư mục `cloud-ai/model/`.
Giữ `best.pt` tại đường dẫn truyền vào `--weights`. Ba ảnh trong `cloud-ai/` chỉ là
ảnh kiểm thử; chúng không thay thế dataset huấn luyện hoặc chứng minh độ chính xác.

API và công cụ parity dùng chung `cloud-ai/inference.py`:

- Chuyển RGB, xử lý hướng EXIF, resize cạnh ngắn về `imgsz` bằng bilinear rồi cắt giữa.
- Chuyển sang tensor liên tục `float32`, dạng `(1, 3, imgsz, imgsz)`, chia 255.
- Đọc trực tiếp xác suất từ YOLO classification ONNX, không chạy softmax lần hai.
- Kiểm tra số lớp, giá trị hữu hạn, khoảng `[0, 1]` và tổng xác suất gần 1.

Quy tắc resize/crop theo [Ultralytics classify_transforms](https://docs.ultralytics.com/reference/data/augment/#ultralytics.data.augment.classify_transforms);
đầu ra export là xác suất theo [Ultralytics Classify](https://docs.ultralytics.com/reference/nn/modules/head/#ultralytics.nn.modules.head.Classify).
Model có transform tùy chỉnh cần được đối chiếu lại; công cụ parity kiểm tra cả tensor
đầu vào thực tế của Ultralytics để phát hiện khác biệt giữa các phiên bản/transform.

Chạy kiểm tra tính nhất quán giữa mô hình gốc PyTorch và mô hình ONNX:
```powershell
python training/check_parity.py --weights runs/autosort/yolo11-cls/weights/best.pt --onnx cloud-ai/model/best.onnx --classes cloud-ai/model/classes.json
```
Mặc định, lệnh kiểm tra mọi ảnh trong `cloud-ai/`, bao gồm `quatsample.jpg`,
`reject.jpg` và `ripe.jpg`. Có thể chọn riêng nhiều ảnh bằng
`--image cloud-ai/quatsample.jpg cloud-ai/reject.jpg cloud-ai/ripe.jpg`.

Mỗi ảnh phải có sai số tensor đầu vào tối đa `1e-6`, sai số xác suất tối đa
`1e-3` và nhãn top-1 trùng nhau. Thứ tự lớp trong metadata phải khớp với PyTorch.
Lệnh trả mã thoát `1` nếu kiểm tra thất bại hoặc thiếu model/metadata, và `0` khi
tất cả ảnh đạt. Cần cài `training/requirements.txt` để chạy với model thật.

Kiểm thử hồi quy (không cần model, dùng xác suất mô phỏng và ảnh JPEG thật):

```powershell
.\cloud-ai\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Kiểm thử này kiểm tra confidence, ngưỡng `0.70`, resize/crop, ảnh đầu vào và
khả năng phát hiện sai lệch của công cụ parity; không đo chất lượng phân loại.

---

## 5. Chạy Thử FastAPI Local

Cài đặt phụ thuộc cho service:
```powershell
pip install -r cloud-ai/requirements.txt
```

Khởi chạy FastAPI:
```powershell
python -m uvicorn main:app --app-dir cloud-ai --host 127.0.0.1 --port 8000 --reload
```

### Kiểm tra Health Check:
Truy cập `http://127.0.0.1:8000/health`:
```json
{
  "status": "ok",
  "service": "quat-sort-ai",
  "mode": "onnx",
  "model_ready": true,
  "classes": ["GREEN", "REJECT", "RIPE"],
  "model_version": "yolo11n-cls-kumquat-v1",
  "threshold": 0.7
}
```

### Kiểm tra Inference:
Gửi ảnh qua Swagger UI tại `http://127.0.0.1:8000/docs` hoặc bằng curl/PowerShell:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/infer" -Method Post -Form @{
    fruit_id = "F0001";
    camera_id = "cam01";
    image = Get-Item "cloud-ai\quatsample.jpg";
}
```

---

## 6. Đưa Lên Render Web Service

1. Đảm bảo cấu trúc thư mục gồm:
   ```
   AutoSort IoT/
   └── cloud-ai/
       ├── main.py
       ├── inference.py
       ├── requirements.txt
       └── model/
           ├── best.onnx
           └── classes.json
   ```
2. Cấu hình service với thư mục gốc `cloud-ai`, cài `requirements.txt` và chạy
   `uvicorn main:app --host 0.0.0.0 --port $PORT` trong môi trường triển khai.
3. Đưa model và metadata vào bản triển khai, rồi kiểm tra `/health` trả
   `"mode":"onnx"`, `"model_ready":true` trước khi thử `/infer`.
4. Đo thời gian suy luận, bộ nhớ và thời gian khởi động trên gói hosting thực tế.
   Firmware cần có timeout/retry và cách dừng băng chuyền khi dịch vụ chưa sẵn sàng.
