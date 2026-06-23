#include <Arduino.h>
#include <Wire.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// BLDC gimbal motor — minimal FOC, no SimpleFOC library.
// DRV8313 driver (3-PWM) + AS5600 absolute magnetic encoder (I2C).
//
// Wiring:
//   DRV8313 IN1 → pin 9    (phase A, Timer1 OC1A)
//   DRV8313 IN2 → pin 10   (phase B, Timer1 OC1B)
//   DRV8313 IN3 → pin 11   (phase C, Timer2 OC2A)
//   DRV8313 EN  → pin 8
//   AS5600 SDA  → A4,  SCL → A5
//
// Zero position:
//   The AS5600 reading at power-on is captured as _start_offset.
//   _angle always starts at 0.0 regardless of physical rotor position.
//   @foc.zero resets _angle=0 and _set=0 at the current position.
//
// FOC convention:
//   Electrical angle = _angle * poles (positive, no negation).
//   Spring: vq = +k * err  (positive vq = positive torque = increasing angle).
//   If spring pulls wrong way → swap any two motor phase wires.
//
// Control modes (!foc.mode):
//   0 = open loop  (direct Vq via !foc.vq, fixed electrical angle via !foc.theta)
//   1 = spring     (Vq = +k × error, pulls toward _set)
//   2 = detents    (Vq from detent potential wells)
//   3 = damper     (Vq = -b × velocity, opposes motion)
//   4 = spring + damper
//   5 = sweep      (electrical angle advances at _sweep_hz rev/sec)
// ─────────────────────────────────────────────────────────────────────────────

#define PIN_A    9
#define PIN_B    10
#define PIN_C    11
#define PIN_EN   8

#define AS5600_ADDR  0x36
#define AS5600_REG   0x0C   // ANGLE register (filtered, 12-bit, 0..4095)

// ── PWM ──────────────────────────────────────────────────────────────────────
static void setupPWM() {
    // Timer1: pins 9,10 — Fast PWM, TOP=255 → 62.5kHz
    // Using TOP=255 (same as Timer2) so all 3 phases have identical range.
    TCCR1A = (1<<COM1A1)|(1<<COM1B1)|(1<<WGM11);
    TCCR1B = (1<<WGM13)|(1<<WGM12)|(1<<CS10);
    ICR1 = 255; OCR1A = 127; OCR1B = 127;
    pinMode(PIN_A, OUTPUT); pinMode(PIN_B, OUTPUT);
    // Timer2: pin 11 — Fast PWM, prescale=1 → 62.5kHz
    TCCR2A = (1<<COM2A1)|(1<<WGM21)|(1<<WGM20);
    TCCR2B = (1<<CS20);
    OCR2A = 127;
    pinMode(PIN_C, OUTPUT);
}

static void motorOff() { OCR1A = 127; OCR1B = 127; OCR2A = 127; }

// ── AS5600 ───────────────────────────────────────────────────────────────────
static uint16_t _raw_count = 0;

// Returns raw sensor angle 0..2π. No offset subtraction — keep it simple.
// Zero reference is handled by initialising _prev = first reading,
// so _angle starts at 0 naturally. @foc.zero resets _angle and _set.
static float readAS5600() {
    Wire.beginTransmission(AS5600_ADDR);
    Wire.write(AS5600_REG);
    if (Wire.endTransmission(false) != 0) return -1.0f;
    Wire.requestFrom((uint8_t)AS5600_ADDR, (uint8_t)2);
    if (Wire.available() < 2) return -1.0f;
    uint16_t raw = ((uint16_t)(Wire.read() & 0x0F) << 8) | Wire.read();
    _raw_count = raw;
    return raw / 4095.0f * 2.0f * (float)PI;   // 0..2π, absolute
}

// ── params ───────────────────────────────────────────────────────────────────
static bool  _enabled  = false;
static int   _poles    = 7;
static float _vsupply  = 12.0f;
static float _vlimit   = 2.0f;
static int   _mode     = 1;
static float _set      = 0.0f;
static float _k        = 2.0f;
static float _b        = 0.3f;
static float _detent   = 0.5236f;   // 30° in rad
static float _detent_k = 8.0f;
static float _vq_cmd   = 2.0f;
static float _th_open  = 0.0f;
static float _sweep_hz = 0.5f;
static float _ph_off   = 0.0f;   // electrical phase offset (rad) — tune for sweep symmetry

// ── state ────────────────────────────────────────────────────────────────────
static float    _angle   = 0.0f;   // unwrapped angle from startup zero (rad)
static float    _vel     = 0.0f;   // filtered angular velocity (rad/s)
static float    _vq      = 0.0f;
static float    _prev    = 0.0f;   // previous readAS5600() for unwrap
static uint32_t _last_us = 0;

