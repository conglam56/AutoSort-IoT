# AutoSort Cloud API — Python/FastAPI + PostgreSQL

API dùng PostgreSQL để lưu tài khoản, phiên đăng nhập, phiên phân loại,
kết quả và nhật ký xác thực. Không còn lưu lịch sử thực tế trong RAM.
Dashboard ở `/dashboard/`; phần mô phỏng công khai vẫn chạy độc lập.

Huấn luyện và kiểm tra PyTorch–ONNX: [AI_TRAIN_DEPLOY.md](../docs/AI_TRAIN_DEPLOY.md).
Nguồn dataset và notebook Colab: [PUBLIC_DATASET.md](../docs/PUBLIC_DATASET.md).

## Mô hình phân loại

Đặt `best.onnx` và `classes.json` từ kết quả export vào `cloud-ai/model/`,
khởi động lại API rồi kiểm tra `/health` có `mode=onnx`, `model_ready=true`.
Nếu không nạp được model, API ghi lỗi và tiếp tục ở chế độ MOCK.
Luồng ONNX dùng chung xử lý ảnh với công cụ parity, đọc trực tiếp xác suất,
chuyển dự đoán có confidence dưới ngưỡng sang `REJECT`.
`GREEN` đi cổng 1, `RIPE` đi cổng 2, `REJECT` ra khay loại.

## Khởi chạy

Dùng Python 3.12 hoặc 3.13. Từ thư mục gốc repository:

```powershell
py -3.12 -m venv cloud-ai/.venv
.\cloud-ai\.venv\Scripts\python.exe -m pip install -r cloud-ai/requirements.txt
Copy-Item cloud-ai/.env.example cloud-ai/.env
```

Chỉnh `.env`: đặt mật khẩu PostgreSQL và một `DEVICE_API_KEY` ngẫu nhiên riêng.
`POSTGRES_PASSWORD` phải khớp phần mật khẩu trong `DATABASE_URL`.
Có thể tạo từng chuỗi bí mật bằng `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
Không commit `.env`, file tài khoản hoặc dữ liệu PostgreSQL.

Nếu dùng Docker Desktop đang hoạt động:

```powershell
docker compose --env-file cloud-ai/.env -f cloud-ai/compose.yaml up -d --wait
```

PostgreSQL chỉ mở ở `127.0.0.1:5433`. Nếu đã có PostgreSQL, tạo database riêng
và đặt `DATABASE_URL` phù hợp thay cho lệnh Docker. Không trỏ vào database dự án khác.

```powershell
.\cloud-ai\.venv\Scripts\python.exe cloud-ai/manage.py init-db
.\cloud-ai\.venv\Scripts\python.exe cloud-ai/manage.py create-user admin --role admin
.\cloud-ai\.venv\Scripts\python.exe cloud-ai/manage.py create-user viewer --role viewer
.\cloud-ai\.venv\Scripts\python.exe -m uvicorn main:app --app-dir cloud-ai --host 127.0.0.1 --port 8000
```

CLI hỏi mật khẩu 12–256 ký tự và không hiển thị mật khẩu. Không có tài khoản mặc định.
Mở <http://127.0.0.1:8000/dashboard/>, nhấn **Đăng nhập máy chủ**.
Admin có thể xác nhận tạo phiên mới; viewer chỉ đọc dữ liệu và xuất CSV.
Admin quản lý tài khoản và nhật ký trực tiếp trong mục **Quản trị** của dashboard;
xem [hướng dẫn quản trị](../docs/ADMIN_GUIDE.md). Viewer không tạo được phiên ở
cả chế độ thực tế lẫn mô phỏng. Xem dữ liệu không còn tự tạo phiên rỗng.

Trên máy đã được cấu hình trong phiên làm việc này, runtime là
`cloud-ai/.venv312/Scripts/python.exe`. Thông tin tài khoản ngẫu nhiên nằm tại
`cloud-ai/.local/initial-accounts.txt`, chỉ lưu cục bộ và được Git bỏ qua.
PostgreSQL riêng được tạo tại `cloud-ai/.local/postgres-data`, cổng 5433.
Không chạy thêm Docker vào cổng này khi cụm cục bộ vẫn chạy.
Để dừng/chạy lại cụm này bằng bộ PostgreSQL 18 đã cài:

```powershell
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'D:\AutoSort IoT\cloud-ai\.local\postgres-data' stop -m fast
& 'C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe' -D 'D:\AutoSort IoT\cloud-ai\.local\postgres-data' -l 'D:\AutoSort IoT\cloud-ai\.local\postgres.log' -o '-h 127.0.0.1 -p 5433' start
```

## Tài khoản và quyền

| Hành động | Khách | Viewer | Admin | Camera Bridge |
|---|---|---|---|---|
| Health, trang dashboard, mô phỏng | Có | Có | Có | Có |
| Đọc phiên/kết quả thực tế | Không | Có | Có | Không |
| Tạo phiên thực tế | Không | Không | Có | Không |
| Đọc 100 nhật ký gần nhất `/api/audit-logs` | Không | Không | Có | Không |
| Gửi ảnh `/infer` bằng `X-API-Key` | Không | Không | Không | Có |

Mật khẩu băm Argon2id. Session token ngẫu nhiên lưu dưới dạng SHA-256 trong DB;
cookie HttpOnly, SameSite=Lax, hết hạn sau 8 giờ. Token đăng nhập và CSRF chỉ
giữ trong bộ nhớ trình duyệt/cookie, không ghi localStorage. Logout thu hồi session
trên server; đổi mật khẩu hoặc vô hiệu tài khoản thu hồi mọi session của tài khoản.
CLI quản lý tài khoản:

```powershell
python cloud-ai/manage.py reset-password admin
python cloud-ai/manage.py disable-user viewer
```

POST từ dashboard cần origin được phép và `X-CSRF-Token` lấy từ login hoặc `/api/auth/me`.
Đăng nhập giới hạn 10 lần/tên tài khoản và 30 lần/IP trong cửa sổ 15 phút,
áp dụng chung cho nhiều API worker nhờ PostgreSQL. Thông báo sai mật khẩu không
tiết lộ tên tài khoản có tồn tại. Nhật ký ghi login thành công/thất bại, logout,
quản lý tài khoản và tạo phiên; không ghi mật khẩu hay API key.

## Camera Bridge và triển khai

Camera là điện thoại cung cấp snapshot JPEG; ESP32 là controller, không phải
ESP32-CAM. Xem [cấu hình và giao thức bridge](../camera-bridge/README.md).
Bridge mới cần model ONNX thật và `/health` có `idempotency_supported=true`.
`POST /infer` nhận header `Idempotency-Key` tùy chọn; retry cùng key và cùng input
trả nguyên kết quả đã lưu, không ghi thêm quả. Key trùng với input khác trả 409.
Để tương thích, client không gửi key vẫn chạy luồng cũ, không có bảo đảm chống trùng.

Schema v2 thêm bảng `inference_requests`, không đổi/xóa dữ liệu cũ. Chạy lại
`python cloud-ai/manage.py init-db` để nâng database hiện có trước khi chạy API
của nhánh này. Với Render Free, xem mục nâng schema trong hướng dẫn triển khai.

Triển khai Render: xem [hướng dẫn cloud](../docs/RENDER_DEPLOY.md) và `render.yaml`
ở root repository. Bản Free có entrypoint riêng khởi tạo database trước khi chạy API.

Đặt cùng `DEVICE_API_KEY` trong `camera-bridge/.env` hoặc môi trường chạy bridge,
cùng URL snapshot điện thoại và cổng Serial, không chèn key trong code:

```powershell
$env:DEVICE_API_KEY = '<key từ cấu hình riêng>'
$env:CLOUD_INFER_URL = 'http://127.0.0.1:8000/infer'
$env:PHONE_IP_WEBCAM_URL = 'http://192.168.1.15:8080/shot.jpg'
$env:SERIAL_PORT = 'COM3'
python camera-bridge/bridge.py
```

Ví dụ gọi API trong PowerShell 7:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/infer -Method Post -Headers @{'X-API-Key'=$env:DEVICE_API_KEY} -Form @{
  fruit_id='F0001'; camera_id='cam01'; image=Get-Item cloud-ai/quatsample.jpg
}
```

