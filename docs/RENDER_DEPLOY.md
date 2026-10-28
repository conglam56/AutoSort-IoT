# Triển khai AutoSort lên Render

FastAPI, dashboard và model ONNX chạy trong một Web Service; dữ liệu ở Render
PostgreSQL. Không phục vụ dataset huấn luyện, `.env` hay mật khẩu qua dịch vụ web.
Cloud nhận ảnh để suy luận; người phụ trách AI huấn luyện và bàn giao model riêng.

## Cấu hình của dự án

- Repository: `https://github.com/conglam56/AutoSort-IoT`, branch `main`.
- Web Service hiện có: `AutoSort-IoT`, URL `https://autosort-iot.onrender.com`.
- Giữ region `oregon` của dịch vụ hiện có; PostgreSQL phải cùng region/workspace.
- Web Service và PostgreSQL đều dùng **Free** trong bản thử nghiệm này.
- `render.yaml` là cấu hình tham khảo/tạo mới. Nếu đã có dịch vụ, dùng lại dịch vụ
  đó; không tạo Blueprint thứ hai làm phát sinh tài nguyên trùng.

Trong **Settings → Build & Deploy** của Web Service, dùng:

| Mục | Giá trị |
|---|---|
| Root Directory | Để trống (root repository) |
| Build Command | `pip install -r cloud-ai/requirements.txt` |
| Start Command | `python cloud-ai/render_start.py` |
| Health Check Path | `/ready` |

Root Directory phải là root repository để FastAPI đọc được thư mục `dashboard/`
cùng cấp với `cloud-ai/`. `.python-version` cố định dòng Python 3.12.
Không dùng `python cloud-ai/main.py` để chạy production: lối chạy trực tiếp đó
dành cho phát triển local và bật reload.

## Database và biến môi trường

Tạo PostgreSQL `autosort-postgres`, plan Free, cùng region `oregon`, phiên bản 18.
Ưu tiên **Internal Database URL**. Trong cấu hình tạo mới bằng Blueprint, database
được giới hạn kết nối bên ngoài bằng `ipAllowList: []`.

| Biến | Giá trị |
|---|---|
| `DATABASE_URL` | Internal Database URL của Render PostgreSQL |
| `DATABASE_SSLMODE` | `require` |
| `COOKIE_SECURE` | `true` |
| `INITIALIZE_DATABASE` | `true` cho lần đầu tạo database |
| `BOOTSTRAP_ADMIN_USERNAME` | `admin` |
| `BOOTSTRAP_ADMIN_PASSWORD` | Chuỗi ngẫu nhiên riêng, 12–256 ký tự |
| `DEVICE_API_KEY` | Chuỗi ngẫu nhiên riêng, tối thiểu 32 ký tự |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` |

Không đặt `ALLOWED_ORIGINS` thì trên Render ứng dụng tự lấy đúng
`RENDER_EXTERNAL_URL`. Nếu thêm domain riêng, đặt danh sách origin HTTPS cụ thể;
không dùng `*`. Không đặt giá trị localhost trên cloud.

`render_start.py` là bước khởi tạo tường minh trước khi chạy Uvicorn. Khi cho phép
`INITIALIZE_DATABASE=true`, nó tạo schema v1 nếu chưa có; chỉ tạo admin khi
database chưa có tài khoản nào. Nếu lỗi tạo tài khoản thì giao dịch tạo schema
cũng rollback. Khởi động lại không đổi mật khẩu hoặc tái tạo tài khoản đã khóa.
API chạy trực tiếp bằng Uvicorn vẫn yêu cầu schema đã được tạo trước như cũ.

Sau lần đầu thành công, có thể đặt `INITIALIZE_DATABASE=false` và gỡ
`BOOTSTRAP_ADMIN_PASSWORD` khỏi môi trường nếu không cần giữ để tra lại mật khẩu.
Mật khẩu tài khoản đã được băm trong PostgreSQL; không bị đổi theo biến bootstrap.
Thao tác này không làm mất dữ liệu. Khi nâng schema sau này, cần migration riêng;
script này không tự nâng schema của một database đã có.

`/ready` kiểm tra schema và kết nối database, trả 503 khi PostgreSQL không khả dụng.
`/health` cho biết model ONNX hay MOCK. Dịch vụ vẫn sẵn sàng thử nghiệm khi chưa có
model; không diễn giải MOCK là nhãn phân loại thật.

## Kiểm tra sau triển khai

1. Mở `/ready`: phải trả `status=ready`.
2. Mở `/health`: xác nhận mode, model version và trạng thái model.
3. Mở `/dashboard/`, đăng nhập bằng admin vừa khởi tạo, tạo một phiên.
4. Từ máy Camera Bridge, đặt `CLOUD_INFER_URL=https://autosort-iot.onrender.com/infer`
   và `DEVICE_API_KEY` riêng được lưu trong môi trường dịch vụ Render.
5. Gửi ảnh JPEG mẫu, kiểm tra API trả kết quả và dashboard ghi nhận cùng mã quả.
6. Khởi động lại dịch vụ, kiểm tra phiên và kết quả cũ còn nguyên trong PostgreSQL.
7. Khi có model, đưa `best.onnx` và `classes.json` vào `cloud-ai/model/`, triển khai
   lại và kiểm tra `/health` có `model_ready=true` rồi thử camera thực tế.

Thiết lập viewer, đổi quyền và đặt lại mật khẩu trong mục **Quản trị** của dashboard.
CLI `cloud-ai/manage.py` vẫn dùng cho việc phục hồi/bảo trì từ môi trường có kết nối
database. Free không có shell, nên nếu dùng CLI trên máy cá nhân phải tạm cho
phép IP cần thiết trong database và dùng External Database URL với TLS. Không
đưa kết nối đó vào Git hoặc chat. Giới hạn proxy tin cậy phải được đối chiếu với
cấu hình mạng thực tế khi triển khai ở nền tảng khác.

## Giới hạn Free

Free Web Service có thể ngủ sau 15 phút không có truy cập; thời gian khởi động
lại có thể vượt timeout Camera Bridge. Không cam kết chạy băng chuyền liên tục
bằng gói này. PostgreSQL Free có giới hạn 1 GB và hết hạn sau 30 ngày; cần xuất
dữ liệu trước hạn hoặc người dùng chủ động quyết định gói phù hợp. Ảnh snapshot
trong PostgreSQL cũng chiếm dung lượng này. Không tự nâng lên gói trả phí.

Nguồn chính thức:

- [Triển khai FastAPI](https://render.com/docs/deploy-fastapi)
- [Biến môi trường Render](https://render.com/docs/environment-variables)
- [Blueprint YAML](https://render.com/docs/blueprint-spec)
- [Kết nối PostgreSQL và TLS](https://render.com/docs/postgresql-creating-connecting)
- [Giới hạn Free](https://render.com/docs/free)
