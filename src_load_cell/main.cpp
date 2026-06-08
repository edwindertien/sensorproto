#include <Arduino.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Load cell with HX711 24-bit ADC amplifier.
// HX711: DOUT=A1, SCK=A0.  Gain: 128 (ch A).
//
// TODO: create lib/modules/mod_hx711.h/.cpp  (shared with pneumatic, kitchen_scales)
//       Until then this sketch uses a minimal inline HX711 read.
//
// Stream 1:  raw HX711 count (i32) + tared grams (f32)
// Params:
//   !hx.tare:1                 capture tare zero
//   !hx.scale:0.001            counts-per-gram factor (calibrate with known weight)
//   !hx.gain:128               128 or 64 (ch A) or 32 (ch B)
// ─────────────────────────────────────────────────────────────────────────────

#define HX_DOUT A1
#define HX_SCK  A0

UniProto proto(Serial, "LoadCell");

static int32_t  _tare  = 0;
static float    _scale = 0.001f;   // counts per gram — calibrate!
static int32_t  _last  = 0;

// --- minimal HX711 read (no library) ---
static bool hxReady() {
    return digitalRead(HX_DOUT) == LOW;
}
static int32_t hxRead() {
    uint32_t raw = 0;
    for (int i = 0; i < 24; i++) {
        digitalWrite(HX_SCK, HIGH);
        raw = (raw << 1) | digitalRead(HX_DOUT);
        digitalWrite(HX_SCK, LOW);
    }
    // one extra pulse → gain 128 ch A
    digitalWrite(HX_SCK, HIGH);
    digitalWrite(HX_SCK, LOW);
    // sign extend 24-bit
    if (raw & 0x800000) raw |= 0xFF000000;
    return (int32_t)raw;
}

// ---- emit ----
static void emitLoad(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    if (hxReady()) _last = hxRead();
    const float g = (_last - _tare) * _scale;
    w.begin(sid);
    w.i32(_last, "raw");
    w.f32(g, "g", 2);
    w.end();
}

// ---- params ----
static bool getHx(UniProto&, const char* key, char* out, size_t outLen, void* /*ctx*/) {
    if (!strcmp(key, "hx.scale")) { snprintf(out, outLen, "%.6f", (double)_scale); return true; }
    if (!strcmp(key, "hx.tare"))  { snprintf(out, outLen, "%ld",  (long)_tare);   return true; }
    return false;
}
static bool setHx(UniProto&, const char* key, const char* value, void* /*ctx*/) {
    if (!strcmp(key, "hx.scale")) { _scale = UniProto::parseFloat(value); return true; }
    if (!strcmp(key, "hx.tare"))  {
        if (UniProto::parseInt(value)) _tare = _last; // capture current as zero
        return true;
    }
    return false;
}

void setup() {
    pinMode(HX_DOUT, INPUT);
    pinMode(HX_SCK,  OUTPUT);
    digitalWrite(HX_SCK, LOW);

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(10);
    proto.registerStream({1, "load", "i32,f32", "raw,g", emitLoad, nullptr});
    proto.registerParam({"hx.scale", UniProto::ParamType::FLOAT, getHx, setHx, nullptr});
    proto.registerParam({"hx.tare",  UniProto::ParamType::BOOL,  getHx, setHx, nullptr});
}

void loop() {
    proto.tick();
}
