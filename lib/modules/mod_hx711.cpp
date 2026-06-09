#include "mod_hx711.h"
#include <string.h>
#include <stdio.h>

Hx711Module::Hx711Module(const Config& cfg) : _cfg(cfg) {
    // build param key names from prefix
    snprintf(_keyScale, sizeof(_keyScale), "%s.scale",  cfg.prefix);
    snprintf(_keyTare,  sizeof(_keyTare),  "%s.tare",   cfg.prefix);
    snprintf(_keyZero,  sizeof(_keyZero),  "%s.zero",   cfg.prefix);
    snprintf(_keyAvg,   sizeof(_keyAvg),   "%s.avg",    cfg.prefix);
    snprintf(_keyRaw,   sizeof(_keyRaw),   "%s.raw",    cfg.prefix);
}

void Hx711Module::registerWith(UniProto& proto) {
    pinMode(_cfg.pinDout, INPUT);
    pinMode(_cfg.pinSck,  OUTPUT);
    digitalWrite(_cfg.pinSck, LOW);

    proto.registerStream({
        _cfg.streamId,
        _cfg.streamName,
        "i32,f32",
        _cfg.units,
        &Hx711Module::emitFn,
        this
    });

    proto.registerParam({_keyScale, UniProto::ParamType::FLOAT, getParam, setParam, this});
    proto.registerParam({_keyTare,  UniProto::ParamType::INT32, getParam, setParam, this});
    proto.registerParam({_keyZero,  UniProto::ParamType::BOOL,  getParam, setParam, this});
    proto.registerParam({_keyAvg,   UniProto::ParamType::INT32, getParam, setParam, this});
    proto.registerParam({_keyRaw,   UniProto::ParamType::INT32, getParam, setParam, this});
}

bool Hx711Module::isReady() const {
    return digitalRead(_cfg.pinDout) == LOW;
}

int32_t Hx711Module::readOnce() {
    // Wait up to 100ms for data ready
    uint32_t t0 = millis();
    while (digitalRead(_cfg.pinDout) == HIGH) {
        if ((uint32_t)(millis() - t0) > 100) return _last; // timeout, return stale
    }

    uint32_t raw = 0;
    for (int i = 0; i < 24; i++) {
        digitalWrite(_cfg.pinSck, HIGH);
        raw = (raw << 1) | (uint32_t)digitalRead(_cfg.pinDout);
        digitalWrite(_cfg.pinSck, LOW);
    }

    // Extra pulses select gain/channel for next read
    uint8_t pulses = 1;  // default: ch A gain 128
    if      (_cfg.gain == 32)  pulses = 2;  // ch B gain 32
    else if (_cfg.gain == 64)  pulses = 3;  // ch A gain 64

    for (uint8_t p = 0; p < pulses; p++) {
        digitalWrite(_cfg.pinSck, HIGH);
        digitalWrite(_cfg.pinSck, LOW);
    }

    // Sign-extend from 24-bit
    if (raw & 0x800000) raw |= 0xFF000000;
    return (int32_t)raw;
}

int32_t Hx711Module::readAvg(uint8_t n) {
    if (n < 1) n = 1;
    int64_t sum = 0;
    for (uint8_t i = 0; i < n; i++) {
        sum += readOnce();
    }
    return (int32_t)(sum / n);
}

int32_t Hx711Module::readRaw() {
    _last = readAvg(_cfg.avgCount);
    return _last;
}

float Hx711Module::toUnits(int32_t raw) const {
    if (_cfg.scale == 0.0f) return 0.0f;
    return (float)(raw - _cfg.tare) / _cfg.scale;
}

void Hx711Module::poll() {
    if (isReady()) readRaw();
}

// ── stream ────────────────────────────────────────────────────────────────────

void Hx711Module::emitFn(UniProto& p, uint8_t sid, UniFrameWriter& w, void* ctx) {
    ((Hx711Module*)ctx)->emit(p, sid, w);
}

void Hx711Module::emit(UniProto& p, uint8_t sid, UniFrameWriter& w) {
    _last = readAvg(_cfg.avgCount);
    const float units = toUnits(_last);
    w.begin(sid);
    w.i32(_last,  "raw");
    w.f32(units, "val", 3);
    w.end();
}

// ── params ────────────────────────────────────────────────────────────────────

bool Hx711Module::getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx) {
    auto* m = (Hx711Module*)ctx;

    if (!strcmp(key, m->_keyScale)) {
#if defined(ARDUINO_ARCH_AVR)
        dtostrf(m->_cfg.scale, 0, 6, out); (void)outLen;
#else
        snprintf(out, outLen, "%.6f", (double)m->_cfg.scale);
#endif
        return true;
    }
    if (!strcmp(key, m->_keyTare)) {
        snprintf(out, outLen, "%ld", (long)m->_cfg.tare);
        return true;
    }
    if (!strcmp(key, m->_keyZero)) {
        snprintf(out, outLen, "0");   // write-only trigger
        return true;
    }
    if (!strcmp(key, m->_keyAvg)) {
        snprintf(out, outLen, "%u", (unsigned)m->_cfg.avgCount);
        return true;
    }
    if (!strcmp(key, m->_keyRaw)) {
        snprintf(out, outLen, "%ld", (long)m->_last);
        return true;
    }
    return false;
}

bool Hx711Module::setParam(UniProto&, const char* key, const char* value, void* ctx) {
    auto* m = (Hx711Module*)ctx;

    if (!strcmp(key, m->_keyScale)) {
        m->_cfg.scale = UniProto::parseFloat(value);
        return true;
    }
    if (!strcmp(key, m->_keyTare)) {
        m->_cfg.tare = UniProto::parseInt(value);
        return true;
    }
    if (!strcmp(key, m->_keyZero)) {
        // Capture current reading as tare zero
        if (UniProto::parseInt(value)) {
            m->_last = m->readAvg(8);  // average 8 readings for stable zero
            m->_cfg.tare = m->_last;
        }
        return true;
    }
    if (!strcmp(key, m->_keyAvg)) {
        long v = UniProto::parseInt(value);
        if (v < 1) v = 1;
        if (v > 32) v = 32;
        m->_cfg.avgCount = (uint8_t)v;
        return true;
    }
    return false;
}