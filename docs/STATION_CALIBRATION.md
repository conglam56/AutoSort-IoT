# Bảng hiệu chỉnh trạm — chưa có thiết bị

Trạng thái: **chưa hiệu chỉnh/kiểm tra trên phần cứng thật**. Các giá trị
ban đầu được giữ để thử phần mềm, không phải kết quả đo. Dùng một sản phẩm
mỗi lượt và model v1 hiện tại. Quy trình: [STATION_CYCLE.md](STATION_CYCLE.md).

## Thông tin lần thử

| Mục | Kết quả |
|---|---|
| Ngày/người kiểm tra | Chưa có |
| Commit phần mềm/firmware | Điền SHA khi nhận bàn giao |
| Board/core/cổng COM | Chưa kiểm tra; sketch đã build với ESP32 Dev Module, core 3.3.12 |
| Motor/driver, nguồn motor và servo | Chưa kiểm tra |
| Điện thoại/DroidCam/camera index/backend | Chưa kiểm tra |
| Chiều dài băng, vị trí IR/camera/servo 1/servo 2 | Chưa đo |

## Các giá trị cần đo và điền vào StationConfig.h

| Trường | Giá trị ban đầu | Cách hiệu chỉnh | Giá trị đã xác nhận |
|---|---:|---|---|
| `IR_ACTIVE_LOW` / `PIN_IR` | true / GPIO 14 | Kiểm tra mức cảm biến có/không có quả | Chưa kiểm tra |
| `MOTOR_SPEED_PWM` | 150/255 | Chốt tốc độ trước khi đo các thời gian di chuyển | Chưa đo |
| `DYNAMIC_BRAKE` | true | Xác minh chế độ dừng driver và độ trôi của quả | Chưa kiểm tra |
| `irToCameraMs` | 300 ms | Từ IR đến lúc quả nằm giữa ảnh; có thể 0 nếu IR ngay vị trí chụp | Chưa đo |
| `settleMs` | 150 ms | Chờ từ dừng motor đến khi ảnh quả ổn định, không nhòe | Chưa đo |
| `cameraToGate1Ms` | 1.200 ms | Từ chạy tiếp sau RESULT đến điểm servo 1 cần bắt đầu gạt | Chưa đo |
| `cameraToGate2Ms` | 2.500 ms | Từ chạy tiếp sau RESULT đến điểm servo 2 cần bắt đầu gạt | Chưa đo |
| `gate1RestDeg` / `gate1SortDeg` | 0° / 90° | Góc nghỉ/gạt servo GREEN, tránh chạm thành hoặc kẹt | Chưa đo |
| `gate2RestDeg` / `gate2SortDeg` | 0° / 90° | Góc nghỉ/gạt servo RIPE; có thể ngược servo 1 | Chưa đo |
| `gate1HoldMs` / `gate2HoldMs` | 400 / 400 ms | Giữ đủ để quả thoát khỏi vùng gạt mỗi cổng | Chưa đo |
| `exitClearMs` | 500 ms | Biên bổ sung trước khi cho nhận sản phẩm tiếp theo | Chưa đo |
| `SERVO_MIN_US` / `SERVO_MAX_US` | 500 / 2.400 µs | Xác minh dải xung theo servo thật trước khi gắn cơ cấu | Chưa kiểm tra |

Đổi tốc độ motor, kiểu phanh, vị trí camera/cảm biến/servo hoặc kích thước
sản phẩm thì đo lại timing. Thời gian tới gate đã bao gồm việc cần mở sớm
để servo kịp gạt; không chỉ đo tới tâm cổng. Chỉnh từng biến, nạp lại và ghi
kết quả, không thay nhiều thông số cùng lúc khi chưa biết tác động.

## Trình tự thử khi nhận thiết bị

1. Kiểm tra nguồn, pin và chiều chuyển động với người phụ trách phần cứng;
   xem trước đúng camera, chưa đưa quả vào trạm.
2. Kiểm tra servo riêng, xác định góc nghỉ/gạt và giới hạn cơ khí, rồi mới
   gắn cơ cấu. Chọn motor PWM và chế độ dừng.
3. Dùng từng quả để đo IR → camera và thời gian ổn định. Xác nhận chỉ phát
   một TRIGGER và motor giữ dừng trong toàn bộ thời gian chờ AI.
4. Đo camera → từng cổng kể từ RESULT/bật lại motor, chỉnh góc và hold.
   Ghi cả nhãn AI và khay thực tế để phân biệt lỗi model với lỗi cơ cấu.
5. Thử từng nhãn nhiều lượt, kiểm tra quả cuối đã ra hết trước lượt tiếp.
6. Thử PAUSE/RESUME ở chờ chụp, chờ AI và gần cổng gạt; thử STOP giữa lượt.
7. Thử rút USB camera/ESP32, ngắt Internet và timeout. Quan sát trạng thái
   cơ khí thực, đối chiếu watchdog và lịch sử phiên trước khi chạy lại.

| Ca thử | Kết quả cần quan sát | Kết quả thực tế |
|---|---|---|
| GREEN | Chụp đúng vị trí, gạt servo 1 vào khay xanh | Chưa thử |
| RIPE | Chụp đúng vị trí, gạt servo 2 vào khay chín | Chưa thử |
| REJECT | Hai servo nghỉ, đi khay cuối | Chưa thử |
| AI chậm nhưng chưa quá hạn | Quả đứng yên, gate timing tính từ lúc chạy lại | Chưa thử |
| PAUSE/RESUME | Không tự chạy lại, giữ cùng phiên và tiến độ | Chưa thử |
| STOP/kết quả muộn | Motor dừng, nhãn cũ không đi vào phiên mới | Chưa thử |
| Mất kết nối | Hành vi thực tế khớp watchdog/fallback đã ghi trong quy trình | Chưa thử |

Bộ đếm firmware và ACK chỉ phản ánh lệnh/trạng thái phần mềm; cần quan sát
và ghi khay thực tế khi nghiệm thu, vì chưa có cảm biến xác nhận ở đầu ra.
