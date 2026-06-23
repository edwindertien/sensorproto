#include <Arduino.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Grove GSR sensor       → A0 (analog, yellow wire on Grove shield)
// Grove ear-clip heart   → A4 (analog read of digital pulse output)
//
// Both sensors sampled at 50Hz — fast enough to see the pulse waveform
// clearly (typical HR 60-120 BPM = 1-2 Hz, Nyquist needs >4Hz).
//
// Stream 1: gsr(u16), hr_raw(u16)
//
// GSR: raw ADC 0-1023. Higher = more resistance = less arousal.
//   Skin conductance = inverse. Slow signal, changes over seconds.
//
// Heart rate: raw ADC from A4. The ear-clip outputs a digital signal
//   but we read it as analog — gives 0 or ~1023 (5V digital).
//   Peak detection done in Python from the waveform.
//   Note: Grove I2C socket connects to A4/A5 — no I2C devices
//   should be present on this sketch.
// ─────────────────────────────────────────────────────────────────────────────

#define PIN_GSR  A0
#define PIN_HR   A5   // Grove I2C socket SCL pin, used as plain analog in

UniProto proto(Serial, "BioSensors");

static void emitBio(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    uint16_t gsr = (uint16_t)analogRead(PIN_GSR);
    uint16_t hr  = (uint16_t)analogRead(PIN_HR);
    w.begin(sid);
    w.u16(gsr, "gsr");
    w.u16(hr,  "hr");
    w.end();
}

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);
    proto.registerStream({1, "bio", "u16,u16", "raw,raw", emitBio, nullptr});
}

void loop() {
    proto.tick();
}