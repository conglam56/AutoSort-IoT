# Chu trình dừng để chụp và phân loại từng sản phẩm

Luồng đã chốt: **motor dừng chờ → đặt sản phẩm tại IR → chạy → dừng tại camera → chờ ổn định → lấy ảnh →
chờ AI → chạy tiếp → đưa vào khay → motor dừng chờ vật tiếp theo**. Demo dùng quất,
nhưng đơn vị vận hành là sản phẩm và phiên. Một phiên có nhiều lượt; việc
dừng nội bộ để chụp không tạo phiên mới và không phải nút Tạm dừng trên web.

## Trình tự thực tế của phần mềm

```mermaid
flowchart TD
    A[Web Bắt đầu: tạo phiên, motor dừng chờ] --> B[IR đầu vào phát hiện một sản phẩm]
    B --> C[Chờ ổn định tại đầu vào, bật motor rồi giảm tốc trước camera]
    C --> D[Dừng motor và chờ ổn định]
    D --> E[ESP32 gửi TRIGGER: run + mã sản phẩm]
    E --> F[Laptop lấy một ảnh từ DroidCam]
    F --> G[Laptop gửi JPEG lên Render AI]
    G --> H[Kết quả về laptop, chuyển xuống ESP32]
    H --> I[Motor chạy tiếp, bắt đầu tính thời gian tới cổng]
    I --> J{Nhãn}
    J -->|GREEN| K[Servo 1 gạt vào khay xanh]
    J -->|RIPE| L[Servo 2 gạt vào khay chín]
    J -->|REJECT| M[Không gạt, đi tới khay cuối]
    K --> N[Servo về nghỉ, chờ hết cửa sổ thoát]
    L --> N
    M --> N
    N --> O[Dừng motor, chờ vật mới tại IR]
    O --> B
```

1. Bridge kết nối USB và cloud nhưng motor vẫn dừng ở IDLE. Bấm Bắt đầu
   trên web mới tạo phiên và gửi START. Motor vẫn dừng chờ vật, firmware trả ACK
   RUNNING để xác nhận chế độ tự động đã bật; không phải xác nhận motor quay.
2. Đặt **một** sản phẩm lên băng chuyền. IR ở đầu vào ngay chỗ đặt vật; phát hiện ổn định mới bật motor. IR phải nhả trước khi nhận cạnh
   phát hiện mới. Firmware xác nhận mức IR ổn định trong 120 ms rồi đợi thêm 600 ms.
3. IR nằm tại đầu vào theo người dùng xác nhận ngày 02/11/2026. Firmware
   chạy motor `irToCameraMs=700` trước khi dừng, gồm xung khởi động 80 ms và 300 ms giảm tốc cuối. Không
   chuyển cảm biến này đến camera nếu vẫn cần phát hiện vật khi băng dừng.
4. Sau khi tắt motor, firmware chờ `settleMs` cho quả ổn định rồi phát đúng
   một TRIGGER. Laptop mới lấy ảnh. Băng chuyền **tiếp tục dừng** trong WAIT_AI.
5. Với DroidCam, video tới laptop; bridge lấy khung mới, chuyển JPEG và chỉ
   gửi ảnh đó lên API. API trả GREEN/RIPE/REJECT về laptop, laptop gửi RESULT
   kèm run UUID và counter xuống ESP32. Không gửi video liên tục lên cloud.
6. Nhận kết quả đúng lượt mới bắt đầu DISPATCH và bật motor. Các mốc
   `cameraToGate1Ms` / `cameraToGate2Ms` được tính **từ lúc chạy tiếp**, không
   tính từ thời điểm IR hoặc từ lúc bắt đầu gọi AI. Thời gian AI thay đổi
   không được cộng vào thời gian di chuyển tới servo.
7. GREEN dùng servo 1, RIPE dùng servo 2. Mỗi servo có góc nghỉ, góc gạt và
   thời gian giữ riêng. REJECT giữ hai servo ở góc nghỉ để quả đi cuối băng.
8. Sau cửa sổ `max(gate1 travel + hold, gate2 travel + hold) + exitClearMs`,
   firmware tăng bộ đếm phần mềm, **dừng motor** và về RUNNING (chờ vật).
   Giữ cùng phiên trên web. Chỉ đưa sản phẩm tiếp theo
   sau bước này. Không có hàng đợi nhiều quả và chưa có cảm biến khay xác
   nhận quả thật đã ra hết.

