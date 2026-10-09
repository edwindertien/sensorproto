#include <Arduino.h>
#include "UniProto.h"

// ── DC Motor — Arduino Motor Shield Channel B ─────────────────────────────────
// Single 12V DC motor, 1:30 gearbox, US-Digital 100PPR quadrature encoder.
//
// Motor Shield Channel B:
//   PWM  → pin 11  (Timer2, ultrasonic ~31kHz)
//   DIR  → pin 13
//   BRAKE→ pin 8   (HIGH=brake, LOW=coast)
//
// Encoder (rear shaft, before gearbox):
//   A    → pin 2   (INT0, quadrature)
//   B    → pin 3   (INT1, quadrature)
//   100 PPR × 4 (quadrature) × 30 (gearbox) = 12000 counts/output rev
//
// Potentiometer setpoint (A3=GND, A4=signal, A5=VCC):
//   Provides reference setpoint for position/velocity/PWM modes.
//   A0=Ch.A current sense, A1=Ch.B current sense — used by motor shield,
//   do not connect anything else to A0/A1.
//
// Control modes (!mot.mode):
//   0 = direct PWM   (pot maps ±pwm_lim directly)
//   1 = position PID (pot maps to position setpoint in ticks)
//   2 = velocity PID (pot maps to velocity setpoint in counts/s)
//
// Stream 1 "mot": pos(i32), set(f32), cmd(i32), err(f32), vel(f32), mA(f32)
//   mA = Channel B motor current (A1 sense pin, 2.96mA per ADC count)
//
// Key commands:
//   !mot.mode:1         position control
//   !mot.enable:1       engage controller
//   !mot.kp:2.0         P gain
//   !mot.ki:0.1         I gain
//   !mot.kd:0.05        D gain
//   !mot.pwm_lim:200    max PWM (0-255)
//   !mot.set:6000       set target (ticks — 6000 = 0.5 output rev)
//   !mot.pot_scale:12000 pot range in ticks (position mode)
//   @mot.zero           zero encoder
//   @mot.brake          engage brake
//   @mot.coast          release brake
// ─────────────────────────────────────────────────────────────────────────────

// ── Pins ──────────────────────────────────────────────────────────────────────
#define PIN_PWM   11
#define PIN_DIR   13
#define PIN_BRAKE  8
#define PIN_ENC_A  2
#define PIN_ENC_B  3
#define PIN_POT_GND A3
#define PIN_POT_SIG A4
#define PIN_POT_VCC A5

// ── Encoder ───────────────────────────────────────────────────────────────────
volatile int32_t _enc = 0;

void encISR_A() {
    if (digitalRead(PIN_ENC_A) == digitalRead(PIN_ENC_B)) _enc--; else _enc++;
}
void encISR_B() {
    if (digitalRead(PIN_ENC_A) == digitalRead(PIN_ENC_B)) _enc++; else _enc--;
}

// ── PWM ───────────────────────────────────────────────────────────────────────
// Timer2 fast PWM on pin 11 at ~31kHz (inaudible)
static void setupPWM() {
    TCCR2A = (1<<COM2A1)|(1<<WGM21)|(1<<WGM20);
    TCCR2B = (1<<CS20);   // prescale 1 → 62.5kHz / 2 ≈ 31kHz
    OCR2A  = 0;
    pinMode(PIN_PWM, OUTPUT);
}

static void driveMotor(int16_t cmd) {
    // cmd: -255..+255
    if (cmd >= 0) {
        digitalWrite(PIN_DIR, HIGH);
        OCR2A = (uint8_t)min(cmd, 255);
    } else {
        digitalWrite(PIN_DIR, LOW);
        OCR2A = (uint8_t)min(-cmd, 255);
    }
}

// ── Current sense ─────────────────────────────────────────────────────────────
// Motor Shield: A0=Ch.A current, A1=Ch.B current (our motor is Ch.B)
// 3.3V at pin = 2A → each count = 2.96mA
#define PIN_CS_A  A0
#define PIN_CS_B  A1
static float _current_ma = 0.0f;   // Ch.B motor current in mA

// ── State ─────────────────────────────────────────────────────────────────────
static bool    _enabled   = true;    // start enabled — pot controls position
static uint8_t _mode      = 1;       // 0=PWM, 1=pos PID, 2=vel PID
static float   _kp        = 2.0f;   // P-only to start, safer
static float   _ki        = 0.0f;
static float   _kd        = 0.0f;
static int16_t _pwm_lim   = 100;    // conservative start — increase once working
static float   _set       = 0.0f;
static float   _pot_scale = 12000.0f;
static float   _vel_scale = 20000.0f;

static float    _integral  = 0.0f;
static float    _prev_err  = 0.0f;
static float    _vel       = 0.0f;
static int16_t  _cmd       = 0;
static uint32_t _prev_us   = 0;
static uint16_t _ctrl_hz   = 500;    // control loop rate Hz (default 500)
static uint32_t _ctrl_next = 0;

