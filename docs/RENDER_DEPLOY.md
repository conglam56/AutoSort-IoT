# Triển khai Java Spring Boot lên Render

Backend mới dùng **Docker, Java 21 + Python ONNX worker nội bộ**. Dashboard và mọi
API do Spring Boot phục vụ. PostgreSQL vẫn là database hiện có, không cần tạo lại
tài khoản hay xóa dữ liệu. `render.yaml` mô tả một Web Service Docker Free mới,
**không khai báo/tạo database mới**.

## Địa chỉ cloud đang sử dụng

Đã triển khai dịch vụ `AutoSort-IoT-Java` trên gói Free ngày 29/10/2026:

- Dashboard: https://autosort-iot-java.onrender.com/dashboard/
- Camera Bridge: `CLOUD_INFER_URL=https://autosort-iot-java.onrender.com/infer`.
- Dùng lại `autosort-postgres`, schema v3; Admin và Operator đã kiểm tra đăng nhập.
- Bản tích hợp v1 kèm detector `autosort-yolo11n-detect-v1` trong
  `cloud-ai/model/`. Sau khi triển khai bản này, xác nhận `/health` có
  `mode=onnx`, `model_ready=true`, `task=detect` và đúng phiên bản model.
  Đây là thử tích hợp; chất lượng trên trạm chưa được xác nhận, xem
  [kết quả và giới hạn](AI_DETECTION_RESULTS.md).

Nếu bridge đã có `.env` riêng, cần sửa `CLOUD_INFER_URL` trong file đó; thay đổi
giá trị mặc định không ghi đè biến môi trường đã đặt.

## Dịch vụ Python hiện có

Dịch vụ `AutoSort-IoT` tại `https://autosort-iot.onrender.com` trước đây dùng
runtime Python và `python cloud-ai/render_start.py`. Runtime của dịch vụ Render
không thể đổi trực tiếp sang Docker bằng sửa Blueprint. Merge mã không tự chuyển
dịch vụ này sang Java. Không bấm triển khai mã mới bằng start command Python cũ;
các module FastAPI cũ đã được thay bằng backend Java.

Không sync Blueprint mới lên dịch vụ Python cũ để ép đổi runtime. Giữ bản đang
live trong lúc kiểm tra dịch vụ Docker; việc chuyển traffic là bước triển khai riêng.

## Tạo Web Service Docker

Trong workspace AutoSort IoT, tạo Web Service **Free**, region **Oregon**, từ
repository `conglam56/AutoSort-IoT`, branch `main`:

| Mục | Giá trị |
|---|---|
| Tên | `AutoSort-IoT-Java` (phân biệt dịch vụ Python cũ) |
| Runtime/Language | Docker |
| Root Directory | Để trống |
| Dockerfile Path | `./Dockerfile` |
| Docker Build Context | `.` |
| Docker Command | Để trống, dùng ENTRYPOINT của image |
| Health Check Path | `/ready` |

Image chỉ copy backend, dashboard, worker và model; không chứa dataset, `.env`,
file tài khoản, thư mục `.local` hoặc Git. Chạy bằng user không phải root.
JVM giới hạn heap 160 MB; ONNX dùng CPU một thread. Cần đo bộ nhớ/độ trễ với model
nhóm bàn giao trước khi kết luận gói Free đủ cho chạy thực tế.

## Biến môi trường và giữ dữ liệu

- `DATABASE_URL`: **Internal Database URL của autosort-postgres hiện có**, cùng
  workspace/region. Không gửi URL chứa mật khẩu vào chat hoặc commit vào Git.
- `DATABASE_SSLMODE=require`, `COOKIE_SECURE=true`.
- `DEVICE_API_KEY`: giữ cùng key thiết bị nếu tiếp tục dùng bridge hiện có.
- `MIGRATE_DATABASE=true`: cho phép nâng schema v1/v2 lên v3 theo giao dịch có khóa.
  Giữ mật khẩu/lịch sử; khóa Viewer cũ và thu hồi token của họ, không tự nâng Operator. Xem AUTH_RBAC_REFACTOR.md trước khi chạy migration.
- Với database đang có admin, không cần bootstrap. Với database trống mới, cần
  `INITIALIZE_DATABASE=true`, `BOOTSTRAP_ADMIN_USERNAME` và mật khẩu riêng.
- Không đặt `ALLOWED_ORIGINS` thì backend dùng `RENDER_EXTERNAL_URL` của chính
  dịch vụ Java. Nếu có domain riêng, đặt đúng origins HTTPS. Cookie/token cũ ở DB
  vẫn hợp lệ nhưng đổi hostname thì trình duyệt cần đăng nhập lại.
- `PORT` dùng biến Render cấp. Python và đường dẫn worker/model đã đặt trong image.

## Kiểm tra và chuyển sang Java

1. Xác nhận deploy Java `live`; `/health` có `backend=spring-boot` và `/ready` trả 200.
2. Đăng nhập bằng tài khoản hiện có; xem lịch sử cũ, thử quyền admin/operator.
3. Kiểm tra model. Khi chưa có `best.onnx` + `classes.json`, vẫn là MOCK và bridge
   sẽ từ chối chạy trạm. Khi có model, health phải có `mode=onnx`, `model_ready=true`.
4. Đổi `CLOUD_INFER_URL` của bridge sang URL **dịch vụ Java** + `/infer`, mở dashboard
   tại URL mới. Kiểm tra một quả từ điện thoại đến dữ liệu cloud và ESP32.
5. Chỉ sau khi xác nhận chạy tốt mới dừng dịch vụ Python cũ hoặc chuyển domain.
   Gỡ/tắt cờ migration và mật khẩu bootstrap sau khi thành công.

Khi rollback quyền v3, dừng writer và dùng script rollback được mô tả trong AUTH_RBAC_REFACTOR.md; không xóa dữ liệu hoặc bảng metadata.
migration mang tính thêm mới và schema cũ vẫn giữ nguyên. Xem kỹ dữ liệu ghi từ
hai phiên bản nếu vận hành song song; dùng một backend cho trạm tại thời điểm cắt chuyển.

## Giới hạn Free và nguồn

Free Web Service có thể ngủ khi không có truy cập; PostgreSQL Free có hạn sử dụng
và không có backup quản lý. Xuất dữ liệu trước hạn, kiểm tra lại chính sách và
đánh thức dịch vụ trước buổi demo. Không tự nâng gói trả phí.

- [Docker trên Render](https://render.com/docs/docker)
- [Blueprint specification](https://render.com/docs/blueprint-spec)
- [Giới hạn Free](https://render.com/docs/free)
