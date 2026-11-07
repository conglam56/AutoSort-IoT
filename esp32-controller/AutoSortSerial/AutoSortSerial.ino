/*
 * AUTOSORT - CHƯƠNG TRÌNH ĐIỀU KHIỂN ESP32 QUA USB SERIAL
 * Board: ESP32 Dev Module; Arduino-ESP32 3.x (đã kiểm tra với 3.3.12).
 * Mở file này bằng Arduino IDE; giữ Controller.h và StationConfig.h cùng thư mục.
 *
 * Vai trò các thiết bị:
 *   Điện thoại/DroidCam -> laptop chụp ảnh -> cloud chạy AI -> laptop trả nhãn
 *   -> ESP32 điều khiển motor/servo. ESP32 không tự chụp ảnh hoặc chạy model AI.
 *   Nút trên web -> cloud -> bridge trên laptop -> lệnh USB Serial cho ESP32.
 *
 * Chu trình một quả:
 *   Bắt đầu -> motor DỪNG chờ vật ở IR đầu vào -> IR phát hiện -> motor chạy
 *   -> tới vị trí chụp -> dừng, chờ ổn định -> chụp/chờ AI -> chạy tiếp, gạt
 *   -> hết thời gian thoát khay -> motor DỪNG chờ vật mới, giữ nguyên phiên.
 *   GREEN: servo 1; RIPE: servo 2; REJECT: đi thẳng đến khay cuối.
 *
 * Cấu hình chân nối/thời gian/góc: StationConfig.h.
 * Máy trạng thái và kiểm tra lệnh: Controller.h.
 * File này áp dụng trạng thái đó lên GPIO, đọc lệnh và gửi phản hồi Serial.
 * Mỗi lượt chỉ có một quả; không dùng Wi-Fi/MQTT hay thư viện servo bên ngoài.
 */
#include <Arduino.h>
#include <esp_arduino_version.h>
#include "Controller.h"

#if ESP_ARDUINO_VERSION_MAJOR < 3
#error "Select Arduino-ESP32 core 3.x (tested 3.3.12)"
#endif

using namespace autosort::hardware;

autosort::Controller controller(STATION_CONFIG);
// Theo dõi PWM đã sẵn sàng hay đang khóa lỗi phần cứng.
bool pwmReady = false, hardwareFault = false;
// Ghi nhớ đầu ra đã áp dụng để chỉ cập nhật PWM/Servo khi có thay đổi.
uint8_t appliedMotorPwm = 0;
uint8_t appliedGate1 = STATION_CONFIG.gate1RestDeg, appliedGate2 = STATION_CONFIG.gate2RestDeg;
// Lệnh Serial kết thúc bằng '\n'; bộ đệm chứa tối đa 127 ký tự và ký tự kết thúc chuỗi.
char lineBuffer[128];
size_t lineLength = 0;
// Dòng hỏng sẽ bị bỏ đến hết '\n'; partialSince dùng phát hiện dòng nhận dở quá lâu.
bool discardLine = false;
uint32_t partialSince = 0;

// Đổi mức điện của cảm biến thành true = có vật chắn, theo IR_ACTIVE_LOW.
bool irBlocked() {
  return digitalRead(PIN_IR) == (IR_ACTIVE_LOW ? LOW : HIGH);
}

uint32_t servoDuty(uint8_t degrees) {
  // Đổi góc thành độ rộng xung (micro giây), rồi thành giá trị PWM 14 bit.
  // Servo 50 Hz có chu kỳ 20.000 micro giây; cộng 10.000 để làm tròn phép chia.
  const uint32_t pulse = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * degrees / 180;
  return (pulse * ((1U << SERVO_BITS) - 1) + 10000) / 20000;
}

bool setMotor(uint8_t pwm) {
  // Tắt xung trước khi đổi chân chiều/phanh.
  if (!ledcWrite(PIN_MOTOR_INA1, 0)) return false;
  const bool running = (pwm > 0);
  digitalWrite(PIN_MOTOR_INA2, !running && DYNAMIC_BRAKE ? HIGH : LOW);
  return ledcWrite(PIN_MOTOR_INA1, running ? pwm : (DYNAMIC_BRAKE ? 255 : 0));
}

