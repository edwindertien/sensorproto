#include <Arduino.h>
#include <Servo.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// BLDC motor with standard ESC controlled by 50 Hz servo PWM.
// Servo signal on pin 9.  No feedback.
//
// ESC arming sequence: full throttle → low throttle (done once in setup).
// The ESC's full-throttle pulse is ~2000 µs, idle ~1000 µs.
//
// Params (set via serial):
//   !servo.us:1500             direct µs (1000..2000)
//   !servo.arm:1               re-run arm sequence
//   !servo.dir:1               (ESC must support reverse; flip if needed)
//
// Stream 1: echoes the commanded pulse width (for logging)
//
// TODO: add mod_adc on A0 for a pot throttle input when desired.
// ─────────────────────────────────────────────────────────────────────────────

#define SERVO_PIN 9
#define US_MIN    1000
#define US_MAX    2000
#define US_IDLE   1000

UniProto proto(Serial, "BLDCServo");
Servo esc;

static uint16_t _us = US_IDLE;

// ---- emit ----
static void emitServo(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    w.begin(sid);
    w.u16(_us, "us");
    w.end();
}

// ---- params ----
static bool getServo(UniProto&, const char* key, char* out, size_t outLen, void* /*ctx*/) {
    if (!strcmp(key, "servo.us")) { snprintf(out, outLen, "%u", (unsigned)_us); return true; }
    return false;
}
static bool setServo(UniProto&, const char* key, const char* value, void* /*ctx*/) {
    if (!strcmp(key, "servo.us")) {
        long v = UniProto::parseInt(value);
        if (v < US_MIN) v = US_MIN;
        if (v > US_MAX) v = US_MAX;
        _us = (uint16_t)v;
        esc.writeMicroseconds(_us);
        return true;
    }
    return false;
}

// ---- arm action ----
static bool doArm(UniProto&, const char*, const char*, Stream& out, void* /*ctx*/) {
    esc.writeMicroseconds(US_MAX);
    delay(2000);
    esc.writeMicroseconds(US_MIN);
    delay(2000);
    _us = US_IDLE;
    out.println(F("armed"));
    return true;
}

void setup() {
    Serial.begin(115200);
    esc.attach(SERVO_PIN);

    // Arm the ESC
    esc.writeMicroseconds(US_MAX);
    delay(2000);
    esc.writeMicroseconds(US_MIN);
    delay(2000);

    proto.begin();
    proto.registerStream({1, "servo", "u16", "us", emitServo, nullptr});
    proto.registerParam({"servo.us", UniProto::ParamType::INT32, getServo, setServo, nullptr});
    proto.registerAction({"servo.arm", doArm, nullptr});
}

void loop() {
    proto.tick();
}
