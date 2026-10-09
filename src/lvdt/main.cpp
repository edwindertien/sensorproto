#include <Arduino.h>
#include "UniProto.h"

// ── LVDT — Linear Variable Differential Transformer ──────────────────────────
// Primary coil excited with anti-phase filtered PWM on pins 9 and 10.
// Secondary coils wired in series opposition, differential output to GND + A1.
//
// Working principle:
//   Pin 9  -> 100Ω + 1µF RC filter -> primary half A (0°)
//   Pin 10 -> 100Ω + 1µF RC filter -> primary half B (180°, anti-phase)
//   The two halves drive the primary coil differentially.
//   Secondary coils in series opposition: when core is centred, the two
//   induced voltages cancel (zero output). Displacement from centre causes
//   an imbalance proportional to position.
//   A1 = differential secondary output (with optional series capacitor)
//
// Signal: same frequency as excitation (100Hz here, 48 samples at 5kHz).
// Position: amplitude of receiver / amplitude of excitation.
//   At centre: receiver ≈ 0  → position = 0
//   Displaced: receiver has amplitude proportional to displacement.
//   Phase of receiver (0° or 180° vs excitation) tells direction.
//
// Streams:
//   1 "lvdt.pos"   : position f32 (-1.0 to +1.0 normalised, 0=centre)
//   2 "lvdt.frame" : 480-sample raw capture frame (chunked, oscilloscope view)
//                    Same format as synchro frame: id, off, count, raw bytes
//
// Commands:
//   !lvdt.zero     zero position at current location
//   !lvdt.scale    full-scale calibration factor (default 1.0)
// ─────────────────────────────────────────────────────────────────────────────

#define FRAME_N   480
#define CYCLE_N    48    // samples per excitation cycle (5kHz / 100Hz)
#define CHUNK_N    60    // chunks per frame (480/60 = 8)

UniProto proto(Serial, "LVDT");

// Sine table — 0°  phase for pin 9
// Anti-phase for pin 10 = sineTable[(n + 24) % 48]  (24 = half cycle)
static uint8_t _sine[CYCLE_N];

// Capture buffer
static volatile uint8_t  _cap[FRAME_N];
static volatile uint16_t _wIdx  = 0;
static volatile uint16_t _fCnt  = 0;   // frame counter

// Transmission state
static uint16_t _txFId   = 0;
static uint16_t _txOff   = 0;
static bool     _txPend  = false;
static uint16_t _lastFCnt = 0;
static uint16_t _frameId  = 0;

// Position
static float _pos       = 0.0f;
static float _zero_off  = 0.0f;
static float _scale     = 1.0f;

// Timer2 ISR counter (shared with both PWM outputs)
static volatile uint16_t _z = 0;

ISR(TIMER2_OVF_vect) {
    TCNT2 = 0xCE;   // reload for 5kHz

    // Anti-phase excitation:
    // Pin 9  = sine at phase z
    // Pin 10 = sine at phase z + 24 (180° = CYCLE_N/2)
    analogWrite(9,  _sine[_z % CYCLE_N]);
    analogWrite(10, _sine[(_z + CYCLE_N/2) % CYCLE_N]);

    // Sample receiver
    _cap[_wIdx] = (uint8_t)(analogRead(A1) >> 2);

    _z++;
    _wIdx++;
    if (_wIdx >= FRAME_N) { _wIdx = 0; _fCnt++; }
}

