#include <Arduino.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Variable capacitor ~200pF.
// SENSE = A0  (read voltage)
// SEND  = A3  (charge through 10 MΩ resistor)
//
// RC time constant: τ = R×C = 10e6 × 200e-12 = 2ms
// At 200µs charge time we're at ~10% of full charge — well in the linear range,
// giving good sensitivity to capacitance changes.
//
// Modes (!cap.mode):
//   0 = analog voltage after fixed charge delay (best for small C, default)
//   1 = count-to-threshold (better for larger C)
//
// Params:
//   !cap.mode:0
//   !cap.delay:200        charge delay in µs for mode 0 (default 200)
//   !cap.threshold:700    ADC threshold for mode 1
//   !cap.samples:8        averages per reading
// ─────────────────────────────────────────────────────────────────────────────

#define SENSE_PIN  A0
#define SEND_PIN   A3

UniProto proto(Serial, "CapSense");

static uint8_t  _mode      = 0;      // 0=analog, 1=count
static uint16_t _chargeUs  = 200;    // charge delay µs (mode 0)
static uint16_t _threshold = 700;    // ADC threshold (mode 1)
static uint8_t  _samples   = 8;
static uint16_t _last      = 0;

static void discharge() {
    pinMode(SENSE_PIN, OUTPUT);
    digitalWrite(SENSE_PIN, LOW);
    delayMicroseconds(50);
    pinMode(SENSE_PIN, INPUT);
}

static uint16_t measureAnalog() {
    uint32_t total = 0;
    for (uint8_t s = 0; s < _samples; s++) {
        discharge();
        digitalWrite(SEND_PIN, HIGH);
        delayMicroseconds(_chargeUs);
        total += (uint16_t)analogRead(SENSE_PIN);
        digitalWrite(SEND_PIN, LOW);
        discharge();
    }
    return (uint16_t)(total / _samples);
}

static uint16_t measureCount() {
    uint32_t total = 0;
    for (uint8_t s = 0; s < _samples; s++) {
        discharge();
        uint16_t count = 0;
        while (analogRead(SENSE_PIN) < (int)_threshold && count < 60000) {
            digitalWrite(SEND_PIN, HIGH);
            count++;
        }
        digitalWrite(SEND_PIN, LOW);
        discharge();
        total += count;
    }
    return (uint16_t)(total / _samples);
}

static void emitCap(UniProto& p, uint8_t sid, UniFrameWriter& w, void*) {
    _last = (_mode == 0) ? measureAnalog() : measureCount();
    w.begin(sid);
    w.u16(_last, "cap");
    w.end();
}

static bool getCap(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "cap.mode"))      { snprintf(out, outLen, "%u",  _mode);      return true; }
    if (!strcmp(key, "cap.delay"))     { snprintf(out, outLen, "%u",  _chargeUs);  return true; }
    if (!strcmp(key, "cap.threshold")) { snprintf(out, outLen, "%u",  _threshold); return true; }
    if (!strcmp(key, "cap.samples"))   { snprintf(out, outLen, "%u",  _samples);   return true; }
    return false;
}
static bool setCap(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "cap.mode"))      { _mode      = (uint8_t)(UniProto::parseInt(value) & 1); return true; }
    if (!strcmp(key, "cap.delay"))     { _chargeUs  = (uint16_t)constrain(UniProto::parseInt(value), 10, 5000); return true; }
    if (!strcmp(key, "cap.threshold")) { _threshold = (uint16_t)UniProto::parseInt(value); return true; }
    if (!strcmp(key, "cap.samples"))   {
        long v = UniProto::parseInt(value);
        _samples = (uint8_t)constrain(v, 1, 50);
        return true;
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
    proto.registerParam({"cap.delay",     UniProto::ParamType::INT32, getCap, setCap, nullptr});
    proto.registerParam({"cap.threshold", UniProto::ParamType::INT32, getCap, setCap, nullptr});
    proto.registerParam({"cap.samples",   UniProto::ParamType::INT32, getCap, setCap, nullptr});
}

void loop() {
    proto.tick();
}