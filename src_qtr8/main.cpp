#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// QTR-8 optical reflection sensor array → absolute gray-code position.
// Analog outputs on A0..A5 (6 sensors; remaining 2 on digital 6,7 as analog
// via analogRead if using a MEGA or mapping on an Uno — see note below).
//
// Gray code decoding: threshold each sensor (raw > 512 = 1, else 0),
// then decode 6-bit gray code → binary position.
//
// Stream 1: raw ADC values (6 channels)
// Stream 2: decoded position (u16 0..63) + gray code byte (u16)
//
// NOTE on QTR-8 + Uno: only 6 analog pins available. Use 6-bit code (64 positions).
// For full 8 sensors on Uno you'd need two ADC channels via CD4051 mux (future).
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "QTR8");

static uint16_t _threshold = 512; // per-sensor digital threshold
static uint16_t _raw[6] = {};

// Gray-to-binary decode
static uint8_t grayToBinary(uint8_t g) {
    uint8_t b = 0;
    for (; g; g >>= 1) b ^= g;
    return b;
}

// ---- raw ADC stream ----
static AdcModule::Config makeAdcCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 6;
    for (uint8_t i = 0; i < 6; i++) c.channels[i] = A0 + i;
    c.avgWindow   = 1; // no averaging — need fast digital thresholding
    c.valuesCount = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "qtr.raw";
    c.values[0].schema = "u16,u16,u16,u16,u16,u16";
    c.values[0].units  = "s0,s1,s2,s3,s4,s5";
    c.values[0].selCount = 0;
    return c;
}
AdcModule rawAdc(makeAdcCfg());

// ---- decoded position stream ----
static void emitPos(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    for (uint8_t i = 0; i < 6; i++) _raw[i] = (uint16_t)analogRead(A0 + i);
    uint8_t gray = 0;
    for (uint8_t i = 0; i < 6; i++) {
        if (_raw[i] > _threshold) gray |= (1 << i);
    }
    uint8_t pos = grayToBinary(gray);
    w.begin(sid);
    w.u16(pos,  "pos");
    w.u16(gray, "gray");
    w.end();
}

static bool getQtr(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "qtr.threshold")) { snprintf(out, outLen, "%u", (unsigned)_threshold); return true; }
    return false;
}
static bool setQtr(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "qtr.threshold")) {
        long v = UniProto::parseInt(value);
        if (v < 0) v = 0; if (v > 1023) v = 1023;
        _threshold = (uint16_t)v; return true;
    }
    return false;
}

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);
    rawAdc.registerWith(proto);
    proto.registerStream({2, "qtr.pos", "u16,u16", "pos,gray", emitPos, nullptr});
    proto.registerParam({"qtr.threshold", UniProto::ParamType::INT32, getQtr, setQtr, nullptr});
}

void loop() {
    proto.tick();
}