void hardwareStop() {
  // Khi PWM lỗi: cố đưa motor về LOW/LOW và servo về góc nghỉ, rồi khóa đến khi reset.
  // Đây là thao tác cố gắng dừng; không phải xác nhận motor vật lý đã ngừng quay.
  ledcWrite(PIN_MOTOR_INA1, 0);
  ledcDetach(PIN_MOTOR_INA1);
  pinMode(PIN_MOTOR_INA1, OUTPUT);
  digitalWrite(PIN_MOTOR_INA1, LOW);
  digitalWrite(PIN_MOTOR_INA2, LOW);
  ledcWrite(PIN_SERVO1, servoDuty(STATION_CONFIG.gate1RestDeg));
  ledcWrite(PIN_SERVO2, servoDuty(STATION_CONFIG.gate2RestDeg));
  hardwareFault = true;
  controller.stop("PWM_FAILURE");
}

bool applyOutputs() {
  if (hardwareFault || !pwmReady) return false;

  // Kiểm tra nếu giá trị PWM yêu cầu thay đổi thì xuất PWM mới ra phần cứng
  if (controller.motorPwm() != appliedMotorPwm) {
    if (!setMotor(controller.motorPwm())) { hardwareStop(); return false; }
    appliedMotorPwm = controller.motorPwm();
  }

  if (controller.gate1() != appliedGate1) {
    if (!ledcWrite(PIN_SERVO1, servoDuty(controller.gate1()))) { hardwareStop(); return false; }
    appliedGate1 = controller.gate1();
  }
  if (controller.gate2() != appliedGate2) {
    if (!ledcWrite(PIN_SERVO2, servoDuty(controller.gate2()))) { hardwareStop(); return false; }
    appliedGate2 = controller.gate2();
  }
  return true;
}

void readCommands(uint32_t now) {
  // Mỗi vòng chỉ đọc tối đa 64 byte để vẫn kiểm tra cảm biến, thời gian và mất kết nối.
  // Dữ liệu có thể đến thành nhiều đoạn; chỉ xử lý sau khi nhận đủ dấu xuống dòng.
  for (int n = 0; n < 64 && Serial.available(); ++n) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\n') {
      if (!discardLine) {
        // Chấp nhận cả LF và CRLF do phần mềm gửi lệnh có thể dùng hai kiểu xuống dòng.
        if (lineLength && lineBuffer[lineLength - 1] == '\r') --lineLength;
        lineBuffer[lineLength] = '\0';
        controller.command(lineBuffer, now);
      }
      lineLength = 0;
      discardLine = false;
    } else if (!discardLine) {
      if (lineLength == 0) partialSince = now;
      // Ký tự điều khiển lạ hoặc dòng quá dài đều làm dừng trạm và khóa lỗi.
      if (static_cast<unsigned char>(ch) < 32 && ch != '\r') {
        controller.stop("SERIAL_FORMAT"); discardLine = true;
      } else if (lineLength >= sizeof(lineBuffer) - 1) {
        controller.stop("SERIAL_OVERFLOW"); discardLine = true;
      } else lineBuffer[lineLength++] = ch;
    }
  }
  if (lineLength && static_cast<uint32_t>(now - partialSince) >= 1000) {
    // Không chờ vô hạn một lệnh thiếu '\n': sau 1 giây báo lỗi và bỏ phần dòng còn lại.
    controller.stop("SERIAL_PARTIAL_LINE");
    discardLine = true;
    lineLength = 0;
  }
}

