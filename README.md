# AutoSort IoT

## Băng chuyền phân loại và kiểm tra lỗi sản phẩm tự động

AutoSort IoT là mô hình băng chuyền tự động nhận diện và phân loại sản phẩm từ hình ảnh. Bản trình diễn sử dụng **quả quất**: quất xanh đạt vào khay **GREEN**, quất chín đạt vào khay **RIPE**, còn quả có lỗi ngoại quan vào khay **REJECT**. Đốm đen, vết thâm, sẹo vỏ và mốc đều được xem là lỗi, bất kể màu vỏ.

Camera điện thoại ghi hình; laptop chuyển ảnh lên cloud để AI suy luận; ESP32 điều khiển băng chuyền và servo. Dashboard giúp theo dõi kết quả, lịch sử và điều khiển phiên vận hành.

## Từ sản phẩm đến khay phân loại

1. Người vận hành đăng nhập dashboard, kết nối ESP32 và camera DroidCam trên laptop, rồi bấm **Bắt đầu**. **Tạm dừng**, **Tiếp tục** và **Kết thúc** điều khiển cùng một phiên vận hành.
2. Cảm biến hồng ngoại ở đầu vào phát hiện một sản phẩm. ESP32 điều khiển băng chuyền đưa sản phẩm tới vị trí chụp và dừng motor.
3. Điện thoại truyền hình ảnh qua DroidCam tới laptop. Laptop lấy một ảnh JPEG và gửi tới máy chủ trên Render; không truyền video liên tục lên cloud.
4. Backend **Java 21 / Spring Boot** gọi Python worker chạy model **ONNX** để suy luận. Kết quả GREEN / RIPE / REJECT được lưu trong **PostgreSQL** và trả về laptop.
5. Laptop gửi kết quả qua **USB Serial** tới ESP32. ESP32 cho băng chuyền chạy tiếp, điều khiển hai servo để đưa GREEN và RIPE vào khay tương ứng; REJECT đi tới khay cuối. Sau một lượt, trạm chờ sản phẩm tiếp theo trong cùng phiên.

Hệ thống xử lý **một sản phẩm mỗi lượt**. Camera là **điện thoại**, không dùng ESP32-CAM. Một phiên có thể gồm nhiều lượt; băng chuyền dừng để chụp ảnh mà không tạo phiên mới. Xem [chu trình trạm](docs/STATION_CYCLE.md) và [giao thức điều khiển](docs/WEB_CONTROL.md) để hiểu các trạng thái và điều kiện dừng.

## Sử dụng

- **Dashboard:** [autosort-iot-java.onrender.com](https://autosort-iot-java.onrender.com/dashboard/index.html). Cần tài khoản Admin hoặc Operator; trang không có demo công khai. Khi chưa kết nối trạm, vẫn có thể xem lịch sử và kết quả đã lưu sau khi đăng nhập.
- **Có thiết bị:** dùng Chrome trên laptop nối ESP32. Bật DroidCam, vào **Kết nối thiết bị → Chọn ESP32 → Bật camera → Kết nối trạm**, sau đó bấm **Bắt đầu**. Giữ tab điều khiển hiển thị trong lúc vận hành. Xem [hướng dẫn kết nối trên web](docs/BROWSER_STATION.md) và [hiệu chỉnh trạm](docs/STATION_CALIBRATION.md).
- **Chưa có băng chuyền:** có thể [kiểm tra camera và suy luận trên laptop](docs/DROIDCAM_SETUP.md) mà không tạo phiên, gửi ảnh lên cloud hoặc điều khiển ESP32.
- **Cách kết nối bằng Python:** `camera-bridge/bridge.py` vẫn có cho trường hợp cần bridge riêng; xem [hướng dẫn Camera Bridge](camera-bridge/README.md). Không chạy đồng thời Python bridge và kết nối trạm trên web vì cả hai dùng cùng cổng USB.

## Khám phá mã nguồn

- **Cloud và giao diện:** [`backend/`](backend/README.md) chứa Spring Boot API, xác thực, điều khiển phiên và lưu dữ liệu PostgreSQL. [`cloud-ai/`](cloud-ai/README.md) chứa Python worker chạy ONNX. [`dashboard/`](dashboard/) là giao diện web được backend phục vụ.
- **Camera và thiết bị:** [`camera-bridge/`](camera-bridge/README.md) có công cụ thử camera và cách kết nối Python tùy chọn. [`esp32-controller/`](esp32-controller/README.md) chứa firmware cho cảm biến, motor, servo và USB Serial.
- **Dữ liệu và tài liệu:** [`training/`](training/) chứa quy trình chuẩn bị, huấn luyện, đánh giá và xuất model; [`datasets/`](datasets/) chứa ảnh cùng nhãn. Hướng dẫn chi tiết nằm ở [`docs/`](docs/), còn kiểm thử ở [`tests/`](tests/).

Muốn chạy tại máy phát triển, cần **Java 21, Maven 3.9+, Python 3.12 và PostgreSQL**. Bắt đầu với [hướng dẫn backend](backend/README.md); xem [hướng dẫn Render](docs/RENDER_DEPLOY.md) nếu cần triển khai cloud. Các file `.env.example` là mẫu cấu hình; không đưa mật khẩu hoặc device key vào Git.

## Trạng thái và giới hạn

- Model đóng gói trong repo là **V2.1-640**, ba nhãn GREEN / RIPE / REJECT, đang dùng để thử nghiệm. Xem [thông tin model và giới hạn](cloud-ai/model/README.md). Các gói V2.2 đang được đánh giá và chưa thay vào bản cloud.
- Điểm tin cậy AI là điểm của model, không phải cam kết tỷ lệ đúng. Model vẫn có thể nhận nhầm quả xanh hoặc quả có lỗi vỏ; chưa bảo đảm nhận ra mọi vật không phải quả quất.
- Luồng phần mềm đã có kiểm thử tự động với camera và Serial giả lập. Thời điểm dừng băng chuyền, vị trí chụp, servo và xử lý lỗi vẫn cần kiểm tra, hiệu chỉnh trên thiết bị thật trước khi trình diễn.