// ── Position computation ──────────────────────────────────────────────────────
// Correlate captured signal against reference sine to get amplitude and phase.
// Amplitude = peak of cross-correlation → magnitude of displacement.
// Phase (0° or 180° vs reference) → sign of displacement.
static float computePos() {
    // Use the last complete cycle ending at _wIdx
    uint16_t base = (_wIdx + FRAME_N - CYCLE_N) % FRAME_N;

    float corr_sin = 0.0f, corr_cos = 0.0f;
    for (uint16_t n = 0; n < CYCLE_N; n++) {
        float v = (float)_cap[(base + n) % FRAME_N] - 127.0f;
        float ref_sin = (float)_sine[n] - 127.0f;
        float ref_cos = (float)_sine[(n + CYCLE_N/4) % CYCLE_N] - 127.0f;
        corr_sin += v * ref_sin;
        corr_cos += v * ref_cos;
    }

    // Amplitude of correlation (normalised by expected max)
    float amp   = sqrtf(corr_sin*corr_sin + corr_cos*corr_cos);
    float phase = atan2f(corr_sin, corr_cos);   // sign tells direction

    // Normalise: max correlation when signal = reference, amp ≈ 127²×CYCLE_N/2
    float norm = amp / (127.0f * 127.0f * CYCLE_N / 2.0f);

    // Apply direction: phase near 0 = positive, near ±π = negative
    float pos = norm * (cosf(phase) >= 0 ? 1.0f : -1.0f);
    return (pos - _zero_off) * _scale;
}

// ── Streams ───────────────────────────────────────────────────────────────────
static void emitPos(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    _pos = computePos();
    w.begin(sid); w.f32(_pos, "pos", 4); w.end();
}

static void emitFrame(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    if (!_txPend) {
        if (_fCnt == _lastFCnt) return;
        _lastFCnt = _fCnt;
        _txPend  = true;
        _txOff   = 0;
        _txFId   = ++_frameId;
    }

    uint16_t remaining = FRAME_N - _txOff;
    uint16_t count = (remaining < CHUNK_N) ? remaining : CHUNK_N;

    uint8_t chunk[CHUNK_N];
    for (uint16_t i = 0; i < count; i++) chunk[i] = _cap[_txOff + i];

    w.begin(sid);
    w.u16(_txFId, "id"); w.u16(_txOff, "off"); w.u16(count, "cnt");
    for (uint16_t i = 0; i < count; i++) w.u16(chunk[i], "s");
    w.end();

    _txOff += count;
    if (_txOff >= FRAME_N) { _txPend = false; _txOff = 0; }
}

// ── Params ────────────────────────────────────────────────────────────────────
static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"lvdt.scale")) { snprintf(out,len,"%.3f",(double)_scale);    return true; }
    if (!strcmp(k,"lvdt.pos"))   { snprintf(out,len,"%.4f",(double)_pos);      return true; }
    return false;
}
static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"lvdt.scale")) { _scale = UniProto::parseFloat(v); return true; }
    return false;
}
static bool doZero(UniProto&, const char*, const char*, Stream& out, void*) {
    _zero_off = computePos() / _scale;
    out.println(F("lvdt.zero"));
    return true;
}

// ── Setup / loop ──────────────────────────────────────────────────────────────
void setup() {
    // Build sine table
    for (uint16_t n = 0; n < CYCLE_N; n++) {
        float v = 127.0f * sinf(2.0f * (float)PI * n / CYCLE_N) + 127.0f;
        _sine[n] = (uint8_t)v;
    }

    pinMode(9,  OUTPUT);
    pinMode(10, OUTPUT);

    // Fast PWM on Timer1 (pins 9, 10): no prescale
    TCCR1B = (1<<CS10);   // prescale 1

    // Timer2: 5kHz ISR (not used for PWM output — analogWrite handles that)
    TCCR2A = 0;
    TCCR2B = 4;            // prescale 64
    TIMSK2 = 1<<TOIE2;
    TCNT2  = 0xCE;

    Serial.begin(38400);   // conservative — Timer2 ISR is timing-critical
    proto.begin();
    proto.setRateHz(20);

    proto.registerStream({1,"lvdt.pos",  "f32",                "pos",          emitPos,   nullptr});
    proto.registerStream({2,"lvdt.frame","u16,u16,u16,...","id,off,cnt,s0..sN",emitFrame,nullptr});

    proto.registerParam({"lvdt.scale", UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerParam({"lvdt.pos",   UniProto::ParamType::FLOAT, getParam,setParam,nullptr});
    proto.registerAction({"lvdt.zero", doZero, nullptr});
}

void loop() {
    proto.tick();
}

