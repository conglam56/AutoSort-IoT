# ESP32 điều khiển qua USB Serial và web

Sketch: [AutoSortSerial.ino](AutoSortSerial/AutoSortSerial.ino), kèm
[Controller.h](AutoSortSerial/Controller.h) và
[StationConfig.h](AutoSortSerial/StationConfig.h). Bản gốc `D:/IoT_Arduino_Final` không bị sửa.

## Nạp và vận hành

1. Arduino IDE: chọn **ESP32 Dev Module**, board package Espressif **3.3.12**
   (bản đã build kiểm chứng), đúng cổng COM.
2. Mở `.ino`, giữ cả hai file `.h` trong cùng thư mục rồi Upload.
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

Motor: 1000 Hz, 8 bit, PWM chạy 180/255 theo `AutoSortSerial (1).zip` ngày 07/11/2026.
Servo: 50 Hz, 14 bit, 500–2400 µs. Sửa pin/PWM/dải xung, thời gian
và góc tại **StationConfig.h**, không sửa logic `.ino`/Controller.h.
`DYNAMIC_BRAKE=true` giữ dừng HIGH/HIGH của driver MX1508 bàn giao;
đặt false nếu driver thực tế dùng thả trôi, rồi hiệu chỉnh lại vị trí dừng.

Timing trong `Config` ở `StationConfig.h`:

| Tham số | Mặc định |
|---|---:|
| Chờ sau khi IR phát hiện | 600 ms |
| Xung khởi động | 230/255 trong 80 ms |
| Thời gian motor chạy tới camera | 700 ms |
| Giảm tốc trước camera | 300 ms cuối, từ 180 về gần 145/255 |
| Chờ ổn định sau dừng | 600 ms |
| Chờ AI | 30.000 ms |
| Heartbeat ngoài WAIT_AI | 10.000 ms |
| Debounce IR | 120 ms |
| Camera tới servo 1 / servo 2 | 1.000 / 1.500 ms |
| Giữ góc gạt servo 1 / 2 | 2.100 / 2.100 ms |
| Khoảng thoát bổ sung | 500 ms |
| Góc nghỉ/gạt servo 1 / servo 2 | 43°/0° và 45°/0° |

PWM/góc đã đối chiếu với code nhóm cung cấp; bản firmware cập nhật vẫn cần
thử trên thiết bị. Các thời gian di chuyển **chưa được đo trên trạm thật**. Xem
[chu trình dừng/chụp/xử lý/gạt](../docs/STATION_CYCLE.md) và
[bảng hiệu chỉnh](../docs/STATION_CALIBRATION.md). IR đã được người dùng xác nhận
ở ngay chỗ đặt vật đầu vào. Bản này dùng cảm biến đó để đánh thức motor; nếu
chuyển IR đến camera thì sẽ không tự phát hiện vật ở đầu vào. Servo có góc
nghỉ/gạt và thời gian giữ riêng. Gate timing bắt đầu từ lúc nhận RESULT và bật motor chạy tiếp.
Config sai góc/thời gian bị chặn khi build; bộ điều khiển cũng từ chối chạy
với config không hợp lệ trong mô phỏng.

## Chạy từng vật và dừng chờ

- Để IR trống rồi bấm **Bắt đầu** một lần: phiên được mở, motor **vẫn dừng**.
- Đặt vật ngay IR đầu vào. Sau 120 ms lọc nhiễu và 600 ms chờ, motor bắt đầu chạy.
- Sau 700 ms di chuyển, gồm đoạn giảm tốc, motor dừng và chờ 600 ms trước khi chụp.
- Nhận RESULT đúng lượt: chạy tiếp, gạt theo nhãn với timing trong bảng.
- Hết cửa sổ 4.100 ms kể từ RESULT (khi hai servo đã về nghỉ), motor dừng,
  vẫn giữ phiên để chờ vật tiếp. Cần IR nhả rồi mới nhận cạnh phát hiện mới.
- RUNNING/ACK RUNNING nghĩa là chế độ tự động đang hoạt động; giữa các vật
  motor không quay. Pause/Resume khi đang chờ vật cũng không tự quay motor.

Không có cảm biến ở khay: mốc 4.100 ms là ước lượng vận chuyển, chưa xác nhận
vật thực sự vào hộp. Hiệu chỉnh `exitClearMs` và timing nếu vật chưa thoát hết.
Khi hoàn tất mỗi lượt **không bấm Kết thúc**; chỉ Kết thúc khi muốn đóng phiên.

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
