#include <Arduino.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Kitchen scales — load cell + HX711.
// Same wiring as load_cell (DOUT=A1, SCK=A0) but calibrated for cooking range
// (~0..5000 g).  Tare on startup.
//
// NOTE: shares inline HX711 driver with src_load_cell/.
// Both will be migrated to mod_hx711 once that module is written.
//
// Useful commands:
//   @hx.tare:1                 or  !hx.tare:1
//   !hx.scale:0.00045          counts-per-gram (calibrate with 200 g weight)
//   !stream:1
//   !rate:5                    5 Hz is enough for kitchen use
// ─────────────────────────────────────────────────────────────────────────────

#define HX_DOUT A1
#define HX_SCK  A0

UniProto proto(Serial, "KitchenScales");

static int32_t  _tare  = 0;
static float    _scale = 0.00045f;
static int32_t  _last  = 0;

static bool hxReady() { return digitalRead(HX_DOUT) == LOW; }
static int32_t hxRead() {
    uint32_t raw = 0;
    for (int i = 0; i < 24; i++) {
        digitalWrite(HX_SCK, HIGH);
        raw = (raw << 1) | digitalRead(HX_DOUT);
        digitalWrite(HX_SCK, LOW);
    }
    digitalWrite(HX_SCK, HIGH); digitalWrite(HX_SCK, LOW); // gain 128
    if (raw & 0x800000) raw |= 0xFF000000;
    return (int32_t)raw;
}

static void emitScale(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    if (hxReady()) _last = hxRead();
    float g = (_last - _tare) * _scale;
    w.begin(sid);
    w.f32(g, "g", 1);
    w.end();
}

static bool getHx(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "hx.scale")) { snprintf(out, outLen, "%.6f", (double)_scale); return true; }
    if (!strcmp(key, "hx.tare"))  { snprintf(out, outLen, "%ld", (long)_tare); return true; }
    return false;
}
static bool setHx(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "hx.scale")) { _scale = UniProto::parseFloat(value); return true; }
    if (!strcmp(key, "hx.tare") && UniProto::parseInt(value)) { _tare = _last; return true; }
    return false;
}
static bool doTare(UniProto&, const char*, const char*, Stream& out, void*) {
    _tare = _last; out.println(F("tare done")); return true;
}

void setup() {
    pinMode(HX_DOUT, INPUT);
    pinMode(HX_SCK, OUTPUT);
    digitalWrite(HX_SCK, LOW);
    // warm up: read a few times
    for (int i = 0; i < 10; i++) { delay(100); if (hxReady()) _last = hxRead(); }
    _tare = _last; // auto-tare on boot

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(5);
    proto.registerStream({1, "scale", "f32", "g", emitScale, nullptr});
    proto.registerParam({"hx.scale", UniProto::ParamType::FLOAT, getHx, setHx, nullptr});
    proto.registerParam({"hx.tare",  UniProto::ParamType::BOOL,  getHx, setHx, nullptr});
    proto.registerAction({"hx.tare", doTare, nullptr});
}

void loop() {
    proto.tick();
}