// ── PID ───────────────────────────────────────────────────────────────────────
static uint32_t _vel_last_us  = 0;
static int32_t  _vel_last_enc = 0;
static float    _vel_alpha    = 0.5f;  // IIR filter: 0=max smooth, 1=raw (off)
#define VEL_WINDOW_US 20000   // compute velocity over 20ms windows

static void updateControl() {
    uint32_t now_us = micros();
    float    dt     = (float)(now_us - _prev_us) * 1e-6f;
    _prev_us = now_us;
    if (dt < 1e-5f || dt > 0.5f) return;

    int32_t pos = _enc;

    // current sense (Ch.B = our motor)
    _current_ma = analogRead(PIN_CS_B) * 2.96f;

    // velocity: only update over minimum window (avoids single-tick noise)
    uint32_t vel_dt_us = now_us - _vel_last_us;
    if (vel_dt_us >= VEL_WINDOW_US) {
        float vel_dt = (float)vel_dt_us * 1e-6f;
        float raw_vel = (float)(pos - _vel_last_enc) / vel_dt;
        _vel = _vel * (1.0f - _vel_alpha) + raw_vel * _vel_alpha;
        _vel_last_us  = now_us;
        _vel_last_enc = pos;
    }

    if (!_enabled) return;

    float err = 0.0f;
    if (_mode == 0) {
        // Direct PWM — pot already mapped to _set in pollPot()
        _cmd = (int16_t)constrain(_set, -_pwm_lim, _pwm_lim);
        driveMotor(_cmd);
        return;
    } else if (_mode == 1) {
        err = _set - (float)pos;
    } else if (_mode == 2) {
        err = _set - _vel;
    }

    _integral += err * dt;
    // Anti-windup: clamp integral
    float max_i = _pwm_lim / max(0.001f, _ki);
    _integral = constrain(_integral, -max_i, max_i);

    float deriv = (err - _prev_err) / dt;
    _prev_err = err;

    float out = _kp * err + _ki * _integral + _kd * deriv;
    _cmd = (int16_t)constrain(out, -_pwm_lim, _pwm_lim);
    driveMotor(_cmd);
}

// ── Potentiometer ─────────────────────────────────────────────────────────────
static void pollPot() {
    int raw = analogRead(PIN_POT_SIG);   // 0-1023
    float norm = (raw / 1023.0f) * 2.0f - 1.0f;  // -1..+1
    if (_mode == 0)      _set = norm * _pwm_lim;
    else if (_mode == 1) _set = norm * _pot_scale;
    else if (_mode == 2) _set = norm * _vel_scale;
}

// ── UniProto ──────────────────────────────────────────────────────────────────
UniProto proto(Serial, "DCMotor");

static void emitMot(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    float err = (_mode == 1) ? (_set - (float)_enc)
              : (_mode == 2) ? (_set - _vel)
              : 0.0f;
    w.begin(sid);
    w.i32(_enc,  "pos");
    w.f32(_set,  "set",  1);
    w.i32(_cmd,  "cmd");
    w.f32(err,   "err",  1);
    w.f32(_vel,  "vel",  1);
    w.f32(_current_ma, "mA", 0);
    w.end();
}

static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"mot.enable"))    { snprintf(out,len,"%d",_enabled);           return true; }
    if (!strcmp(k,"mot.mode"))      { snprintf(out,len,"%u",_mode);              return true; }
    if (!strcmp(k,"mot.kp"))        { snprintf(out,len,"%.3f",(double)_kp);      return true; }
    if (!strcmp(k,"mot.ki"))        { snprintf(out,len,"%.3f",(double)_ki);      return true; }
    if (!strcmp(k,"mot.kd"))        { snprintf(out,len,"%.3f",(double)_kd);      return true; }
    if (!strcmp(k,"mot.pwm_lim"))   { snprintf(out,len,"%d",_pwm_lim);           return true; }
    if (!strcmp(k,"mot.set"))       { snprintf(out,len,"%.1f",(double)_set);     return true; }
    if (!strcmp(k,"mot.pot_scale")) { snprintf(out,len,"%.0f",(double)_pot_scale);return true;}
    if (!strcmp(k,"mot.vel_scale")) { snprintf(out,len,"%.0f",(double)_vel_scale);return true;}
    if (!strcmp(k,"mot.vel_alpha")) { snprintf(out,len,"%.2f",(double)_vel_alpha);return true;}
    if (!strcmp(k,"mot.pos"))       { snprintf(out,len,"%ld",(long)_enc);        return true; }
    if (!strcmp(k,"mot.vel"))       { snprintf(out,len,"%.1f",(double)_vel);     return true; }
    if (!strcmp(k,"mot.ctrl_hz"))   { snprintf(out,len,"%u",_ctrl_hz);           return true; }
    return false;
}