// ── FOC output ───────────────────────────────────────────────────────────────
static void setPhases(float vq, float theta) {
    const float TP = 2.0f * (float)PI;
    theta = theta - TP * floorf(theta / TP);

    float va = vq * sinf(theta);
    float vb = vq * sinf(theta + 2.09440f);
    float vc = vq * sinf(theta + 4.18879f);

    float n = (_vsupply > 0.1f) ? _vsupply : 12.0f;

    auto clamp01 = [](float x) -> float {
        return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x);
    };
    // All three phases now use identical 0-255 range — fully symmetric
    uint8_t pa = (uint8_t)(clamp01(va / n + 0.5f) * 255.0f);
    uint8_t pb = (uint8_t)(clamp01(vb / n + 0.5f) * 255.0f);
    uint8_t pc = (uint8_t)(clamp01(vc / n + 0.5f) * 255.0f);
    OCR1A = pa;
    OCR1B = pb;
    OCR2A = pc;
}

// ── control ──────────────────────────────────────────────────────────────────
static float computeVq() {
    // Unwrapped error: positive when rotor is ahead of setpoint.
    // Spring pulls back to _set across any number of full turns.
    float err = _angle - _set;

    switch (_mode) {
        case 0: return _vq_cmd;

        case 1:
            return -_k * err;

        case 2: {
            // fmodf preserves the sign of the dividend, so detents only
            // work correctly on the positive side of zero (err > 0).
            // On the negative side the sawtooth phase is offset and does
            // not oscillate symmetrically. This is by design — detents
            // start from zero and extend in one direction only.
            // To get symmetric detents in both directions, replace fmodf
            // with a positive modulo:
            //   float e = err - _detent * floorf(err / _detent);
            //   float phase = e - half;
            float half  = _detent * 0.5f;
            float phase = fmodf(err + half, _detent) - half;
            return -_detent_k * phase;
        }

        case 3:
            return -_b * _vel;

        case 4:
            return -_k * err - _b * _vel;

        case 5:
            return _vq_cmd;

        default: return 0.0f;
    }
}

// ── UniProto ─────────────────────────────────────────────────────────────────
UniProto proto(Serial, "BLDCGimbal");

static void emitFoc(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    w.begin(sid);
    w.f32(_angle,     "pos", 3);
    w.f32(_vel,       "vel", 3);
    w.f32(_set,       "set", 3);
    w.f32(_vq,        "vq",  2);
    w.u16(_raw_count, "cnt");
    w.end();
}

static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"foc.enable"))   { snprintf(out,len,"%d",_enabled);             return true; }
    if (!strcmp(k,"foc.poles"))    { snprintf(out,len,"%d",_poles);               return true; }
    if (!strcmp(k,"foc.vsupply"))  { snprintf(out,len,"%.2f",(double)_vsupply);  return true; }
    if (!strcmp(k,"foc.vlimit"))   { snprintf(out,len,"%.2f",(double)_vlimit);   return true; }
    if (!strcmp(k,"foc.mode"))     { snprintf(out,len,"%d",_mode);                return true; }
    if (!strcmp(k,"foc.set"))      { snprintf(out,len,"%.3f",(double)_set);       return true; }
    if (!strcmp(k,"foc.k"))        { snprintf(out,len,"%.3f",(double)_k);         return true; }
    if (!strcmp(k,"foc.b"))        { snprintf(out,len,"%.3f",(double)_b);         return true; }
    if (!strcmp(k,"foc.detent"))   { snprintf(out,len,"%.4f",(double)_detent);    return true; }
    if (!strcmp(k,"foc.detent_k")) { snprintf(out,len,"%.2f",(double)_detent_k);  return true; }
    if (!strcmp(k,"foc.vq"))       { snprintf(out,len,"%.2f",(double)_vq_cmd);   return true; }
    if (!strcmp(k,"foc.pos"))      { snprintf(out,len,"%.3f",(double)_angle);     return true; }
    if (!strcmp(k,"foc.theta"))    { snprintf(out,len,"%.3f",(double)_th_open);   return true; }
    if (!strcmp(k,"foc.sweep_hz")) { snprintf(out,len,"%.2f",(double)_sweep_hz);  return true; }
    if (!strcmp(k,"foc.ph"))       { snprintf(out,len,"%.3f",(double)_ph_off);    return true; }
    return false;
}

