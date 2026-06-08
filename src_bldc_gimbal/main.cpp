#include <Arduino.h>
#include <Wire.h>
#include "UniProto.h"
#include "mod_bldc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// BLDC gimbal motor with AS5600 absolute hall-effect position sensor.
// Driver: M5Stack Unit BLDC (DRV11873), STM32 co-processor, I2C address 0x65 (V1).
// Also suitable for haptic feedback knob use cases.
//
// Control sources (!bldc.src):
//   0 = external loop (Arduino runs PID/spring/detent, sends open-loop PWM)
//   1 = STM32 closed-loop speed (rpm)
//
// External modes (!bldc.mode when src=0):
//   0 open-loop cmd   1 PID position   2 spring-damper   3 endstops   4 detents
//
// Useful commands:
//   Wire.setClock(400000) is set in setup — keep it
//   !stream:6
//   @bldc.zero                 zero the position counter
//   !bldc.enable:1
//   !bldc.src:0
//   !bldc.mode:2               spring-damper
//   !bldc.spring_k:5.0
//   !bldc.damp_b:0.3
//   !bldc.set:0.0              hold at zero rad
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "BLDCGimbal");
BldcModule bldc(BldcModule::defaultUno());

void setup() {
    Serial.begin(115200);
    Wire.begin();
    Wire.setClock(400000);
    proto.begin();
    bldc.registerWith(proto);
}

void loop() {
    proto.tick();
    bldc.poll();
}
