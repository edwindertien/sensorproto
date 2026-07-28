#include <Arduino.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Anemometer using IR LED + photodiode across a rotating fan (respirometer).
// Photodiode in forward-voltage mode: junction voltage read on A1.
//
// Pin roles (matching original sketch):
//   A3 → HIGH  (LED anode supply)
//   A2 → OUTPUT LOW (LED cathode — drives current through LED)
//   A0 → OUTPUT LOW (photodiode GND side — current sink)
//   A1 → INPUT (photodiode signal — reads forward junction voltage)
//
// Signal: when fan blade blocks IR beam → lower light → lower voltage on A1.
// Each blade pass = one pulse.
//
// Stream 1: raw A1 reading (u16) at high rate for waveform view
// Stream 2: computed RPM + wind speed (f32, f32) at 1Hz
//
// RPM calculation: done in firmware via interrupt-free pulse counting.
// Threshold crossing with refractory period, counted over 1-second windows.
// Pulse counting is also available in Python from the raw waveform.
//
// Calibration:
//   wind_speed (m/s) = RPM × blade_circumference / (blades × 60)
//   Set !wind.blades (number of fan blades) and !wind.circ (circumference m)
//   to calibrate. Default: 3 blades, 0.05m circumference.
// ─────────────────────────────────────────────────────────────────────────────

#define PIN_LED_A    A3   // LED anode (HIGH)
#define PIN_LED_K    A2   // LED cathode (LOW)
#define PIN_PD_GND   A0   // photodiode GND side (LOW)
#define PIN_PD_SIG   A1   // photodiode signal

UniProto proto(Serial, "WindSpeed");

// ── params ────────────────────────────────────────────────────────────────────
static uint16_t _threshold  = 512;   // pulse detection threshold (ADC counts)
static uint8_t  _blades     = 3;     // number of fan blades
static float    _circ       = 0.05f; // fan circumference (m) for wind speed

// ── pulse counting state ──────────────────────────────────────────────────────
static uint16_t _pulse_count = 0;
static uint16_t _prev_val    = 0;
static uint16_t _since_last  = 0;    // samples since last pulse (refractory)
static const uint16_t REFRACTORY = 5; // samples (~5ms at 1kHz sample rate)

static float   _rpm   = 0.0f;
static float   _mps   = 0.0f;        // wind speed m/s
static uint32_t _window_start = 0;   // millis() at start of counting window
static uint16_t _window_ms   = 1000; // counting window duration

static void countPulse(uint16_t val) {
    // Detect falling edge (blade blocks beam → voltage drops)
    bool falling = (_prev_val >= _threshold) && (val < _threshold);
    _prev_val = val;
    _since_last++;
    if (falling && _since_last >= REFRACTORY) {
        _pulse_count++;
        _since_last = 0;
    }
}

static void updateRPM() {
    uint32_t now = millis();
    uint32_t elapsed = now - _window_start;
    if (elapsed >= _window_ms) {
        float revs_per_sec = (float)_pulse_count / ((float)elapsed / 1000.0f)
                             / (float)_blades;
        _rpm = revs_per_sec * 60.0f;
        _mps = revs_per_sec * _circ;
        _pulse_count  = 0;
        _window_start = now;
    }
}

// ── streams ───────────────────────────────────────────────────────────────────
static uint16_t _last_raw = 0;

static void emitRaw(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    _last_raw = (uint16_t)analogRead(PIN_PD_SIG);
    countPulse(_last_raw);
    w.begin(sid);
    w.u16(_last_raw, "raw");
    w.end();
}

static void emitRPM(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    w.begin(sid);
    w.f32(_rpm,  "rpm", 1);
    w.f32(_mps,  "mps", 3);
    w.u16(_threshold, "thr");
    w.end();
}

// ── params ────────────────────────────────────────────────────────────────────
static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"wind.thr"))    { snprintf(out,len,"%u",_threshold);         return true; }
    if (!strcmp(k,"wind.blades")) { snprintf(out,len,"%u",_blades);            return true; }
    if (!strcmp(k,"wind.circ"))   { snprintf(out,len,"%.4f",(double)_circ);    return true; }
    if (!strcmp(k,"wind.window")) { snprintf(out,len,"%u",_window_ms);         return true; }
    return false;
}

static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"wind.thr"))    { _threshold  = (uint16_t)UniProto::parseInt(v);   return true; }
    if (!strcmp(k,"wind.blades")) { _blades     = (uint8_t)UniProto::parseInt(v);    return true; }
    if (!strcmp(k,"wind.circ"))   { _circ       = UniProto::parseFloat(v);           return true; }
    if (!strcmp(k,"wind.window")) { _window_ms  = (uint16_t)UniProto::parseInt(v);   return true; }
    return false;
}

// ── setup / loop ──────────────────────────────────────────────────────────────
void setup() {
    pinMode(PIN_LED_A,  OUTPUT); digitalWrite(PIN_LED_A,  HIGH);
    pinMode(PIN_LED_K,  OUTPUT); digitalWrite(PIN_LED_K,  LOW);
    pinMode(PIN_PD_GND, OUTPUT); digitalWrite(PIN_PD_GND, LOW);
    pinMode(PIN_PD_SIG, INPUT);

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(200);  // fast raw stream for waveform view

    proto.registerStream({1, "raw",  "u16",         "counts",       emitRaw, nullptr});
    proto.registerStream({2, "wind", "f32,f32,u16", "rpm,mps,thr",  emitRPM, nullptr});

    proto.registerParam({"wind.thr",    UniProto::ParamType::INT32, getParam, setParam, nullptr});
    proto.registerParam({"wind.blades", UniProto::ParamType::INT32, getParam, setParam, nullptr});
    proto.registerParam({"wind.circ",   UniProto::ParamType::FLOAT, getParam, setParam, nullptr});
    proto.registerParam({"wind.window", UniProto::ParamType::INT32, getParam, setParam, nullptr});

    _window_start = millis();
}

void loop() {
    updateRPM();
    proto.tick();
}