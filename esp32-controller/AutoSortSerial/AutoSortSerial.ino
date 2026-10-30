// ESP32 Dev Module, Arduino-ESP32 3.3.12. Camera: phone, inference: existing cloud.
// One fruit on the belt at a time. No Wi-Fi, MQTT or third-party servo library.
#include <Arduino.h>
#include <esp_arduino_version.h>
#include "Controller.h"

#if ESP_ARDUINO_VERSION_MAJOR < 3
#error "Select Arduino-ESP32 core 3.x (tested 3.3.12)"
#endif

constexpr int PIN_IR = 14;
constexpr int PIN_SERVO1 = 18;
constexpr int PIN_SERVO2 = 19;
constexpr int PIN_MOTOR_INA1 = 16;
constexpr int PIN_MOTOR_INA2 = 17;
constexpr uint32_t MOTOR_SPEED_PWM = 150;
constexpr uint32_t SERVO_MIN_US = 500, SERVO_MAX_US = 2400;
constexpr uint8_t SERVO_BITS = 14;
// Retains the supplied MX1508 HIGH/HIGH stop; disable if the actual driver needs coast.
constexpr bool DYNAMIC_BRAKE = true;

autosort::Controller controller;
bool pwmReady = false, hardwareFault = false;
bool appliedMotor = false;
uint8_t appliedGate1 = 0, appliedGate2 = 0;
char lineBuffer[128];
size_t lineLength = 0;
bool discardLine = false;
uint32_t partialSince = 0;

uint32_t servoDuty(uint8_t degrees) {
  const uint32_t pulse = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * degrees / 180;
  return (pulse * ((1U << SERVO_BITS) - 1) + 10000) / 20000;
}

bool setMotor(bool running) {
  // Stop PWM before changing direction/brake input; never mix digitalWrite on its PWM pin.
  if (!ledcWrite(PIN_MOTOR_INA1, 0)) return false;
  digitalWrite(PIN_MOTOR_INA2, !running && DYNAMIC_BRAKE ? HIGH : LOW);
  return ledcWrite(PIN_MOTOR_INA1, running ? MOTOR_SPEED_PWM : (DYNAMIC_BRAKE ? 255 : 0));
}

void hardwareStop() {
  // Best effort if PWM itself failed; latch until reset, never try to restart automatically.
  ledcWrite(PIN_MOTOR_INA1, 0);
  ledcDetach(PIN_MOTOR_INA1);
  pinMode(PIN_MOTOR_INA1, OUTPUT);
  digitalWrite(PIN_MOTOR_INA1, LOW);
  digitalWrite(PIN_MOTOR_INA2, LOW);
  ledcWrite(PIN_SERVO1, servoDuty(0));
  ledcWrite(PIN_SERVO2, servoDuty(0));
  hardwareFault = true;
  controller.stop("PWM_FAILURE");
}

bool applyOutputs() {
  if (hardwareFault || !pwmReady) return false;
  if (controller.motor() != appliedMotor) {
    if (!setMotor(controller.motor())) { hardwareStop(); return false; }
    appliedMotor = controller.motor();
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
  // Bounded per loop: serial noise must not starve timers and watchdogs.
  for (int n = 0; n < 64 && Serial.available(); ++n) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\n') {
      if (!discardLine) {
        if (lineLength && lineBuffer[lineLength - 1] == '\r') --lineLength;
        lineBuffer[lineLength] = '\0';
        controller.command(lineBuffer, now);
      }
      lineLength = 0;
      discardLine = false;
    } else if (!discardLine) {
      if (lineLength == 0) partialSince = now;
      if (static_cast<unsigned char>(ch) < 32 && ch != '\r') {
        controller.stop("SERIAL_FORMAT"); discardLine = true;
      } else if (lineLength >= sizeof(lineBuffer) - 1) {
        controller.stop("SERIAL_OVERFLOW"); discardLine = true;
      } else lineBuffer[lineLength++] = ch;
    }
  }
  if (lineLength && static_cast<uint32_t>(now - partialSince) >= 1000) {
    controller.stop("SERIAL_PARTIAL_LINE");
    discardLine = true;
    lineLength = 0;
  }
}

void setup() {
  pinMode(PIN_MOTOR_INA1, OUTPUT); digitalWrite(PIN_MOTOR_INA1, LOW);
  pinMode(PIN_MOTOR_INA2, OUTPUT); digitalWrite(PIN_MOTOR_INA2, LOW);
  pinMode(PIN_IR, INPUT);
  Serial.begin(115200);
  // Distinct channels, distinct motor/servo frequency. Core manages timer allocation.
  pwmReady = ledcAttachChannel(PIN_MOTOR_INA1, 1000, 8, 0)
      && ledcAttachChannel(PIN_SERVO1, 50, SERVO_BITS, 2)
      && ledcAttachChannel(PIN_SERVO2, 50, SERVO_BITS, 3);
  controller.begin(millis(), digitalRead(PIN_IR) == LOW);
  if (!pwmReady || !setMotor(false)
      || !ledcWrite(PIN_SERVO1, servoDuty(0)) || !ledcWrite(PIN_SERVO2, servoDuty(0))) {
    hardwareStop();
    Serial.println("FAULT:PWM_FAILURE");
    return;
  }
  Serial.println("CONTROLLER:WAIT_BRIDGE");
}

void loop() {
  static autosort::State reported = autosort::State::WAIT_BRIDGE;
  static uint32_t lastStats = 0;
  const uint32_t now = millis();
  readCommands(now);
  controller.tick(now, digitalRead(PIN_IR) == LOW);
  const bool applied = applyOutputs();
  if(applied && reported==autosort::State::WAIT_BRIDGE && controller.state()==autosort::State::IDLE) Serial.println("CONTROLLER:IDLE");
  if(applied && controller.takeAck()) Serial.printf("ACK:%s:%s\n",controller.ackId(),controller.ackState());
  if (applied && reported == autosort::State::WAIT_BRIDGE && controller.state() == autosort::State::RUNNING) {
    Serial.printf("CONTROLLER:RUNNING:%s\n", controller.session());
  }
  if (applied && controller.takeTrigger()) {
    Serial.printf("TRIGGER:%s:%lu\n", controller.session(), static_cast<unsigned long>(controller.counter()));
  }
  if (controller.state() != reported) {
    reported = controller.state();
    if (reported == autosort::State::FAULT) Serial.printf("FAULT:%s\n", controller.fault());
    else Serial.printf("STATE:%u\n", static_cast<unsigned>(reported));
  }
  if (static_cast<uint32_t>(now - lastStats) >= 3000) {
    lastStats = now;
    Serial.printf("COUNTS:G=%lu,R=%lu,X=%lu\n", static_cast<unsigned long>(controller.green()),
                  static_cast<unsigned long>(controller.ripe()), static_cast<unsigned long>(controller.rejected()));
  }
  delay(1);  // Yield one millisecond; no blocking network, AI or actuator delays.
}
