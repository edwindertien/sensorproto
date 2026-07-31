#include <Arduino.h>
#include "UniProto.h"

// ── Pololu QTR-8RC — Duemilanove ATmega328p ───────────────────────────────────
// Sensors on digital pins 4–11 (parallel RC discharge timing).
//
// Streams (enable what you need):
//   1 "raw"  : s0..s7 decay times in µs (8× u16)
//              The primary stream — everything else can be derived from this.
//   2 "bin"  : b0..b7 thresholded 0/1   (8× u16)
//   3 "line" : line position 0.0–7.0     (f32)   weighted centroid
//   4 "gray" : gray-code pattern          (u16)   for 256-position strip
//
// Python derives all of the above from stream 1 independently.
// Streams 2-4 exist for use without Python (MIDI, other consumers).
//
// Commands:
//   !qtr.thr:1000       binary threshold µs (default 1000)
//   !qtr.timeout:2500   max decay µs = full black (default 2500)
//   @qtr.cal            auto-calibrate threshold from current scene
// ─────────────────────────────────────────────────────────────────────────────

#define N    8
#define PINS_START 4   // pins 4..11

UniProto proto(Serial, "QTR8");

static uint16_t _thr     = 1000;
static uint16_t _timeout = 2500;
static uint16_t _raw[N]  = {0};

static void readAll() {
    // Charge all capacitors simultaneously
    for (uint8_t i = 0; i < N; i++) {
        pinMode(PINS_START + i, OUTPUT);
        digitalWrite(PINS_START + i, HIGH);
    }
    delayMicroseconds(10);
    // Release and time decay in parallel
    uint32_t t0 = micros();
    for (uint8_t i = 0; i < N; i++) {
        pinMode(PINS_START + i, INPUT);
        _raw[i] = _timeout;
    }
    while (micros() - t0 < _timeout) {
        uint32_t elapsed = micros() - t0;
        bool all_done = true;
        for (uint8_t i = 0; i < N; i++) {
            if (_raw[i] == _timeout) {
                if (digitalRead(PINS_START + i) == LOW)
                    _raw[i] = (uint16_t)elapsed;
                else
                    all_done = false;
            }
        }
        if (all_done) break;
    }
}

// Stream 1: raw decay times
static void emitRaw(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    w.begin(sid);
    for (uint8_t i = 0; i < N; i++) w.u16(_raw[i], "us");
    w.end();
}

// Stream 2: binary threshold
static void emitBin(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    w.begin(sid);
    for (uint8_t i = 0; i < N; i++) w.u16(_raw[i] >= _thr ? 1 : 0, "b");
    w.end();
}

// Stream 3: line position — pure weighted centroid, no threshold
static void emitLine(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    uint32_t w_sum = 0, wi_sum = 0;
    for (uint8_t i = 0; i < N; i++) {
        w_sum  += _raw[i];
        wi_sum += (uint32_t)i * _raw[i];
    }
    // Scale centroid (0..7) to 0..255
    float pos = w_sum > 0 ? ((float)wi_sum / w_sum) / 7.0f * 255.0f : -1.0f;
    w.begin(sid); w.f32(pos, "pos", 2); w.end();
}

// Stream 4: gray code pattern
static void emitGray(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    uint16_t g = 0;
    for (uint8_t i = 0; i < N; i++)
        if (_raw[i] >= _thr) g |= (1 << (N - 1 - i));
    w.begin(sid); w.u16(g, "gray"); w.end();
}

static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"qtr.thr"))     { snprintf(out,len,"%u",_thr);     return true; }
    if (!strcmp(k,"qtr.timeout")) { snprintf(out,len,"%u",_timeout); return true; }
    return false;
}
static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"qtr.thr"))     { _thr     = (uint16_t)UniProto::parseInt(v); return true; }
    if (!strcmp(k,"qtr.timeout")) { _timeout = (uint16_t)UniProto::parseInt(v); return true; }
    return false;
}

static bool doCal(UniProto&, const char*, const char*, Stream& out, void*) {
    uint32_t sum = 0;
    for (uint8_t s = 0; s < 50; s++) { readAll(); for (uint8_t i=0;i<N;i++) sum+=_raw[i]; delay(10); }
    _thr = (uint16_t)(sum / (50 * N));
    out.print(F("qtr.cal thr=")); out.println(_thr);
    return true;
}

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(20);
    proto.registerStream({1,"raw", "u16,u16,u16,u16,u16,u16,u16,u16","s0,s1,s2,s3,s4,s5,s6,s7",emitRaw, nullptr});
    proto.registerStream({2,"bin", "u16,u16,u16,u16,u16,u16,u16,u16","b0,b1,b2,b3,b4,b5,b6,b7",emitBin, nullptr});
    proto.registerStream({3,"line","f32",                              "pos",                     emitLine,nullptr});
    proto.registerStream({4,"gray","u16",                              "gray",                    emitGray,nullptr});
    proto.registerParam({"qtr.thr",    UniProto::ParamType::INT32,getParam,setParam,nullptr});
    proto.registerParam({"qtr.timeout",UniProto::ParamType::INT32,getParam,setParam,nullptr});
    proto.registerAction({"qtr.cal", doCal, nullptr});
}

void loop() {
    readAll();
    proto.tick();
}