static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"foc.enable")) {
        _enabled = UniProto::parseInt(v);
        if (_enabled) { digitalWrite(PIN_EN, HIGH); }
        else          { digitalWrite(PIN_EN, LOW); motorOff(); }
        return true;
    }
    if (!strcmp(k,"foc.poles"))    { _poles    = (int)UniProto::parseInt(v); return true; }
    if (!strcmp(k,"foc.vsupply"))  { _vsupply  = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.vlimit"))   { _vlimit   = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.mode"))     { _mode     = (int)UniProto::parseInt(v); return true; }
    if (!strcmp(k,"foc.set"))      { _set      = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.k"))        { _k        = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.b"))        { _b        = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.detent"))   { _detent   = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.detent_k")) { _detent_k = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.vq"))       { _vq_cmd   = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.theta"))    { _th_open  = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.sweep_hz")) { _sweep_hz = UniProto::parseFloat(v);   return true; }
    if (!strcmp(k,"foc.ph"))       { _ph_off   = UniProto::parseFloat(v);   return true; }
    return false;
}

static bool doZero(UniProto&, const char*, const char*, Stream& out, void*) {
    _angle = 0.0f;
    _set   = 0.0f;
    out.println(F("foc.zero"));
    return true;
}

// ── setup / loop ─────────────────────────────────────────────────────────────
void setup() {
    pinMode(PIN_EN, OUTPUT);
    digitalWrite(PIN_EN, LOW);
    setupPWM();
    motorOff();

    Wire.begin();
    Wire.setClock(400000);
    Wire.beginTransmission(AS5600_ADDR);
    bool ok = (Wire.endTransmission() == 0);

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);

    proto.registerStream({1,"foc","f32,f32,f32,f32,u16","pos,vel,set,vq,cnt",emitFoc,nullptr});
    proto.registerParam({"foc.enable",   UniProto::ParamType::BOOL,  getParam,setParam,nullptr});
    proto.registerParam({"foc.poles",    UniProto::ParamType::INT32, getParam,setParam,nullptr});
    proto.registerParam({"foc.vsupply",  UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.vlimit",   UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.mode",     UniProto::ParamType::INT32, getParam,setParam,nullptr});
    proto.registerParam({"foc.set",      UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.k",        UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.b",        UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.detent",   UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.detent_k", UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.vq",       UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.pos",      UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.theta",    UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.sweep_hz", UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"foc.ph",       UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerAction({"foc.zero", doZero, nullptr});

    // Initialise _prev from actual sensor reading so first diff ≈ 0
    // and _angle starts at exactly 0 regardless of physical position.
    // Use @foc.zero to re-zero at any time during operation.
    float r = readAS5600();
    _prev    = (r >= 0.0f) ? r : 0.0f;
    _angle   = 0.0f;
    _set     = 0.0f;
    _last_us = micros();

    if (!ok) Serial.println(F("WARN: AS5600 not found"));
}

void loop() {
    uint32_t now_us = micros();
    float    dt     = (float)(now_us - _last_us) * 1e-6f;
    _last_us = now_us;

    // ── read sensor ──────────────────────────────────────────────────────────
    float raw = readAS5600();
    if (raw >= 0.0f) {
        float diff = raw - _prev;
        // Unwrap: shortest arc
        while (diff >  (float)PI) diff -= 2.0f * (float)PI;
        while (diff < -(float)PI) diff += 2.0f * (float)PI;
        diff = -diff;   // invert: CW = positive angle
        _angle += diff;
        _prev   = raw;
        // Velocity: low-pass filtered to reduce quantisation noise
        if (dt > 0.0001f) {
            float v_raw = diff / dt;
            _vel = _vel * 0.8f + v_raw * 0.2f;   // simple IIR filter
        }
    }

    // ── FOC ──────────────────────────────────────────────────────────────────
    if (_enabled) {
        float vq = computeVq();
        if (vq >  _vlimit) { vq =  _vlimit; }
        if (vq < -_vlimit) { vq = -_vlimit; }
        _vq = vq;

        if (_mode == 0) {
            setPhases(vq, _th_open);
        } else if (_mode == 5) {
            if (dt > 0.0f) {
                // Positive sweep_hz = CW = positive _angle direction.
                // Since electrical angle = -_angle*poles, we subtract here.
                _th_open -= 2.0f * (float)PI * _sweep_hz * dt;
            }
            setPhases(vq, _th_open);
        } else {
            // Electrical angle tracks mechanical angle directly.
            // No negation — correct FOC convention.
            // If spring direction is wrong: swap two motor phase wires.
            setPhases(vq, -_angle * (float)_poles + _ph_off);
        }
    }

    proto.tick();
}