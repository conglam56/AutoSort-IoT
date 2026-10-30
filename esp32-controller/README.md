# ESP32 điều khiển qua USB Serial và web

Sketch: [AutoSortSerial.ino](AutoSortSerial/AutoSortSerial.ino), kèm
[Controller.h](AutoSortSerial/Controller.h). Bản gốc `D:/IoT_Arduino_Final` không bị sửa.

## Nạp và vận hành

1. Arduino IDE: chọn **ESP32 Dev Module**, board package Espressif **3.3.12**
   (bản đã build kiểm chứng), đúng cổng COM.
2. Mở `.ino`, giữ `Controller.h` trong cùng thư mục rồi Upload.
3. Đóng Serial Monitor. Chạy bridge mới; ESP32 chờ lệnh, motor vẫn dừng.
4. Đăng nhập dashboard, dùng **Bắt đầu / Tạm dừng / Tiếp tục / Kết thúc**.
   Backend cần schema v5, `web_control_supported=true`. Xem [WEB_CONTROL.md](../docs/WEB_CONTROL.md).

Không cần Wi-Fi/MQTT/API key trên firmware, không cần sao chép bốn file thư
viện ESP32PWM/ESP32Servo bàn giao. Sketch dùng LEDC của Arduino-ESP32 3.x.
Camera là điện thoại; bridge gửi JPEG lên cloud để suy luận.

## Pinout giữ từ bản bàn giao

| Thiết bị | GPIO |
|---|---|
| IR FC-51, mức phát hiện LOW | 14 |
| Servo GREEN / RIPE | 18 / 19 |
| MX1508 INA1 PWM / INA2 | 16 / 17 |
| USB Serial | 115200 baud |

Motor: 1000 Hz, 8 bit, duty 150/255. Servo: 50 Hz, 14 bit, 500–2400 µs,
góc nghỉ 0 và gạt 90. Sửa pin/PWM/dải xung trong `.ino`.
`DYNAMIC_BRAKE=true` giữ dừng HIGH/HIGH của driver MX1508 bàn giao;
đặt false nếu driver thực tế dùng thả trôi, rồi hiệu chỉnh lại vị trí dừng.

Timing trong `Config` ở `Controller.h`:

| Tham số | Mặc định |
|---|---:|
| IR tới camera | 300 ms |
| Chờ ổn định sau dừng | 150 ms |
| Chờ AI | 30.000 ms |
| Heartbeat ngoài WAIT_AI | 5.000 ms |
| Debounce IR | 20 ms |
| Camera tới servo 1 / servo 2 | 1.200 / 2.500 ms |
| Giữ góc gạt | 400 ms |
| Khoảng thoát bổ sung | 500 ms |

Chỉ đưa **một quả mỗi lượt dispatch**. Phát hiện quả thứ hai khi đang xử lý
quả trước sẽ khóa lỗi. Pause giữ trạng thái/timing và góc servo đang hoạt động;
Resume mới chạy tiếp. Stop thu servo, dừng motor, về IDLE để mở phiên mới.
Lỗi watchdog hoặc BRIDGE:STOP khóa tới khi kiểm tra/reset, không tự arm lại.

CONTROL có command UUID và run UUID; ACK chỉ phát sau khi áp dụng đầu ra.
RESULT có run UUID và counter; kết quả khi PAUSED được giữ, không tự chạy motor.
Kết quả thuộc lượt cũ bị bỏ. Giao thức chi tiết nằm trong WEB_CONTROL.md.

## Kiểm chứng

Đã build thật bằng Arduino CLI với FQBN `esp32:esp32:esp32`, core 3.3.12.
`tests/firmware_controller_test.cpp` kiểm tra chính state machine bằng C++17:
timing, pause/resume, AI đến muộn, START/STOP gửi lại, STOP ưu tiên, heartbeat,
debounce, hai quả, lỗi và `millis()` qua 32 bit. Không định nghĩa NDEBUG khi chạy test.

```text
arduino-cli compile --fqbn esp32:esp32:esp32 esp32-controller/AutoSortSerial
g++ -std=c++17 -Wall -Wextra -Werror tests/firmware_controller_test.cpp -o controller-test
./controller-test
```

Chưa nạp/chạy trên board thật trong lượt sửa này. Cần xác minh đấu dây,
nguồn điện, chiều quay, góc servo và quán tính dừng trên trạm thực trước khi
đưa quả lên băng tải. ACK không thay cho cảm biến chuyển động/khay; COUNTS
là số dispatch phần mềm tích lũy từ reset, không phải xác nhận quả đã tới khay.