Trong production dùng HTTPS, `COOKIE_SECURE=true`, origin dashboard cụ thể và
PostgreSQL với TLS (`sslmode=require`), tài khoản DB giới hạn cho database AutoSort.
Chạy `init-db` như bước triển khai riêng; không tự sửa schema khi khởi động API.
Cấu hình `--forwarded-allow-ips` chỉ cho reverse proxy tin cậy để giới hạn IP chính xác.
Chạy dashboard cùng origin với API là cấu hình ưu tiên. Nếu chạy static ở cổng 8765,
thêm đúng origin đó vào `ALLOWED_ORIGINS` và khởi động lại API.

Chưa có `model/best.onnx` thì `/infer` vẫn trả rõ `MOCK`; kết quả này được lưu
nhưng không phải lệnh điều khiển servo. Ảnh dưới 300 KB được giữ trong DB;
ảnh lớn hơn chỉ lưu metadata. Dữ liệu RAM của bản API cũ không được tự khôi phục.

## Kiểm thử

```powershell
python -m pip install -r cloud-ai/requirements-dev.txt
$env:AUTOSORT_TEST_DATABASE_URL = '<PostgreSQL URL kiểm thử>'
python -m unittest discover -s tests -v
```

Kiểm thử PostgreSQL tạo schema `autosort_test_<uuid>` riêng rồi xóa schema đó,
không sửa các bảng ứng dụng. Role kiểm thử cần quyền CREATE SCHEMA.
Nếu không đặt biến kiểm thử, các bài tích hợp PostgreSQL được báo **skipped**.
Bao gồm kiểm tra 401/403, CSRF, rate limit, hết hạn/thu hồi cookie, viewer,
API key thiết bị, lưu lịch sử qua vòng đời ứng dụng và ghi đồng thời khi đổi phiên.