static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"mot.enable")) {
        _enabled = UniProto::parseInt(v);
        if (!_enabled) { driveMotor(0); _integral = 0; }
        return true;
    }
    if (!strcmp(k,"mot.mode")) {
        _mode = (uint8_t)UniProto::parseInt(v);
        _integral = 0; _prev_err = 0;
        return true;
    }
    if (!strcmp(k,"mot.kp"))        { _kp        = UniProto::parseFloat(v); return true; }
    if (!strcmp(k,"mot.ki"))        { _ki        = UniProto::parseFloat(v); _integral=0; return true; }
    if (!strcmp(k,"mot.kd"))        { _kd        = UniProto::parseFloat(v); return true; }
    if (!strcmp(k,"mot.pwm_lim"))   { _pwm_lim   = (int16_t)UniProto::parseInt(v); return true; }
    if (!strcmp(k,"mot.set"))       { _set       = UniProto::parseFloat(v); return true; }
    if (!strcmp(k,"mot.pot_scale")) { _pot_scale = UniProto::parseFloat(v); return true; }
    if (!strcmp(k,"mot.vel_scale")) { _vel_scale = UniProto::parseFloat(v); return true; }
    if (!strcmp(k,"mot.ctrl_hz"))   { _ctrl_hz = (uint16_t)constrain(UniProto::parseInt(v),1,5000); _ctrl_next=0; return true; }
    if (!strcmp(k,"mot.vel_alpha")) { _vel_alpha = UniProto::parseFloat(v); return true; }
    return false;
}

static bool doZero(UniProto&, const char*, const char*, Stream& out, void*) {
    noInterrupts(); _enc = 0; interrupts();
    _set = 0; _integral = 0; _prev_err = 0;
    _vel_last_enc = 0; _vel_last_us = micros();
    out.println(F("mot.zero"));
    return true;
}
static bool doBrake(UniProto&, const char*, const char*, Stream& out, void*) {
    digitalWrite(PIN_BRAKE, HIGH);
    out.println(F("mot.brake"));
    return true;
}
static bool doCoast(UniProto&, const char*, const char*, Stream& out, void*) {
    digitalWrite(PIN_BRAKE, LOW);
    out.println(F("mot.coast"));
    return true;
}

// ── Setup / loop ──────────────────────────────────────────────────────────────
void setup() {
    // Motor shield pins
    pinMode(PIN_DIR,   OUTPUT); digitalWrite(PIN_DIR, LOW);
    pinMode(PIN_BRAKE, OUTPUT); digitalWrite(PIN_BRAKE, LOW);  // coast
    setupPWM();

    // Pot reference pins
    pinMode(PIN_POT_GND, OUTPUT); digitalWrite(PIN_POT_GND, LOW);
    pinMode(PIN_POT_VCC, OUTPUT); digitalWrite(PIN_POT_VCC, HIGH);
    pinMode(PIN_POT_SIG, INPUT);

    // Encoder
    pinMode(PIN_ENC_A, INPUT_PULLUP);
    pinMode(PIN_ENC_B, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encISR_A, CHANGE);
    attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), encISR_B, CHANGE);

    _prev_us      = micros();
    _ctrl_next    = _prev_us;
    _vel_last_us  = _prev_us;
    _vel_last_enc = 0;

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);

    proto.registerStream({1,"mot","i32,f32,i32,f32,f32,f32","pos,set,cmd,err,vel,mA",emitMot,nullptr});

    proto.registerParam({"mot.enable",    UniProto::ParamType::BOOL,  getParam,setParam,nullptr});
    proto.registerParam({"mot.mode",      UniProto::ParamType::INT32, getParam,setParam,nullptr});
    proto.registerParam({"mot.kp",        UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.ki",        UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.kd",        UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.pwm_lim",   UniProto::ParamType::INT32, getParam,setParam,nullptr});
    proto.registerParam({"mot.set",       UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.pot_scale", UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.vel_scale", UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.ctrl_hz",   UniProto::ParamType::INT32, getParam,setParam,nullptr});
    proto.registerParam({"mot.vel_alpha", UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.pos",       UniProto::ParamType::INT32, getParam,setParam,nullptr});
    proto.registerParam({"mot.vel",       UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"mot.mA",        UniProto::ParamType::FLOAT, getParam,setParam,nullptr});

    proto.registerAction({"mot.zero",  doZero,  nullptr});
    proto.registerAction({"mot.brake", doBrake, nullptr});
    proto.registerAction({"mot.coast", doCoast, nullptr});
}

static uint32_t _pot_next  = 0;

void loop() {
    uint32_t now = micros();

    // Control loop gated by _ctrl_hz
    if (now >= _ctrl_next) {
        _ctrl_next = now + (uint32_t)(1000000UL / _ctrl_hz);
        updateControl();
    }

    // Poll pot at 20Hz
    uint32_t now_ms = millis();
    if (now_ms >= _pot_next) {
        _pot_next = now_ms + 50;
        pollPot();
    }

    proto.tick();
}