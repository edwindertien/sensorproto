#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Pneumatic test bench:
//   - Miniature pump       → digital out pin 6 (HIGH=on)
//   - Solenoid valve       → digital out pin 7 (HIGH=open)
//   - Honeywell bridge-type pressure sensor → mod_adc A0 (differential amp output)
//   - Strain-gauge bridge via HX711         → inline driver (A1=DOUT, A2=SCK)
//
// Stream 1:  pressure voltage A0 (u16 raw / f32 V / f32 kPa via calibration)
// Stream 2:  HX711 strain gauge count (i32) + calibrated force (f32)
//
// Params:
//   !pump:1 / !pump:0          pump on/off
//   !valve:1 / !valve:0        valve open/close
//   !pres.mode:1               switch to volts
//   !pres.cal_slope:X          V-to-kPa slope (calibrate with manometer)
//   !hx.tare:1
//   !hx.scale:X
// ─────────────────────────────────────────────────────────────────────────────

#define PUMP_PIN   6
#define VALVE_PIN  7
#define HX_DOUT   A1
#define HX_SCK    A2

UniProto proto(Serial, "Pneumatic");

// ----- pressure via mod_adc -----
static AdcModule::Config makePresCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 1;
    c.channels[0]  = A0;
    c.vref         = 5.0f;
    c.avgWindow    = 4;
    c.valuesCount  = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "pressure";
    c.values[0].schema = "u16";
    c.values[0].units  = "raw";
    c.values[0].selCount = 0;
    return c;
}
AdcModule presAdc(makePresCfg());

// ----- HX711 inline (strain gauge) -----
static int32_t _hxTare = 0, _hxLast = 0;
static float   _hxScale = 0.001f;

static bool hxReady() { return digitalRead(HX_DOUT) == LOW; }
static int32_t hxRead() {
    uint32_t raw = 0;
    for (int i = 0; i < 24; i++) {
        digitalWrite(HX_SCK, HIGH);
        raw = (raw << 1) | digitalRead(HX_DOUT);
        digitalWrite(HX_SCK, LOW);
    }
    digitalWrite(HX_SCK, HIGH); digitalWrite(HX_SCK, LOW);
    if (raw & 0x800000) raw |= 0xFF000000;
    return (int32_t)raw;
}
static void emitHx(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    if (hxReady()) _hxLast = hxRead();
    float force = (_hxLast - _hxTare) * _hxScale;
    w.begin(sid);
    w.i32(_hxLast, "raw");
    w.f32(force, "N", 3);
    w.end();
}

// ----- actuator params -----
static bool _pump = false, _valve = false;
static bool getAct(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "pump"))  { snprintf(out, outLen, "%d", _pump);  return true; }
    if (!strcmp(key, "valve")) { snprintf(out, outLen, "%d", _valve); return true; }
    if (!strcmp(key, "hx.tare"))  { snprintf(out, outLen, "%ld", (long)_hxTare); return true; }
    if (!strcmp(key, "hx.scale")) { snprintf(out, outLen, "%.6f", (double)_hxScale); return true; }
    return false;
}
static bool setAct(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "pump"))  { _pump  = UniProto::parseInt(value); digitalWrite(PUMP_PIN, _pump); return true; }
    if (!strcmp(key, "valve")) { _valve = UniProto::parseInt(value); digitalWrite(VALVE_PIN, _valve); return true; }
    if (!strcmp(key, "hx.tare")  && UniProto::parseInt(value)) { _hxTare  = _hxLast; return true; }
    if (!strcmp(key, "hx.scale")) { _hxScale = UniProto::parseFloat(value); return true; }
    return false;
}

void setup() {
    pinMode(PUMP_PIN, OUTPUT);  digitalWrite(PUMP_PIN, LOW);
    pinMode(VALVE_PIN, OUTPUT); digitalWrite(VALVE_PIN, LOW);
    pinMode(HX_DOUT, INPUT);
    pinMode(HX_SCK, OUTPUT);    digitalWrite(HX_SCK, LOW);

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(20);

    presAdc.registerWith(proto);
    proto.registerStream({2, "strain", "i32,f32", "raw,N", emitHx, nullptr});

    proto.registerParam({"pump",      UniProto::ParamType::BOOL,  getAct, setAct, nullptr});
    proto.registerParam({"valve",     UniProto::ParamType::BOOL,  getAct, setAct, nullptr});
    proto.registerParam({"hx.tare",   UniProto::ParamType::BOOL,  getAct, setAct, nullptr});
    proto.registerParam({"hx.scale",  UniProto::ParamType::FLOAT, getAct, setAct, nullptr});
}

void loop() {
    proto.tick();
}
