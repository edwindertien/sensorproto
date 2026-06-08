#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Synchro transformer: three-phase PWM excitation (5 kHz carrier, 100 Hz
// envelope), filtered sine output read on A0..A2 (S1, S2, S3 stator).
//
// Angle is decoded by the Scott-T equations:
//   θ = atan2(√3 * S2, 2*S1 - S2)   (one common variant)
//
// PWM excitation (R1): pin 9 at ~490 Hz (Timer1 default).
// For a proper 5 kHz carrier use Timer1 reconfigured — see platformio.ini note.
// The RC filter on the output reduces the carrier; what remains is the 100 Hz
// envelope which encodes the rotor angle.
//
// Stream 1: S1, S2, S3 raw ADC
// Stream 2: decoded angle (f32 degrees, 0..360)
// ─────────────────────────────────────────────────────────────────────────────

#include <math.h>

#define EXCITATION_PIN 9
UniProto proto(Serial, "Synchro");

// ADC: S1=A0, S2=A1, S3=A2 (stator outputs, rectified/filtered)
static AdcModule::Config makeAdcCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 3;
    c.channels[0] = A0; // S1
    c.channels[1] = A1; // S2
    c.channels[2] = A2; // S3
    c.avgWindow   = 4;
    c.vref        = 5.0f;
    c.valuesCount = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "syn.raw";
    c.values[0].schema = "u16,u16,u16";
    c.values[0].units  = "S1,S2,S3";
    c.values[0].selCount = 0;
    return c;
}
AdcModule rawAdc(makeAdcCfg());

static float _angle = 0.0f;
static float _offset = 0.0f; // electrical zero offset (degrees)

static void emitAngle(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    // Scott-T decode — centred around Vcc/2 (2.5 V ≈ 511 raw)
    float s1 = (float)analogRead(A0) - 511.5f;
    float s2 = (float)analogRead(A1) - 511.5f;
    // 2-stator approximation (S3 redundant for atan2)
    float theta = atan2f(1.732050808f * s2, 2.0f * s1 - s2);
    _angle = fmodf((theta * 57.2957795f) - _offset + 720.0f, 360.0f);
    w.begin(sid);
    w.f32(_angle, "deg", 2);
    w.end();
}

static bool getSyn(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "syn.offset")) { snprintf(out, outLen, "%.2f", (double)_offset); return true; }
    return false;
}
static bool setSyn(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "syn.offset")) { _offset = UniProto::parseFloat(value); return true; }
    return false;
}
static bool doZero(UniProto&, const char*, const char*, Stream& out, void*) {
    _offset = _angle; out.println(F("syn.zero")); return true;
}

void setup() {
    analogWrite(EXCITATION_PIN, 127); // 50% duty excitation

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);

    rawAdc.registerWith(proto);
    proto.registerStream({2, "syn.angle", "f32", "deg", emitAngle, nullptr});
    proto.registerParam({"syn.offset", UniProto::ParamType::FLOAT, getSyn, setSyn, nullptr});
    proto.registerAction({"syn.zero", doZero, nullptr});
}

void loop() {
    proto.tick();
}
