# Camera DroidCam qua USB và thử khi chưa có thiết bị

Luồng trạm: điện thoại → DroidCam Client trên laptop → Camera Bridge →
Render AI v1 → laptop → ESP32 qua USB Serial. Server không cần truy cập
camera hoặc địa chỉ IP của điện thoại. Web điều khiển vẫn dùng START/PAUSE/
RESUME/STOP và firmware v5 như [WEB_CONTROL.md](WEB_CONTROL.md).

## Thử ngay trên laptop, không cần thiết bị hoặc cloud

Từ thư mục gốc dự án, dùng Python 3.12 đã cài phụ thuộc của
`cloud-ai/requirements-dev.txt`. Máy hiện tại dùng `.venv312`; máy khác có thể
tạo venv riêng. Chỉ cần `camera-bridge/requirements.txt` nếu không chạy AI local.

```powershell
& .\cloud-ai\.venv312\Scripts\python.exe camera-bridge/camera_check.py --make-sample .local/droidcam-sample.avi
& .\cloud-ai\.venv312\Scripts\python.exe camera-bridge/camera_check.py --source video --video-file .local/droidcam-sample.avi --frames 3 --infer-local
```

Lệnh đầu tạo file AVI mới gồm ba ảnh mẫu sẵn có. Nếu file đã tồn tại, bỏ qua
lệnh đầu hoặc chọn tên khác. Lệnh sau in đường dẫn `index.html`: mở bằng trình
duyệt để xem từng khung, nhãn, điểm confidence và thời gian suy luận v1.
Mỗi lần chạy tạo thư mục kết quả mới, có ảnh JPEG và `report.json`.
Không tự mở trình duyệt, không ghi đè kết quả cũ.

Bỏ `--infer-local` để chỉ kiểm tra lấy ảnh. Có thể thay `--video-file` bằng
video riêng. Mỗi lần chụp lấy **khung tiếp theo**, không phát theo thời gian
thật, không chọn ngẫu nhiên hoặc tự tua lại khi hết file. `--frames 3` lấy
ba khung liên tiếp; video riêng có thể vẫn là cùng một quả ở cả ba khung.
AVI mẫu là fixture kiểm tra đường truyền pixel và JPEG, không phải bộ đánh
giá model hoặc video băng chuyền thực. Resize, nền đệm và nén có thể đổi dự đoán
so với JPEG gốc. Điểm confidence không phải xác suất chất lượng được hiệu chuẩn.

Chế độ này không cần DEVICE_API_KEY, không gọi cloud, không tạo/đóng phiên,
không mở Serial và không gửi lệnh xuống ESP32. Dùng đúng model v1 tại
`cloud-ai/model`, không chuyển sang v2.

## Phụ thuộc Windows và lỗi thiếu MSMF

Windows dùng `opencv-python==4.12.0.88` (đã kiểm tra với DroidCam/MSMF),
Linux/Render giữ bản `opencv-python-headless`. Không cài hai gói vào cùng
venv vì chúng ghi vào cùng module `cv2`. Nếu venv Windows cũ đã cài headless,
chuyển sang phụ thuộc mới trước khi thử:

```powershell
& .\cloud-ai\.venv312\Scripts\python.exe -m pip uninstall -y opencv-python-headless opencv-python
& .\cloud-ai\.venv312\Scripts\python.exe -m pip install -r cloud-ai/requirements-dev.txt
```

Trong trường hợp đã tái hiện trên Windows: client có hình USB nhưng `dshow`
không mở được, bản headless không có MSMF, còn bản đầy đủ đọc thành công với
`--backend msmf --index 1`. Đây là index của máy đã thử, không phải mặc định
cố định cho mọi laptop. Lỗi thiếu backend được báo riêng, không tự đổi camera.
Khi mở camera ảo, các khung đầu có thể chỉ chứa màn hình “Start DroidCam”.
Bridge đọc bỏ các khung khởi động trong `CAMERA_WARMUP_SECONDS=1.5` trước
lần chụp đầu, vẫn nằm trong thời hạn capture. Đây không phải bước nhận diện
placeholder: luôn kiểm tra ảnh đã lưu đúng là quả. Nếu máy cần lâu hơn, tăng
warmup và giữ nó nhỏ hơn `CAPTURE_TIMEOUT_SECONDS`; không đổi thời hạn job AI
vượt watchdog firmware.

## Khi có điện thoại và DroidCam

