#include "mod_synchro.h"
#include <string.h>
#include <math.h>

SynchroModule* SynchroModule::_activeInstance = nullptr;

SynchroModule::SynchroModule(const Config& cfg) : _cfg(cfg) {
    buildSineTable();
}

void SynchroModule::buildSineTable() {
    for (int n = 0; n < SYNCHRO_SAMPLES_PER_CYCLE; n++) {
        float v = 127.0f * sinf(2.0f * (float)PI * n / SYNCHRO_SAMPLES_PER_CYCLE) + 127.0f;
        _sineTable[n] = (uint8_t)v;
    }
}

void SynchroModule::registerWith(UniProto& proto) {
    proto.registerStream({
        _cfg.streamAngleId, _cfg.streamAngleName,
        "f32", "deg",
        &SynchroModule::emitAngleFn, this
    });

    proto.registerStream({
        _cfg.streamFrameId, _cfg.streamFrameName,
        "u16,u16,u16,u8[block]", "id,off,count,raw8",
        &SynchroModule::emitFrameFn, this
    });

    proto.registerParam({"syn.offset", UniProto::ParamType::FLOAT, getParam, setParam, this});
    proto.registerParam({"syn.capture", UniProto::ParamType::BOOL, getParam, setParam, this});
}

void SynchroModule::begin() {
    pinMode(_cfg.pinA, OUTPUT);
    pinMode(_cfg.pinB, OUTPUT);
    pinMode(_cfg.pinC, OUTPUT);

    _activeInstance = this;

    // PWM timers: Fast PWM, no prescale (matches original sketch exactly)
    TCCR1B = 1;   // Timer1 (drives pins 9, 10 PWM) — divider 1, Fast PWM
    TCCR0B = 1;   // Timer0 (drives pin 5 PWM)      — divider 1, Fast PWM

    // Timer2 configured as a free-running interrupt source at 5kHz,
    // NOT used for PWM output (no OCR/PWM bits set).
    TCCR2A = 0;
    TCCR2B = 4;          // clock / 64 prescale
    TIMSK2 = 1 << TOIE2; // enable Timer2 overflow interrupt
    TCNT2  = 0xCE;       // preload for ~5kHz at 16MHz/64
}

// ── ISR ───────────────────────────────────────────────────────────────────────
// Static trampoline — the actual ISR vector calls this.
void SynchroModule::isrHandler() {
    if (_activeInstance) _activeInstance->onTimerTick();
}

ISR(TIMER2_OVF_vect) {
    TCNT2 = 0xCE;   // reload for next 5kHz tick
    SynchroModule::isrHandler();
}

void SynchroModule::onTimerTick() {
    static uint16_t z = 0;

    analogWrite(_cfg.pinA, _sineTable[z % SYNCHRO_SAMPLES_PER_CYCLE]);
    analogWrite(_cfg.pinB, _sineTable[(z + 16) % SYNCHRO_SAMPLES_PER_CYCLE]); // +120°
    analogWrite(_cfg.pinC, _sineTable[(z + 32) % SYNCHRO_SAMPLES_PER_CYCLE]); // +240°

    _capture[_writeIdx] = (uint8_t)(analogRead(_cfg.pinIn) >> 2);  // 10-bit -> 8-bit

    _writeIdx++;
    z++;
    if (_writeIdx >= SYNCHRO_FRAME_SAMPLES) {
        _writeIdx = 0;
        _frameCount++;
    }
}

// ── angle computation (cross-correlation, runs outside ISR) ─────────────────

float SynchroModule::computeAngle() {
    // Cross-correlate the most recent full cycle of captured data against
    // the known excitation sine table to find the phase shift.
    // We use the last 48 samples (one full cycle) ending at _writeIdx.
    //
    // This runs with interrupts on; reading volatile _capture mid-write is
    // a benign race (worst case: one stale sample in 48), acceptable for
    // a slowly-rotating mechanical synchro.

    uint16_t base = (_writeIdx + SYNCHRO_FRAME_SAMPLES - SYNCHRO_SAMPLES_PER_CYCLE)
                     % SYNCHRO_FRAME_SAMPLES;

    float bestCorr = -1e9f;
    int   bestShift = 0;

    for (int shift = 0; shift < SYNCHRO_SAMPLES_PER_CYCLE; shift++) {
        float corr = 0.0f;
        for (int n = 0; n < SYNCHRO_SAMPLES_PER_CYCLE; n++) {
            uint16_t idx = (base + n) % SYNCHRO_FRAME_SAMPLES;
            float capVal = (float)_capture[idx] - 127.0f;
            float refVal = (float)_sineTable[(n + shift) % SYNCHRO_SAMPLES_PER_CYCLE] - 127.0f;
            corr += capVal * refVal;
        }
        if (corr > bestCorr) {
            bestCorr  = corr;
            bestShift = shift;
        }
    }

    float angle = (360.0f * bestShift) / SYNCHRO_SAMPLES_PER_CYCLE;
    angle = fmodf(angle - _offsetDeg + 720.0f, 360.0f);
    return angle;
}

