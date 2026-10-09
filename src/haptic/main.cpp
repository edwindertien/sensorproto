#include <Arduino.h>
#include "UniProto.h"
#include "mod_motors.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Haptic master-slave: two 1:10 Maxon mini-motors + incremental encoders
// on L293 H-bridge.
//
// Confirmed specs (measured 2025-06):
//   500 ticks/rev on output shaft
//   ~220 RPM output @ PWM=80 (~31% duty, 5V supply)
//   Encoder likely 100 PPR × 5:1 gear (or similar combination = 500 ticks/rev)
//
// Pins (L293, defaultUno):
//   Encoders : A=2(INT0),B=4  and  A=3(INT1),B=5
//   Motor 0  : PWM=10, DIR=8
//   Motor 1  : PWM=11, DIR=9
//
// Link modes (!motor.link):
//   0 = independent
//   1 = motor0 follows motor1 (m0 slave, m1 master handle)
//   2 = motor1 follows motor0
//   3 = bidirectional hard coupling
//
// Typical bring-up sequence:
//   !stream:3
//   !rate:50
//   !motor0.kp:1.5  !motor1.kp:1.5
//   !motor0.pwm_lim:180  !motor1.pwm_lim:180
//   !motor0.enable:1  !motor1.enable:1
//   !motor0.set:500        (1 full revolution)
//   !motor.link:3          (bidirectional haptic coupling)
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "Haptic");

DualMotorModule motors(DualMotorModule::defaultUno());

void setup() {
    Serial.begin(115200);
    proto.begin();
    motors.registerWith(proto);
}

void loop() {
    proto.tick();
    motors.poll();
}