void setup() {
  // Đưa hai chân motor xuống LOW ngay khi khởi động, trước khi chờ laptop kết nối.
  pinMode(PIN_MOTOR_INA1, OUTPUT); digitalWrite(PIN_MOTOR_INA1, LOW);
  pinMode(PIN_MOTOR_INA2, OUTPUT); digitalWrite(PIN_MOTOR_INA2, LOW);
  pinMode(PIN_IR, INPUT);
  Serial.begin(SERIAL_BAUD);
  // Motor: kênh 0, 1.000 Hz, 8 bit; servo: kênh 2 và 3, 50 Hz, 14 bit.
  // Arduino-ESP32 tự quản lý bộ định thời; cần core 3.x vì dùng ledcAttachChannel().
  pwmReady = ledcAttachChannel(PIN_MOTOR_INA1, 1000, 8, 0)
      && ledcAttachChannel(PIN_SERVO1, 50, SERVO_BITS, 2)
      && ledcAttachChannel(PIN_SERVO2, 50, SERVO_BITS, 3);
  controller.begin(millis(), irBlocked());  // Chờ bridge; kết nối xong vẫn chưa chạy motor.
  if (!pwmReady || !setMotor(0)
      || !ledcWrite(PIN_SERVO1, servoDuty(STATION_CONFIG.gate1RestDeg))
      || !ledcWrite(PIN_SERVO2, servoDuty(STATION_CONFIG.gate2RestDeg))) {
    hardwareStop();
    Serial.println("FAULT:PWM_FAILURE");
    return;
  }
  Serial.println("CONTROLLER:WAIT_BRIDGE");  // Laptop cần kết nối rồi nhận xác nhận IDLE.
}

void loop() {
  // Ghi nhớ trạng thái đã báo, tránh gửi lặp liên tục cùng một trạng thái lên laptop.
  static autosort::State reported = autosort::State::WAIT_BRIDGE;
  static uint32_t lastStats = 0;
  const uint32_t now = millis();
  readCommands(now);                      // 1. Nhận lệnh web/PING/kết quả AI từ laptop.
  controller.tick(now, irBlocked());      // 2. Cập nhật chu trình theo IR và thời gian.
  const bool applied = applyOutputs();   // 3. Ghi thay đổi motor/servo ra phần cứng.
  // 4. Chỉ xác nhận lệnh và yêu cầu chụp sau khi đã áp dụng đầu ra thành công.
  // ACK xác nhận phần mềm đã ghi đầu ra; không thay thế cảm biến chuyển động motor.
  if(applied && reported==autosort::State::WAIT_BRIDGE && controller.state()==autosort::State::IDLE) Serial.println("CONTROLLER:IDLE");
  if(applied && controller.takeAck()) Serial.printf("ACK:%s:%s\n",controller.ackId(),controller.ackState());
  if (applied && reported == autosort::State::WAIT_BRIDGE && controller.state() == autosort::State::RUNNING) {
    // Tương thích bridge cũ: RUNNING báo phiên đã arm; motor vẫn chờ vật ở IR.
    Serial.printf("CONTROLLER:RUNNING:%s\n", controller.session());
  }
  if (applied && controller.takeTrigger()) {
    // Báo laptop chụp một ảnh; mã lượt chạy và số thứ tự quả dùng ghép đúng kết quả.
    Serial.printf("TRIGGER:%s:%lu\n", controller.session(), static_cast<unsigned long>(controller.counter()));
  }
  if (controller.state() != reported) {
    // FAULT có mã nguyên nhân; STATE là giá trị enum được khai báo trong Controller.h.
    reported = controller.state();
    if (reported == autosort::State::FAULT) Serial.printf("FAULT:%s\n", controller.fault());
    else Serial.printf("STATE:%u\n", static_cast<unsigned>(reported));
  }
  if (static_cast<uint32_t>(now - lastStats) >= 3000) {
    // Số lượt phân loại phần mềm từ lúc reset, không phải số đo từ cảm biến ở khay.
    lastStats = now;
    Serial.printf("COUNTS:G=%lu,R=%lu,X=%lu\n", static_cast<unsigned long>(controller.green()),
                  static_cast<unsigned long>(controller.ripe()), static_cast<unsigned long>(controller.rejected()));
  }
  delay(1);  // Nhường CPU 1 ms; chu trình không dùng delay dài để chờ AI hoặc chờ servo.
}