// ── streams ───────────────────────────────────────────────────────────────────

void SynchroModule::emitAngleFn(UniProto& p, uint8_t sid, UniFrameWriter& w, void* ctx) {
    ((SynchroModule*)ctx)->emitAngle(p, sid, w);
}

void SynchroModule::emitAngle(UniProto& p, uint8_t sid, UniFrameWriter& w) {
    _angleDeg = computeAngle();
    if (p.format() == UniProto::Format::BINARY) {
        w.begin(sid, 4);   // single f32 = 4 bytes
    } else {
        w.begin(sid);
    }
    w.f32(_angleDeg, "deg", 2);
    w.end();
}

void SynchroModule::emitFrameFn(UniProto& p, uint8_t sid, UniFrameWriter& w, void* ctx) {
    ((SynchroModule*)ctx)->emitFrame(p, sid, w);
}

void SynchroModule::emitFrame(UniProto& p, uint8_t sid, UniFrameWriter& w) {
    if (!_txPending) {
        // wait for a new completed frame
        if (_frameCount == _lastSeenFrameCount) return;
        _lastSeenFrameCount = _frameCount;
        _txPending = true;
        _txOffset  = 0;
        _txFrameId = ++_frameId;
    }

    const uint16_t remaining = (uint16_t)(SYNCHRO_FRAME_SAMPLES - _txOffset);
    const uint16_t count = (remaining < SYNCHRO_CHUNK_SAMPLES) ? remaining : SYNCHRO_CHUNK_SAMPLES;

    // Snapshot chunk bytes (copy out of volatile buffer)
    uint8_t chunk[SYNCHRO_CHUNK_SAMPLES];
    for (uint16_t i = 0; i < count; i++) {
        chunk[i] = _capture[_txOffset + i];
    }

    // payloadLen must be exact: 3x u16 header (id, off, count) + count data bytes
    const uint16_t payloadLen = (uint16_t)(3 * 2 + count);

    if (p.format() == UniProto::Format::BINARY) {
        w.begin(sid, payloadLen);
    } else {
        w.begin(sid);
    }
    w.u16(_txFrameId, "id");
    w.u16(_txOffset,  "off");
    w.u16(count,       "count");
    w.bytes(chunk, count);
    w.end();

    _txOffset = (uint16_t)(_txOffset + count);
    if (_txOffset >= SYNCHRO_FRAME_SAMPLES) {
        _txPending = false;
        _txOffset  = 0;
    }
}

// ── params ────────────────────────────────────────────────────────────────────

bool SynchroModule::getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx) {
    auto* m = (SynchroModule*)ctx;
    if (!strcmp(key, "syn.offset")) {
        snprintf(out, outLen, "%.2f", (double)m->_offsetDeg);
        return true;
    }
    if (!strcmp(key, "syn.capture")) {
        snprintf(out, outLen, "%d", m->_txPending ? 1 : 0);
        return true;
    }
    return false;
}

bool SynchroModule::setParam(UniProto&, const char* key, const char* value, void* ctx) {
    auto* m = (SynchroModule*)ctx;
    if (!strcmp(key, "syn.offset")) {
        m->_offsetDeg = UniProto::parseFloat(value);
        return true;
    }
    if (!strcmp(key, "syn.capture")) {
        // Force the next emitFrame() call to start a fresh frame transmission
        if (UniProto::parseInt(value)) {
            m->_lastSeenFrameCount = (uint16_t)(m->_frameCount - 1);
            m->_txPending = false;
        }
        return true;
    }
    return false;
}