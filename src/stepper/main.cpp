#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Stepper with MKS SERVO42D closed-loop controller.
// Interface: standard STEP/DIR + ENABLE.
//   STEP=3, DIR=4, EN=5  (active-low enable on most MKS boards)
//
// The SERVO42D handles closed-loop internally via its own encoder.
// We just send pulses and optionally read an analog fault/status output.
//
// Stream 1: commanded position (steps, i32), direction, step rate
// ADC stream 2: optional status/analog readback on A0
//
// Params:
//   !step.pos:1000             move to absolute step position (generates pulses)
//   !step.rate:500             steps per second for moves
//   !step.en:1 / !step.en:0   enable/disable driver
// ─────────────────────────────────────────────────────────────────────────────

#define STEP_PIN  3
#define DIR_PIN   4
#define EN_PIN    5

UniProto proto(Serial, "Stepper");

static int32_t  _pos      = 0;   // current commanded position (steps)
static int32_t  _target   = 0;   // target position
static uint16_t _rateHz   = 500; // steps/sec
static bool     _en       = false;
static bool     _moving   = false;
static uint32_t _lastStep = 0;

// optional status ADC
static AdcModule::Config makeAdcCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 1;
    c.channels[0]  = A0;
    c.valuesCount  = 1;
    c.values[0].id     = 2;
    c.values[0].name   = "step.status";
    c.values[0].schema = "u16";
    c.values[0].units  = "raw";
    c.values[0].selCount = 0;
    return c;
}
AdcModule statusAdc(makeAdcCfg());

// ---- emit stream 1 ----
static void emitStep(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    w.begin(sid);
    w.i32(_pos,    "pos");
    w.i32(_target, "target");
    w.u16(_rateHz, "rate");
    w.u16(_en ? 1 : 0, "en");
    w.end();
}

// ---- params ----
static bool getStep(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "step.pos"))    { snprintf(out, outLen, "%ld", (long)_pos);    return true; }
    if (!strcmp(key, "step.target")) { snprintf(out, outLen, "%ld", (long)_target); return true; }
    if (!strcmp(key, "step.rate"))   { snprintf(out, outLen, "%u",  (unsigned)_rateHz); return true; }
    if (!strcmp(key, "step.en"))     { snprintf(out, outLen, "%d",  _en);           return true; }
    return false;
}
static bool setStep(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "step.target")) { _target = (int32_t)UniProto::parseInt(value); _moving = true; return true; }
    if (!strcmp(key, "step.rate")) {
        long v = UniProto::parseInt(value);
        if (v < 1) v = 1; if (v > 5000) v = 5000;
        _rateHz = (uint16_t)v; return true;
    }
    if (!strcmp(key, "step.en")) {
        _en = UniProto::parseInt(value);
        digitalWrite(EN_PIN, _en ? LOW : HIGH); // active-low
        return true;
    }
    return false;
}
static bool doHome(UniProto&, const char*, const char*, Stream& out, void*) {
    _pos = 0; _target = 0; _moving = false;
    out.println(F("step.zero")); return true;
}

void setup() {
    pinMode(STEP_PIN, OUTPUT); digitalWrite(STEP_PIN, LOW);
    pinMode(DIR_PIN,  OUTPUT); digitalWrite(DIR_PIN,  LOW);
    pinMode(EN_PIN,   OUTPUT); digitalWrite(EN_PIN,   HIGH); // disabled

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(20);

    proto.registerStream({1, "stepper", "i32,i32,u16,u16", "pos,target,rate,en", emitStep, nullptr});
    statusAdc.registerWith(proto);

    proto.registerParam({"step.target", UniProto::ParamType::INT32, getStep, setStep, nullptr});
    proto.registerParam({"step.rate",   UniProto::ParamType::INT32, getStep, setStep, nullptr});
    proto.registerParam({"step.en",     UniProto::ParamType::BOOL,  getStep, setStep, nullptr});
    proto.registerParam({"step.pos",    UniProto::ParamType::INT32, getStep, setStep, nullptr});
    proto.registerAction({"step.zero", doHome, nullptr});
}

void loop() {
    // non-blocking step generation
    if (_moving && _en) {
        const int32_t err = _target - _pos;
        if (err == 0) {
            _moving = false;
        } else {
            uint32_t now = micros();
            uint32_t period = 1000000UL / _rateHz;
            if ((uint32_t)(now - _lastStep) >= period) {
                _lastStep = now;
                digitalWrite(DIR_PIN, err > 0 ? HIGH : LOW);
                digitalWrite(STEP_PIN, HIGH);
                delayMicroseconds(2);
                digitalWrite(STEP_PIN, LOW);
                _pos += (err > 0) ? 1 : -1;
            }
        }
    }
    proto.tick();
}
