#include <Arduino.h>
#include "UniProto.h"

// ── HC-SR04 Ultrasonic Distance Sensor ───────────────────────────────────────
// Trigger: pin 3 (10µs pulse output)
// Echo:    pin 2 (measures return pulse duration via INT0)
//
// Each measurement cycle:
//   1. Send 10µs trigger pulse on pin 3
//   2. Echo pin goes HIGH (start) then LOW (end) — duration = distance
//   3. Distance = echo_us / 58.0 cm  (speed of sound ÷ 2)
//
// Streams:
//   1 "pulse": trig_us(u32), echo_start_us(u32), echo_us(u32), dist_cm(f32)
//              All timestamps relative to session start (micros()).
//              echo_us=0 means timeout (no object / >4m).
//   2 "dist":  dist_cm(f32) only — for simple distance logging
//
// Stream 1 gives everything needed to reconstruct oscilloscope view in Python:
//   - Trigger: pulse from trig_us to trig_us+10
//   - Echo:    pulse from echo_start_us to echo_start_us+echo_us
//   - Gap between trigger end and echo start = acoustic travel time
//
// Commands:
//   !us.rate:10        measurement rate Hz (default 10, max ~20)
//   !us.timeout:30000  echo timeout µs (default 30000 = ~5m)
// ─────────────────────────────────────────────────────────────────────────────

#define PIN_TRIG  3
#define PIN_ECHO  2

UniProto proto(Serial, "HCSR04");

static uint16_t _rate_hz  = 10;
static uint32_t _timeout  = 30000;   // µs

// Captured by ISR
static volatile uint32_t _echo_start = 0;
static volatile uint32_t _echo_end   = 0;
static volatile bool     _echo_done  = false;
static volatile bool     _echo_busy  = false;

static uint32_t _trig_us   = 0;
static uint32_t _echo_dur  = 0;
static float    _dist_cm   = 0.0f;
static uint32_t _t_session = 0;   // micros() at start, for relative timestamps

void echoISR() {
    if (digitalRead(PIN_ECHO) == HIGH) {
        _echo_start = micros();
        _echo_busy  = true;
    } else {
        if (_echo_busy) {
            _echo_end  = micros();
            _echo_done = true;
            _echo_busy = false;
        }
    }
}

static void measure() {
    // Reset echo capture
    _echo_done = false;
    _echo_busy = false;
    _echo_dur  = 0;

    // Send 10µs trigger
    digitalWrite(PIN_TRIG, LOW);
    delayMicroseconds(2);
    _trig_us = micros() - _t_session;
    digitalWrite(PIN_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(PIN_TRIG, LOW);

    // Wait for echo (ISR captures it)
    uint32_t t_wait = micros();
    while (!_echo_done && (micros() - t_wait) < _timeout) {
        // spin — echo ISR will set _echo_done
    }

    if (_echo_done) {
        _echo_dur = _echo_end - _echo_start;
        _dist_cm  = _echo_dur / 58.0f;
    } else {
        // Timeout — no echo
        _echo_dur = 0;
        _dist_cm  = -1.0f;   // sentinel for "no object"
    }
}

static void emitPulse(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    uint32_t echo_rel = _echo_done ? (_echo_start - _t_session) : 0;
    w.begin(sid);
    w.i32(_trig_us,  "trig_us");    // trigger leading edge (µs from session start)
    w.i32(echo_rel,  "echo_us");    // echo leading edge (µs from session start)
    w.i32(_echo_dur, "echo_dur");   // echo duration (µs), 0=timeout
    w.f32(_dist_cm,  "cm", 1);
    w.end();
}

static void emitDist(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    w.begin(sid);
    w.f32(_dist_cm, "cm", 1);
    w.end();
}

static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"us.rate"))    { snprintf(out,len,"%u",_rate_hz);  return true; }
    if (!strcmp(k,"us.timeout")) { snprintf(out,len,"%lu",(unsigned long)_timeout); return true; }
    return false;
}
static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"us.rate"))    { _rate_hz = (uint16_t)constrain(UniProto::parseInt(v),1,20); return true; }
    if (!strcmp(k,"us.timeout")) { _timeout = (uint32_t)UniProto::parseInt(v); return true; }
    return false;
}

void setup() {
    pinMode(PIN_TRIG, OUTPUT);
    digitalWrite(PIN_TRIG, LOW);
    pinMode(PIN_ECHO, INPUT);
    attachInterrupt(digitalPinToInterrupt(PIN_ECHO), echoISR, CHANGE);

    _t_session = micros();

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(_rate_hz);

    proto.registerStream({1,"pulse","i32,i32,i32,f32","trig_us,echo_us,echo_dur,cm",emitPulse,nullptr});
    proto.registerStream({2,"dist", "f32",            "cm",                          emitDist, nullptr});

    proto.registerParam({"us.rate",    UniProto::ParamType::INT32, getParam,setParam,nullptr});
    proto.registerParam({"us.timeout", UniProto::ParamType::INT32, getParam,setParam,nullptr});
}

static uint32_t _next_ms = 0;

void loop() {
    uint32_t now = millis();
    uint32_t period = 1000 / _rate_hz;
    if (now >= _next_ms) {
        _next_ms = now + period;
        measure();
    }
    proto.tick();
}