1. Cài ứng dụng điện thoại và [DroidCam Windows Client chính thức](https://droidcam.app/windows/).
   Kết nối USB theo [hướng dẫn của DroidCam](https://droidcam.app/help/).
   Hoàn tất driver/quyền USB theo loại điện thoại; chỉ cắm dây chưa đủ.
2. Bật truyền hình ảnh trong DroidCam Client. Client cung cấp webcam trên PC.
3. Dùng lệnh sau để lưu ảnh xác nhận đúng camera, chưa chạy cloud/motor:

```powershell
& .\cloud-ai\.venv312\Scripts\python.exe camera-bridge/camera_check.py --source webcam --index 0
```

Mở `index.html` được in ra. Nếu là webcam laptop, thử `--index 1`, `--index 2`...
Không giả định DroidCam luôn có index 0. Camera index có thể đổi theo backend
hoặc khi thêm/tháo thiết bị. Windows DroidCam đã được đọc thành công qua
`--backend msmf`. Nếu `auto`/`dshow` không mở được, thử MSMF và xác nhận đúng
ảnh; index của DirectShow không đảm bảo trùng index của MSMF. Không mở preview và bridge đồng
thời; một số driver chỉ cho một ứng dụng dùng camera. Công cụ không tự dò/mở
mọi camera để tránh chọn nhầm nguồn.

Trong `camera-bridge/.env` (không commit key), đặt:

```dotenv
CAMERA_SOURCE=webcam
CAMERA_INDEX=1
CAMERA_BACKEND=msmf
```

Thay index/backend bằng giá trị đã xác nhận. Với `webcam` không cần
`PHONE_IP_WEBCAM_URL`. Giữ `CLOUD_INFER_URL`, `DEVICE_API_KEY`, `SERIAL_PORT`
và baud rate hiện có. Sau khi nạp firmware đúng và nối ESP32, chạy
`camera-bridge/bridge.py`, rồi dùng các nút trên web. Không cần sửa/deploy
backend chỉ để đổi nguồn ảnh. Chế độ `phone` tiếp tục hỗ trợ snapshot JPEG
qua HTTP như trước; không tự chuyển nguồn nếu DroidCam lỗi.

## Hành vi lỗi và giới hạn

- Camera cục bộ dùng OpenCV VideoCapture trong **tiến trình riêng**, một handle
  cho mỗi bridge. Webcam được đọc liên tục để giảm backlog; mỗi yêu cầu lấy
  lần đọc mới, không tái dùng JPEG đã lưu. Driver/DroidCam vẫn có thể trả
  hình đứng; phần mềm không chứng minh độ mới của nội dung cảnh chụp.
- `CAPTURE_TIMEOUT_SECONDS` giới hạn cả mở/đọc camera. Hết hạn thì ngắt tiến
  trình camera, không dùng ảnh đến muộn. Kiểm tra nguồn và chạy lại bridge
  khi camera đã lỗi; không tự đổi sang webcam khác hoặc ảnh mẫu.
- Ảnh nguồn tối đa 25 MP, được thu nhỏ cạnh dài tối đa 1600 và mã hóa JPEG
  không quá 1 MB. Đây là chuẩn gửi API, không gửi video liên tục lên cloud.
- Khi lấy ảnh/gọi AI thất bại, bridge giữ hành vi hiện có: quả đang xử lý
  đi nhánh REJECT dự phòng. Đây không phải AI xác nhận quả lỗi. Kênh điều
  khiển/Serial lỗi hoặc thiếu ACK sẽ dừng/khóa theo watchdog và giao thức v5.
- Video bị từ chối trong chế độ điều khiển băng chuyền thật. Nếu dùng
  `CAMERA_SOURCE=video` với `bridge.py --manual`, đó là kiểm thử **gọi cloud
  thật và tạo phiên thật**, cần key và ảnh hưởng lịch sử. Để thử riêng, dùng
  `camera_check.py` như hướng dẫn đầu trang.

## Kiểm thử cho người phát triển

```powershell
& .\cloud-ai\.venv312\Scripts\python.exe -m unittest discover -s tests -v
```

Bao gồm video MJPEG thật, EOF không lặp ảnh, timeout driver giả lập,
JPEG hợp lệ, giữ giới hạn ảnh, chọn đúng nguồn cấu hình, video không được dùng
cho băng chuyền và preview không dùng key/cloud/Serial. Test điều khiển kiểm
tra PAUSE trong khi AI đang chạy, STOP bỏ kết quả muộn, mất kênh điều khiển,
thiếu ACK, ghi Serial dở không gửi lại, camera mất không gọi AI.

Với PostgreSQL thử nghiệm trên localhost và JAR đã build:

```powershell
$env:AUTOSORT_TEST_DATABASE_URL='postgresql://<test-user>:<test-password>@127.0.0.1:5432/<test-db>'
& .\cloud-ai\.venv312\Scripts\python.exe tests/integration_spring_bridge.py --task detect --web-control --video-camera
```

E2E dùng video thật, Java/PostgreSQL/ONNX Runtime thật, graph ONNX fixture
cố định và Serial giả lập. Nó kiểm tra luồng phần mềm và phiên, **không đo
độ chính xác v1 hoặc xác nhận motor/servo đã hoạt động**. Không dùng dữ liệu
production. Còn phải thử DroidCam qua USB, cảm biến và cơ khí thật khi nhận
thiết bị. Tham khảo [OpenCV VideoCapture](https://docs.opencv.org/4.x/d8/dfe/classcv_1_1VideoCapture.html).
