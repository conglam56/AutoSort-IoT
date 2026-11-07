# AutoSort IoT

**Băng chuyền phân loại và kiểm tra lỗi sản phẩm tự động**

**[Mở dashboard AutoSort trên Render](https://autosort-iot-demo.onrender.com/dashboard/index.html)**

Bản trình diễn dùng quả quất. AI phân loại **GREEN** (quả xanh đạt), **RIPE** (quả chín đạt) và **REJECT** (quả lỗi ngoại quan). Hai servo đưa quả xanh và quả chín vào hai khay riêng. Quả loại đi tới khay cuối băng chuyền.

## 1. Xem kết quả trên web

1. Mở dashboard ở đầu trang và đăng nhập bằng tài khoản **Operator** do nhóm cấp riêng. Nếu chưa có tài khoản, liên hệ nhóm để nhận thông tin đăng nhập.
2. Vào **Tổng quan** để xem ảnh và nhãn AI, số quả đã xử lý và tỉ lệ đạt của phiên.
3. Vào **Lịch sử phiên**, chọn một phiên đã chạy để xem kết quả từng quả hoặc bấm **Xuất CSV** để tải số liệu.

Chỉ cần trình duyệt và Internet để xem dữ liệu đã lưu. Nếu nhóm chưa chạy phiên nào trên bản deploy này, danh sách lịch sử sẽ trống.

## 2. Chạy băng chuyền từ dashboard

Chuẩn bị **laptop Windows có Chrome**, Internet, **điện thoại có DroidCam**, dây USB truyền dữ liệu, ESP32 đã đấu nối với băng chuyền và nguồn cho trạm.

1. **Chuẩn bị ESP32.** Nếu board chưa nạp bản mới, mở sketch [AutoSortSerial.ino](esp32-controller/AutoSortSerial/AutoSortSerial.ino) bằng Arduino IDE. Giữ `Controller.h` và `StationConfig.h` cùng thư mục, chọn **ESP32 Dev Module** (Arduino-ESP32 **3.3.12**) và đúng cổng COM, rồi bấm **Upload**. [Sơ đồ chân và thông số firmware](esp32-controller/README.md)
2. **Chuẩn bị camera.** Mở DroidCam trên điện thoại và DroidCam Client trên laptop. Kết nối điện thoại qua USB và kiểm tra hình trong Client. Cắm ESP32 vào laptop, đóng Arduino Serial Monitor và thoát bridge Python nếu đang chạy. [Hướng dẫn DroidCam](docs/DROIDCAM_SETUP.md)
3. **Kết nối trạm.** Trên Chrome của laptop, mở dashboard và đăng nhập. Bấm **Kết nối thiết bị → Chọn ESP32**, rồi cấp quyền cho cổng USB của board. Bấm **Bật camera** và cấp quyền camera. Trong **Nguồn hình ảnh**, chọn **DroidCam** nếu đang thấy webcam laptop. Khi hình xem trước đã đúng, bấm **Kết nối trạm** và chờ trạng thái **Trạm sẵn sàng · Đang dừng**. [Hướng dẫn kết nối trên web](docs/BROWSER_STATION.md)
4. **Chạy một lượt.** Để cảm biến IR ở đầu vào trống, bấm **Bắt đầu** và chờ web báo **Chế độ tự động đang hoạt động**. Đặt **một quả** trước IR. Băng chuyền chạy sau khi nhận vật, giảm tốc và dừng tại vị trí chụp. Khi có kết quả AI, băng chuyền chạy tiếp để đưa quả vào khay. Chờ quả ra khỏi băng và motor dừng hẳn rồi đặt quả tiếp theo. [Chu trình trạm](docs/STATION_CYCLE.md)
5. **Điều khiển và kết thúc.** Giữ tab dashboard hiển thị trong lúc chạy. **Tạm dừng** giữ phiên hiện tại, **Tiếp tục** khôi phục bước đang làm. Khi demo xong, bấm **Kết thúc**, chờ trạm xác nhận đã dừng rồi chọn **Thiết bị đã kết nối → Ngắt thiết bị**.

Chrome gửi ảnh lên AI và trao đổi lệnh với ESP32 qua USB Serial. Với luồng này, mọi thao tác vận hành nằm trên dashboard.

| Hiện tượng | Cách kiểm tra |
| --- | --- |
| Web báo **Chế độ tự động đang hoạt động**, băng chuyền vẫn đứng yên | Trạm đang chờ vật. Đặt một quả trước IR đầu vào. |
| Không thấy cổng ESP32 | Kiểm tra dây USB truyền dữ liệu, cổng COM và đóng Serial Monitor hoặc ứng dụng đang dùng cổng. |
| Hình xem trước sai camera | Chọn **DroidCam** trong **Nguồn hình ảnh** và kiểm tra lại góc chụp. |
| Tab bị ẩn, mất USB hoặc trạm báo khóa lỗi | Kiểm tra thiết bị tại trạm, nhấn **EN/RESET** trên ESP32 rồi kết nối lại từ dashboard. |

Khi lắp đặt hoặc đổi vị trí camera, cảm biến hay servo, dùng [bảng hiệu chỉnh trạm](docs/STATION_CALIBRATION.md) để kiểm tra thời điểm dừng, chụp và gạt quả.

## Cấu trúc dự án

Điện thoại gửi hình về laptop qua DroidCam. Dashboard lấy một ảnh JPEG khi ESP32 yêu cầu chụp. Backend **Java 21 / Spring Boot** trên Render gọi Python worker chạy **YOLO11n V2.1** bằng ONNX, lưu kết quả vào **PostgreSQL** và trả nhãn về trạm. ESP32 điều khiển motor và servo theo nhãn nhận được.

| Thư mục | Nội dung |
| --- | --- |
| [`dashboard/`](dashboard/) | Giao diện xem kết quả, lịch sử và điều khiển trạm |
| [`esp32-controller/`](esp32-controller/) | Firmware điều khiển IR, motor và servo |
| [`backend/`](backend/README.md) và [`cloud-ai/`](cloud-ai/README.md) | API, tài khoản, lưu dữ liệu và suy luận AI |
| [`camera-bridge/`](camera-bridge/README.md) | Công cụ kiểm tra camera và kết nối trạm bằng Python |
| [`training/`](training/) và [`datasets/`](datasets/) | Mã huấn luyện, ảnh và nhãn |

Để chạy web trên máy phát triển, xem [hướng dẫn backend](backend/README.md). Để triển khai dịch vụ riêng, xem [hướng dẫn Render](docs/RENDER_DEPLOY.md).