Thông số trong ZIP ngày 07/11/2026: PWM chạy 180/255, khởi động 230/255,
giảm tốc về gần 145/255. Sau khi dừng chờ 600 ms trước khi chụp. Từ camera
đến servo 1/2 là 1.000/1.500 ms, giữ mỗi servo 2.100 ms, thoát thêm 500 ms.
Cửa sổ dispatch là 4.100 ms kể từ lúc chạy tiếp. Đây là
mốc theo thời gian, không phải xác nhận cảm biến rằng vật đã vào khay.

## Cấu hình và hiệu chỉnh

Chỉ sửa [StationConfig.h](../esp32-controller/AutoSortSerial/StationConfig.h)
để đổi thời gian, góc, pin và PWM; không cần sửa logic `Controller.h` hoặc
bridge. Giữ file này cùng `Controller.h` và `.ino` khi nạp ESP32. Config không
hợp lệ bị chặn khi build sketch; state machine cũng không cho chạy nếu
nhận config không hợp lệ trong kiểm thử native.

Ghi kết quả vào [bảng hiệu chỉnh](STATION_CALIBRATION.md). Bản sửa này đã mô phỏng và build, chưa thử trực tiếp
trên thiết bị; không ghi các mốc giữ từ ZIP thành kết quả đo mới.

## Tạm dừng, kết thúc và lỗi

| Tình huống | Hành vi phần mềm |
|---|---|
| Tạm dừng trên web | Dừng motor, giữ trạng thái và thời gian đã di chuyển; không tạo phiên mới |
| AI trả về khi PAUSED | Giữ nhãn đúng lượt; chỉ Tiếp tục mới được chạy motor |
| Tiếp tục | Khôi phục bước đang làm; nếu chờ vật thì motor vẫn dừng, nếu đang di chuyển thì chạy phần còn lại |
| Kết thúc | Dừng motor, servo về góc nghỉ, bỏ kết quả tới muộn và đóng phiên sau ACK |
| Camera/gọi AI lỗi trên laptop | Quả hiện tại nhận REJECT dự phòng; không phải AI xác nhận thấy lỗi |
| Firmware chờ AI quá 30 s | Đi nhánh cuối với REJECT dự phòng, sau đó khóa lỗi để kiểm tra trạm |
| Mất heartbeat/ghi Serial dở/thiếu ACK | Dừng hoặc khóa theo watchdog/giao thức; không phát lại lệnh motor chưa rõ kết quả |
| Quả thứ hai trong lúc xử lý quả trước | Khóa SECOND_FRUIT, cần kiểm tra và reset |

Đóng tab hoặc đăng xuất không tự dừng trạm. Sau Kết thúc giữa lượt, lấy quả
đang dở trước khi Bắt đầu lại. Thay đổi watchdog AI phải đồng bộ thời hạn job
của bridge: mặc định bridge tối đa 25 s, firmware 30 s, chừa biên cho Serial.
Giữ các mốc watchdog hiện có trong lúc hiệu chỉnh cơ khí.

## Kiểm chứng khi chưa có thiết bị

- `tests/firmware_controller_test.cpp` chạy chính Controller của ESP32:
  motor tắt trước TRIGGER, chỉ một TRIGGER, đứng yên chờ AI, lấy mốc gate
  sau RESULT, từng góc/hold tùy chỉnh, cả ba nhãn và về sẵn sàng sau thoát.
- Có test IR tại camera (`irToCameraMs=0`, tắt chờ đầu vào, xung và giảm tốc), pause trong chờ ổn định, pause
  trong gate/WAIT_AI, kết quả cũ, timeout, overflow timer và cấu hình sai.
- Test Python và E2E kiểm tra video thật → JPEG → Java/ONNX/PostgreSQL
  localhost → kết quả có run/counter → Serial fixture, cùng START/PAUSE/
  RESUME/STOP. Xem [DroidCam và thử offline](DROIDCAM_SETUP.md).

Các test này kiểm chứng logic, không xác nhận chiều quay motor, khoảng dừng,
góc cơ khí hay quả đã được gạt đúng khay. Việc nghiệm thu vật lý vẫn chờ
điện thoại, ESP32, cảm biến, motor/driver và servo của nhóm.
