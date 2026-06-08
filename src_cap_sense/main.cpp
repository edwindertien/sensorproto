#include <Arduino.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Variable capacitor — charge-time (RC) sensing strategy.
// Drive pin (SEND=4) charges the cap through a 10 MΩ resistor.
// Sense pin (SENSE=A0) reads the voltage via analogRead during charge.
// Charge count correlates with capacitance.
//
// Two measurement strategies available (set via !cap.mode):
//   0 = count-to-threshold: count cycles until A0 > threshold (like CapSense lib)
//   1 = analogRead: read raw voltage at a fixed delay after charge pulse
//
// Stream 1: cap value (u16), raw cycles or ADC reading
//
// Params:
//   !cap.mode:0                mode 0 or 1
//   !cap.threshold:700         ADC threshold for mode 0 (out of 1023)
//   !cap.samples:10            averages per measurement
// ─────────────────────────────────────────────────────────────────────────────

#define SEND_PIN  4
#define SENSE_PIN A0

UniProto proto(Serial, "CapSense");

static uint8_t  _mode      = 0;
static uint16_t _threshold = 700;
static uint8_t  _samples   = 10;
static uint16_t _last      = 0;

static uint16_t measureCount() {
    uint32_t total = 0;
    for (uint8_t s = 0; s < _samples; s++) {
        // discharge
        pinMode(SENSE_PIN, OUTPUT);
        digitalWrite(SENSE_PIN, LOW);
        pinMode(SENSE_PIN, INPUT);
        // count charge cycles
        uint16_t count = 0;
        while (analogRead(SENSE_PIN) < (int)_threshold && count < 60000) {
            digitalWrite(SEND_PIN, HIGH);
            count++;
        }
        digitalWrite(SEND_PIN, LOW);
        // discharge again
        pinMode(SENSE_PIN, OUTPUT);
        digitalWrite(SENSE_PIN, LOW);
        pinMode(SENSE_PIN, INPUT);
        total += count;
    }
    return (uint16_t)(total / _samples);
}

static uint16_t measureAnalog() {
    uint32_t total = 0;
    for (uint8_t s = 0; s < _samples; s++) {
        // discharge
        pinMode(SENSE_PIN, OUTPUT);
        digitalWrite(SENSE_PIN, LOW);
        delayMicroseconds(10);
        pinMode(SENSE_PIN, INPUT);
        // charge for fixed time
        digitalWrite(SEND_PIN, HIGH);
        delayMicroseconds(200);
        total += (uint16_t)analogRead(SENSE_PIN);
        digitalWrite(SEND_PIN, LOW);
    }
    return (uint16_t)(total / _samples);
}

static void emitCap(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    _last = (_mode == 0) ? measureCount() : measureAnalog();
    w.begin(sid);
    w.u16(_last, "cap");
    w.end();
}

static bool getCap(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "cap.mode"))      { snprintf(out, outLen, "%u", _mode);      return true; }
    if (!strcmp(key, "cap.threshold")) { snprintf(out, outLen, "%u", _threshold); return true; }
    if (!strcmp(key, "cap.samples"))   { snprintf(out, outLen, "%u", _samples);   return true; }
    return false;
}
static bool setCap(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "cap.mode"))      { _mode = (uint8_t)(UniProto::parseInt(value) & 1); return true; }
    if (!strcmp(key, "cap.threshold")) { _threshold = (uint16_t)UniProto::parseInt(value); return true; }
    if (!strcmp(key, "cap.samples"))   {
        long v = UniProto::parseInt(value); if (v < 1) v = 1; if (v > 50) v = 50;
        _samples = (uint8_t)v; return true;
    }
    return false;
}

void setup() {
    pinMode(SEND_PIN, OUTPUT);
    digitalWrite(SEND_PIN, LOW);

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(20);
    proto.registerStream({1, "cap", "u16", "counts", emitCap, nullptr});
    proto.registerParam({"cap.mode",      UniProto::ParamType::INT32, getCap, setCap, nullptr});
    proto.registerParam({"cap.threshold", UniProto::ParamType::INT32, getCap, setCap, nullptr});
    proto.registerParam({"cap.samples",   UniProto::ParamType::INT32, getCap, setCap, nullptr});
}

void loop() {
    proto.tick();
}
