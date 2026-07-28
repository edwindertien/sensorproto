#include <Arduino.h>
#include "UniProto.h"

// ── Piezo plates — serial streaming via UniProto ──────────────────────────────
// 4 piezo plates on A0..A3 (Arduino Leonardo).
// Streams raw ADC values at high rate for waveform visualisation,
// plus detected strike events (channel, peak amplitude) for the heatmap view.
//
// Piezo physics: idle ≈ 512 (mid-rail). Strike produces a fast spike
// above or below mid. We track the envelope and detect impacts.
//
// Stream 1 "raw"    : A0,A1,A2,A3 raw ADC (4× u16) at 200Hz
// Stream 2 "strike" : channel(u8), peak(u16) — emitted on each detected hit
//
// Strike detection:
//   - Signal crosses THRESHOLD above baseline → strike starts
//   - Peak tracked for PEAK_WINDOW ms
//   - Strike emitted with peak value when signal returns below threshold
//
// Useful commands:
//   !stream:1           waveform only
//   !stream:2           strike events only
//   !stream:+1 !stream:+2  both
//   !piezo.thr:100      detection threshold (default 80)
//   !piezo.window:20    peak window ms (default 20)
// ─────────────────────────────────────────────────────────────────────────────

#define NUM_CH    4
#define BASELINE  512

UniProto proto(Serial, "PiezoSerial");

static uint16_t _threshold   = 80;    // counts above baseline to trigger
static uint16_t _peak_window = 20;    // ms to collect peak after trigger

// Per-channel strike state
struct Ch {
    uint16_t peak    = 0;
    uint32_t peak_t  = 0;
    bool     active  = false;
};
static Ch _ch[NUM_CH];

// Last raw readings
static uint16_t _raw[NUM_CH] = {512,512,512,512};

// Pending strike event (queued for stream 2 emit)
struct Strike {
    uint8_t  ch;
    uint16_t peak;
    bool     pending;
};
static Strike _strike = {0, 0, false};

static void emitRaw(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    w.begin(sid);
    w.u16(sid, "sid");
    for (uint8_t i = 0; i < NUM_CH; i++) w.u16(_raw[i], "raw");
    w.end();
}

static void emitStrike(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    if (!_strike.pending) return;
    w.begin(sid);
    w.u16(sid, "sid");
    w.u16(_strike.ch,   "ch");
    w.u16(_strike.peak, "peak");
    w.end();
    _strike.pending = false;
}

static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"piezo.thr"))    { snprintf(out,len,"%u",_threshold);   return true; }
    if (!strcmp(k,"piezo.window")) { snprintf(out,len,"%u",_peak_window); return true; }
    return false;
}
static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"piezo.thr"))    { _threshold   = (uint16_t)UniProto::parseInt(v); return true; }
    if (!strcmp(k,"piezo.window")) { _peak_window = (uint16_t)UniProto::parseInt(v); return true; }
    return false;
}

void setup() {
    Serial.begin(115200);
    while (!Serial);   // Leonardo: wait for USB CDC to be ready
    proto.begin();
    proto.setRateHz(200);   // fast for waveform capture
    proto.registerStream({1, "raw",    "u16,u16,u16,u16,u16", "sid,A0,A1,A2,A3", emitRaw,    nullptr});
    proto.registerStream({2, "strike", "u16,u16,u16",          "sid,ch,peak",      emitStrike, nullptr});
    proto.registerParam({"piezo.thr",    UniProto::ParamType::INT32, getParam, setParam, nullptr});
    proto.registerParam({"piezo.window", UniProto::ParamType::INT32, getParam, setParam, nullptr});
}

void loop() {
    uint32_t now = millis();

    // Sample all channels
    for (uint8_t i = 0; i < NUM_CH; i++) {
        _raw[i] = (uint16_t)analogRead(i);
        uint16_t dev = (uint16_t)abs((int)_raw[i] - BASELINE);

        if (!_ch[i].active) {
            if (dev >= _threshold) {
                // Strike started
                _ch[i].active = true;
                _ch[i].peak   = dev;
                _ch[i].peak_t = now;
            }
        } else {
            // Collecting peak
            if (dev > _ch[i].peak) _ch[i].peak = dev;
            if ((now - _ch[i].peak_t) >= _peak_window) {
                // Emit strike if no other pending
                if (!_strike.pending) {
                    _strike.ch      = i;
                    _strike.peak    = _ch[i].peak;
                    _strike.pending = true;
                }
                _ch[i].active = false;
                _ch[i].peak   = 0;
            }
        }
    }

    proto.tick();
}