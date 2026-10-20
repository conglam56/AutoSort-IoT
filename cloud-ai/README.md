# AutoSort IoT — Cloud AI service

FastAPI nhận JPEG tại `/infer` và phân loại bằng ONNX khi có model. Hiện chưa
huấn luyện nên API trả `MOCK`. Không nối phản hồi MOCK với quyết định điều khiển servo.

Hướng dẫn huấn luyện: [AI_TRAIN_DEPLOY.md](../docs/AI_TRAIN_DEPLOY.md).
Nguồn dataset và notebook Colab: [PUBLIC_DATASET.md](../docs/PUBLIC_DATASET.md).

## A. Chạy trên Windows 10/11 bằng PowerShell

Yêu cầu: Python 3.11+ và một ảnh JPEG chụp quả quất tên `quatsample.jpg`.

1. Mở thư mục `cloud-ai/` chứa `main.py` trong VS Code và mở Terminal PowerShell.
2. Chạy:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

3. Truy cập http://127.0.0.1:8000/health; phải thấy `"status":"ok"`.
4. Đặt ảnh `quatsample.jpg` cạnh `main.py` rồi gửi thử:

```powershell
curl.exe -X POST -F "fruit_id=F0001" -F "camera_id=cam01" -F "image=@quatsample.jpg;type=image/jpeg" http://127.0.0.1:8000/infer
```

5. Khi chưa có model, phản hồi có `"fruit_id":"F0001"`, `"label":"MOCK"`,
   `"decision_reason":"MOCK_MODE"` và `"image_bytes":...`.

## B. Bật mô hình đã huấn luyện

Đặt `best.onnx` và `classes.json` từ kết quả export vào `cloud-ai/model/` rồi
khởi động lại API. `/health` phải trả `"mode":"onnx"`, `"model_ready":true`.
Nếu không nạp được model, API ghi lỗi vào log và tiếp tục ở chế độ MOCK.

Luồng ONNX dùng chung xử lý ảnh với công cụ parity, đọc trực tiếp xác suất và
chuyển dự đoán có confidence dưới ngưỡng sang `REJECT`.

## C. Deploy lên Google Cloud Run (tùy chọn)

1. Tạo project trong https://console.cloud.google.com/ và kích hoạt Billing phù hợp. Đặt cảnh báo/ngưỡng chi phí và giới hạn mở rộng. Chú ý cảnh báo ngân sách thường không tự chặn phát sinh phí.
2. Cài Google Cloud CLI: https://cloud.google.com/sdk/docs/install
3. Mở Terminal tại thư mục `cloud-ai/` (không phải thư mục gốc `quat-sort-iot/`) và chạy:

```powershell
gcloud init
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
gcloud run deploy quat-sort-ai --source . --region asia-southeast1 --allow-unauthenticated
```

4. Nếu Cloud yêu cầu bật API, tạo artifact repo hoặc cấp quyền build, làm theo hướng dẫn từ tài khoản/project của bạn. Lưu URL service thực tế sau triển khai.
5. Truy cập `https://YOUR_CLOUD_RUN_URL/health`.
6. Từ một máy khác, gửi lại ảnh:

```powershell
curl.exe -X POST -F "fruit_id=F0002" -F "camera_id=cam01" -F "image=@quatsample.jpg;type=image/jpeg" https://YOUR_CLOUD_RUN_URL/infer
```

7. Mở **Cloud Run → Services → quat-sort-ai → Logs** để tìm dòng `MOCK received fruit_id=F0002...`.

**Lưu ý bảo mật:** `--allow-unauthenticated` chỉ dùng với endpoint MOCK không chứa bí mật cho bài thử ban đầu. Trước khi sử dụng thật, thêm xác thực (ví dụ API key trong Secret Manager hoặc cơ chế định danh phù hợp), giới hạn truy cập và không đưa Wi-Fi password/MQTT secret lên GitHub. Không nhúng secret thật vào ảnh, URL hay log.

## D. Kết nối camera (phát triển tiếp)

1. Người B nạp ví dụ CameraWebServer lên ESP32-CAM, kiểm tra ảnh qua IP nội bộ.
2. Tải một ảnh JPEG từ camera về máy tính, dùng lệnh POST ở trên gửi tới URL Cloud Run để kiểm chứng định dạng.
3. Sau khi HTTPS từ ESP32-CAM được kiểm tra (CA certificate, PSRAM, timeout), mới thay thao tác thủ công bằng firmware tự chụp và POST `/infer`.
4. Người A đối chiếu `fruit_id` gửi đi, trả về và log Cloud Run.

## Nhãn phân loại

- `GREEN`: quả xanh → servo 1.
- `RIPE`: quả chín → servo 2.
- `REJECT`: quả lỗi/không chắc chắn → khay thẳng.

`MOCK` **không thuộc ba nhãn hợp lệ**, nên ESP32 không được dùng phản hồi MOCK để gạt quả.
API đã trả `confidence`, `model_version` và `decision_reason`; phần MQTT,
timestamp và xử lý trùng `fruit_id` cần được phát triển tiếp.

## Tài liệu chính thức

- Cloud Run FastAPI quickstart: https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-fastapi-service
- EMQX Cloud Serverless: https://docs.emqx.com/en/cloud/latest/create/serverless.html
- EMQX + ESP32 TLS: https://docs.emqx.com/en/cloud/latest/connect_to_deployments/esp32.html

**Hiện trạng:** Có code suy luận ONNX và bộ công cụ huấn luyện; chưa có trọng số
đã train, chưa kết nối MQTT và firmware. Cần kiểm tra model bằng ảnh camera thực tế.
