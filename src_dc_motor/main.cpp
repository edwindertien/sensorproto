#include <Arduino.h>
#include "UniProto.h"
#include "mod_motors.h"

// ── Device ────────────────────────────────────────────────────────────────────
// 1:30 geared DC motor, 200 PPR incremental encoder.
// Driver: Arduino Motor Shield (L298P)
//   Channel A: PWM=3, DIR=12, BRAKE=9, CS=A0
//   (only one motor — motor1 unused, streams still registered but silent)
//
// Encoder wiring: A=2 (INT0), B=4  (standard quadrature, CHANGE interrupts)
//
// Key commands:
//   !motor0.enable:1           engage PID
//   !motor0.kp:2.0             tune P gain
//   !motor0.set:400            move to 400 ticks (2 revs of output shaft)
//   !motor0.pwm_lim:180        cap effort
//   !stream:3                  start streaming
//   @motor.zero                rezero encoder
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "DCMotor");

// Arduino Motor Shield ch-A pinout
static DualMotorModule::Config makeCfg() {
    DualMotorModule::Config c;
    // Encoder
    c.encA0 = 2;   // INT0
    c.encB0 = 4;
    c.encA1 = 3;   // INT1 — unused second motor, won't interfere
    c.encB1 = 5;
    // Motor Shield channel A
    c.pwm0  = 3;
    c.dir0  = 12;
    // Motor Shield channel B (unused, parked)
    c.pwm1  = 11;
    c.dir1  = 13;
    // The Motor Shield uses DIR_PWM, active-high direction
    c.driveMode         = DualMotorModule::Config::DriveMode::DIR_PWM;
    c.invertPwmOnDirHigh = false;
    c.invertDir0        = false;
    c.invertDir1        = false;
    c.pwmHz             = 31372; // ultrasonic on Timer2 (pin 3)
    c.streamId    = 3;
    c.streamIdRaw = 4;
    return c;
}

DualMotorModule motors(makeCfg());

void setup() {
    Serial.begin(115200);
    proto.begin();
    motors.registerWith(proto);
}

void loop() {
    proto.tick();
    motors.poll();
}
