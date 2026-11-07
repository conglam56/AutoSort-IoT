#pragma once
#include <stdint.h>

namespace autosort {

namespace hardware {
// PWM motor 8 bit (0..255): Tốc độ chạy định mức chuẩn.
constexpr uint32_t MOTOR_SPEED_PWM = 180;
}

/*
 * CẤU HÌNH TRẠM: sửa chân nối, tốc độ, góc và thời gian tại file này.
 * Đã bổ sung:
 *   1. Delay khởi động IR (irStartDelayMs)
 *   2. Xung Kick-Start thắng ma sát nghỉ (kickStartMs, kickMotorPwm)
 *   3. Giảm tốc mượt dưới camera (rampDownMs, minMotorPwm)
 *   4. Lọc nhiễu IR nâng cao (debounceMs = 120ms)
 */
struct Config {
  // --- 1. CẤU HÌNH DELAY & XUNG KHỞI ĐỘNG (KICK-START) ---
  // Thời gian delay (ms) từ lúc IR phát hiện vật đến khi bật motor
  uint32_t irStartDelayMs = 600;
  // Thời gian nhấp xung mạnh lúc bắt đầu để thắng ma sát nghỉ (ms)
  uint32_t kickStartMs    = 80;
  // Tốc độ PWM xuất phát cao để thắng ma sát (0..255)
  uint8_t  kickMotorPwm   = 230;

  // --- 2. CẤU HÌNH DI CHUYỂN TỚI CAMERA & GIẢM TỐC ---
  // Từ lúc bắt đầu chạy đến lúc dừng hẳn motor tại vị trí chụp
  uint32_t irToCameraMs   = 700;
  // Thời gian thực hiện giảm tốc từ từ trước khi dừng (ms)
  uint32_t rampDownMs     = 300;
  // Tốc độ PWM nhỏ nhất khi giảm tốc (0..255)
  uint8_t  minMotorPwm    = 145;
  // Chờ quả và camera ổn định sau khi motor đã nhận lệnh dừng
  uint32_t settleMs       = 600;

  // --- 3. CẤU HÌNH CỬA GẠT SERVO & THỜI GIAN THOÁT QUẢ ---
  // Tính từ lúc nhận kết quả AI và bật motor chạy tiếp
  uint32_t cameraToGate1Ms = 1000;
  uint32_t cameraToGate2Ms = 1500;
  // Thời gian giữ servo ở góc gạt trước khi thu về góc nghỉ
  uint32_t gate1HoldMs     = 2100;
  uint32_t gate2HoldMs     = 2100;
  // Khoảng chờ thêm sau cửa sổ gạt xa nhất để quả thoát hoàn toàn
  uint32_t exitClearMs     = 500;

  // Góc nghỉ và góc gạt của các Servo (0..180 độ)
  uint8_t gate1RestDeg = 43;
  uint8_t gate1SortDeg = 0;
  uint8_t gate2RestDeg = 45;
  uint8_t gate2SortDeg = 0;

  // --- 4. CÁC MỐC BẢO VỆ & LỌC NHIỄU IR ---
  // Thời gian chờ phản hồi AI tối đa (ms)
  uint32_t aiTimeoutMs = 30000;
  // Hạn mất kết nối PING từ laptop/bridge (ms)
  uint32_t heartbeatMs = 10000;
  // Lọc nhiễu IR: thời gian giữ mức ổn định tối thiểu (ms)
  uint32_t debounceMs  = 120;

  // Kiểm tra giới hạn thời gian, thứ tự servo và góc để chặn cấu hình sai lúc biên dịch
  constexpr bool valid() const {
    return settleMs > 0 && settleMs < 0x80000000UL
        && irStartDelayMs < 0x80000000UL
        && irToCameraMs < 0x80000000UL
        && kickStartMs <= irToCameraMs
        && rampDownMs <= irToCameraMs - kickStartMs
        && (irToCameraMs == 0 || rampDownMs < irToCameraMs - kickStartMs)
        && kickMotorPwm > 0
        && minMotorPwm > 0 && minMotorPwm <= hardware::MOTOR_SPEED_PWM
        && aiTimeoutMs > 0 && aiTimeoutMs < 0x80000000UL
        && heartbeatMs > 0 && heartbeatMs < 0x80000000UL
        && debounceMs > 0 && debounceMs < 0x80000000UL
        && cameraToGate1Ms <= cameraToGate2Ms
        && gate1HoldMs > 0 && gate2HoldMs > 0
        && static_cast<uint64_t>(cameraToGate1Ms) + gate1HoldMs + exitClearMs < 0x80000000ULL
        && static_cast<uint64_t>(cameraToGate2Ms) + gate2HoldMs + exitClearMs < 0x80000000ULL
        && gate1RestDeg <= 180 && gate1SortDeg <= 180 && gate1RestDeg != gate1SortDeg
        && gate2RestDeg <= 180 && gate2SortDeg <= 180 && gate2RestDeg != gate2SortDeg;
  }

  // Đợi hết cửa sổ xa nhất của cả hai servo rồi cộng khoảng thoát quả
  uint32_t dispatchWindowMs() const {
    const uint32_t first = cameraToGate1Ms + gate1HoldMs;
    const uint32_t second = cameraToGate2Ms + gate2HoldMs;
    return (first > second ? first : second) + exitClearMs;
  }
};

namespace hardware {
// Chân GPIO phần cứng
constexpr int PIN_IR = 14;
constexpr bool IR_ACTIVE_LOW = true;

constexpr int PIN_SERVO1 = 18;
constexpr int PIN_SERVO2 = 19;

constexpr int PIN_MOTOR_INA1 = 16;
constexpr int PIN_MOTOR_INA2 = 17;

constexpr uint32_t SERIAL_BAUD = 115200;

constexpr uint32_t SERVO_MIN_US = 500, SERVO_MAX_US = 2400;
constexpr uint8_t SERVO_BITS = 14;
constexpr bool DYNAMIC_BRAKE = true;

constexpr Config STATION_CONFIG{};

// Kiểm tra lỗi cấu hình ngay khi biên dịch
static_assert(STATION_CONFIG.valid(), "Invalid station timing or servo angles");
static_assert(MOTOR_SPEED_PWM > 0 && MOTOR_SPEED_PWM <= 255, "Motor PWM must be 1..255");
static_assert(SERVO_MIN_US > 0 && SERVO_MIN_US < SERVO_MAX_US && SERVO_MAX_US < 20000,
              "Invalid servo pulse range");
}  // namespace hardware
}  // namespace autosort
