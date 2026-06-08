#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// LVDT using PWM AC excitation (100 Hz) and filtered AC input.
// PWM excitation output on pin 9 (Timer1 ~500 Hz default, or reconfigured).
// Rectified/filtered sense voltage read on A0 (primary ref) and A1 (sense).
//
// The LVDT output is a ratio: Vsense / Vref.  At null position, ratio ≈ 0.5.
// Displacement ∝ (ratio - 0.5).
//
// PWM note: actual excitation uses a low-pass RC filter on pin 9.
//           Timer1 default on Uno ~490 Hz is acceptable for 100 Hz target.
//           For better accuracy, use mod_adc block stream + FFT approach.
//
// Stream 1: Vref (A0), Vsense (A1), ratio (f32), position_mm (f32, needs cal)
// Params:
//   !lvdt.cal_span:10.0        full-scale mm (half-stroke each side)
//   !lvdt.pwm:127              excitation PWM duty (0..255)
// ─────────────────────────────────────────────────────────────────────────────

#define EXCITATION_PIN 9

UniProto proto(Serial, "LVDT");

static float _calSpan = 10.0f;   // ±10 mm full stroke
static uint8_t _pwmDuty = 127;

static AdcModule::Config makeAdcCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 2;
    c.channels[0]  = A0; // Vref (excitation after filter)
    c.channels[1]  = A1; // Vsense (LVDT output after filter)
    c.avgWindow    = 8;
    c.vref         = 5.0f;
    c.valuesCount  = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "lvdt.raw";
    c.values[0].schema = "u16,u16";
    c.values[0].units  = "ref,sense";
    c.values[0].selCount = 0;
    return c;
}
AdcModule rawAdc(makeAdcCfg());

// computed stream
static float _ratio = 0.5f, _posMm = 0.0f;
static uint16_t _vref_raw = 512, _vsense_raw = 512;

static void emitLvdt(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    _vref_raw   = (uint16_t)analogRead(A0);
    _vsense_raw = (uint16_t)analogRead(A1);
    float vref   = (_vref_raw   / 1023.0f) * 5.0f;
    float vsense = (_vsense_raw / 1023.0f) * 5.0f;
    _ratio = (vref > 0.01f) ? (vsense / vref) : 0.5f;
    _posMm = (_ratio - 0.5f) * 2.0f * _calSpan;
    w.begin(sid);
    w.u16(_vref_raw,   "vref");
    w.u16(_vsense_raw, "vsense");
    w.f32(_ratio,  "ratio", 4);
    w.f32(_posMm,  "mm",    2);
    w.end();
}

static bool getLvdt(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "lvdt.cal_span")) { snprintf(out, outLen, "%.2f", (double)_calSpan); return true; }
    if (!strcmp(key, "lvdt.pwm"))      { snprintf(out, outLen, "%u", (unsigned)_pwmDuty);  return true; }
    return false;
}
static bool setLvdt(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "lvdt.cal_span")) { _calSpan = UniProto::parseFloat(value); return true; }
    if (!strcmp(key, "lvdt.pwm")) {
        long v = UniProto::parseInt(value);
        if (v < 0) v = 0; if (v > 255) v = 255;
        _pwmDuty = (uint8_t)v;
        analogWrite(EXCITATION_PIN, _pwmDuty);
        return true;
    }
    return false;
}

void setup() {
    analogWrite(EXCITATION_PIN, _pwmDuty);

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);

    proto.registerStream({2, "lvdt", "u16,u16,f32,f32", "vref,vsense,ratio,mm", emitLvdt, nullptr});

    proto.registerParam({"lvdt.cal_span", UniProto::ParamType::FLOAT, getLvdt, setLvdt, nullptr});
    proto.registerParam({"lvdt.pwm",      UniProto::ParamType::INT32, getLvdt, setLvdt, nullptr});
}

void loop() {
    proto.tick();
}
