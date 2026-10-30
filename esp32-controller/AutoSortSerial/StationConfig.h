#pragma once
#include <stdint.h>

namespace autosort {

// Initial bench values only. Calibrate on the actual conveyor before acceptance.
// Time unit: ms. Angles: 0..180 degrees. Zero travel delay supports an IR at the camera.
struct Config {
  uint32_t irToCameraMs = 300;
  uint32_t settleMs = 150;
  uint32_t cameraToGate1Ms = 1200;
  uint32_t cameraToGate2Ms = 2500;
  uint32_t gate1HoldMs = 400;
  uint32_t gate2HoldMs = 400;
  uint32_t exitClearMs = 500;
  uint8_t gate1RestDeg = 0;
  uint8_t gate1SortDeg = 90;
  uint8_t gate2RestDeg = 0;
  uint8_t gate2SortDeg = 90;

  // Protocol/watchdogs: coordinate changes with the PC bridge, not just mechanics.
  uint32_t aiTimeoutMs = 30000;
  uint32_t heartbeatMs = 5000;
  uint32_t debounceMs = 20;

  constexpr bool valid() const {
    return settleMs > 0 && settleMs < 0x80000000UL
        && irToCameraMs < 0x80000000UL
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

  uint32_t dispatchWindowMs() const {
    const uint32_t first = cameraToGate1Ms + gate1HoldMs;
    const uint32_t second = cameraToGate2Ms + gate2HoldMs;
    return (first > second ? first : second) + exitClearMs;
  }
};

namespace hardware {
constexpr int PIN_IR = 14;
constexpr bool IR_ACTIVE_LOW = true;
constexpr int PIN_SERVO1 = 18;
constexpr int PIN_SERVO2 = 19;
constexpr int PIN_MOTOR_INA1 = 16;
constexpr int PIN_MOTOR_INA2 = 17;
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint32_t MOTOR_SPEED_PWM = 150;  // 8-bit: 0..255
constexpr uint32_t SERVO_MIN_US = 500, SERVO_MAX_US = 2400;
constexpr uint8_t SERVO_BITS = 14;
// Supplied MX1508 uses HIGH/HIGH stop. Verify against the actual driver.
constexpr bool DYNAMIC_BRAKE = true;
constexpr Config STATION_CONFIG{};

static_assert(STATION_CONFIG.valid(), "Invalid station timing or servo angles");
static_assert(MOTOR_SPEED_PWM > 0 && MOTOR_SPEED_PWM <= 255, "Motor PWM must be 1..255");
static_assert(SERVO_MIN_US > 0 && SERVO_MIN_US < SERVO_MAX_US && SERVO_MAX_US < 20000,
              "Invalid servo pulse range");
}  // namespace hardware
}  // namespace autosort
