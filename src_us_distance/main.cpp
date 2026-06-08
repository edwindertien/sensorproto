#include <Arduino.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// HC-SR04 ultrasonic distance sensor.
// TRIG=7, ECHO=8.  Range: 2..400 cm.
// No external library needed — timing via pulseIn().
//
// Streams:
//   stream 1 — distance in cm (f32) and raw pulse µs (u16)
//
// NOTE: pulseIn() blocks for up to 23 ms (400 cm at 343 m/s roundtrip).
// Cap with timeout to avoid starving the serial command parser at high rates.
// Recommended rate: ≤20 Hz.
// ─────────────────────────────────────────────────────────────────────────────

#define TRIG_PIN  7
#define ECHO_PIN  8
#define TIMEOUT_US 23000UL   // 400 cm limit

UniProto proto(Serial, "UltrasoundDist");

static float _cm = 0.0f;
static uint16_t _us = 0;

static void emitDist(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* /*ctx*/) {
    // Trigger pulse
    digitalWrite(TRIG_PIN, LOW);
    delayMicroseconds(2);
    digitalWrite(TRIG_PIN, HIGH);
    delayMicroseconds(10);
    digitalWrite(TRIG_PIN, LOW);

    const unsigned long dur = pulseIn(ECHO_PIN, HIGH, TIMEOUT_US);
    _us = (dur == 0) ? 0 : (uint16_t)dur;
    _cm = (_us == 0) ? 0.0f : (_us * 0.01715f); // µs → cm (speed of sound / 2)

    w.begin(streamId);
    w.f32(_cm, "cm", 1);
    w.u16(_us, "us");
    w.end();
}

void setup() {
    pinMode(TRIG_PIN, OUTPUT);
    pinMode(ECHO_PIN, INPUT);
    digitalWrite(TRIG_PIN, LOW);

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(10);

    proto.registerStream({1, "dist", "f32,u16", "cm,us", emitDist, nullptr});
}

void loop() {
    proto.tick();
}
