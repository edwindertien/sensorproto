#include "mod_psd.h"
#include <stdio.h>
#include <math.h>

PsdModule::PsdModule(const Config& cfg)
: _cfg(cfg),
  _mode(0),
  _vref(cfg.vref),
  _adcMax(cfg.adcMax),
  _win(cfg.avgWindow),
  _calA(cfg.calA),
  _calB(cfg.calB),
  _cmMin(cfg.cmMin),
  _cmMax(cfg.cmMax) {

  setAvgWindow(cfg.avgWindow);
}

void PsdModule::registerWith(UniProto& proto) {
  // Stream
  proto.registerStream({
    _cfg.streamId,
    _cfg.streamName,
    _cfg.schema,
    _cfg.units,
    &PsdModule::emitFn,
    this
  });

  // Params (module)
  proto.registerParam({"psd.mode", UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"psd.vref", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"psd.window", UniProto::ParamType::INT32, &getParam, &setParam, this});

  // Calibration params
  proto.registerParam({"psd.cal_a", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"psd.cal_b", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"psd.cm_min", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"psd.cm_max", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
}

void PsdModule::setAvgWindow(uint8_t w) {
  if (w < 1) w = 1;
  if (w > PSD_MAX_WIN) w = PSD_MAX_WIN;
  _win = w;
  _pos = 0;
  _fill = 0;
}

uint16_t PsdModule::sampleRaw() {
  return (uint16_t)analogRead(_cfg.pin);
}

void PsdModule::pushRing(uint16_t raw) {
  _ring[_pos] = raw;
  _pos = (_pos + 1) % _win;
  if (_fill < _win) _fill++;
}

uint16_t PsdModule::avgRaw() const {
  if (_fill == 0) return 0;
  uint32_t sum = 0;
  for (uint8_t i = 0; i < _fill; ++i) sum += _ring[i];
  return (uint16_t)(sum / _fill);
}

float PsdModule::voltsToCm(float v) const {
  // Inverse model: cm = A / (V - B)
  const float denom = (v - _calB);
  if (denom <= 0.0001f) return _cmMax; // avoid blow-up

  float cm = _calA / denom;

  // clamp (optional but strongly recommended)
  if (cm < _cmMin) cm = _cmMin;
  if (cm > _cmMax) cm = _cmMax;
  return cm;
}

void PsdModule::emitFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx) {
  ((PsdModule*)ctx)->emit(p, streamId, w);
}

void PsdModule::emit(UniProto& p, uint8_t streamId, UniFrameWriter& w) {
  (void)streamId;

  const uint16_t raw = sampleRaw();
  pushRing(raw);

  const bool wantAvg = (_mode == 2 || _mode == 3 || _mode == 5);
  const uint16_t r = wantAvg ? avgRaw() : raw;

  // Binary: only support raw u16 (fixed framing)
  if (p.format() == UniProto::Format::BINARY) {
    w.begin(_cfg.streamId, 2);
    w.u16(r);
    w.end();
    return;
  }

  w.begin(_cfg.streamId);

  if (_mode == 0 || _mode == 2) {
    // raw / avg raw
    w.u16(r);
  } else if (_mode == 1 || _mode == 3) {
    // volts / avg volts
    w.f32(toVolts(r), nullptr, 3);
  } else if (_mode == 4 || _mode == 5) {
    // cm / avg cm
    const float v = toVolts(r);
    w.f32(voltsToCm(v), nullptr, 1);
  } else {
    // unknown -> raw
    w.u16(r);
  }

  w.end();
}

// ---- Param get/set ----
bool PsdModule::getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx) {
  PsdModule* m = (PsdModule*)ctx;

  if (!strcmp(key, "psd.mode"))   { snprintf(out, outLen, "%u", (unsigned)m->_mode); return true; }
  if (!strcmp(key, "psd.window")) { snprintf(out, outLen, "%u", (unsigned)m->_win); return true; }

#if defined(ARDUINO_ARCH_AVR)
  if (!strcmp(key, "psd.vref"))   { dtostrf(m->_vref, 0, 3, out); (void)outLen; return true; }
  if (!strcmp(key, "psd.cal_a"))  { dtostrf(m->_calA, 0, 4, out); (void)outLen; return true; }
  if (!strcmp(key, "psd.cal_b"))  { dtostrf(m->_calB, 0, 4, out); (void)outLen; return true; }
  if (!strcmp(key, "psd.cm_min")) { dtostrf(m->_cmMin, 0, 2, out); (void)outLen; return true; }
  if (!strcmp(key, "psd.cm_max")) { dtostrf(m->_cmMax, 0, 2, out); (void)outLen; return true; }
#else
  if (!strcmp(key, "psd.vref"))   { snprintf(out, outLen, "%.3f", (double)m->_vref); return true; }
  if (!strcmp(key, "psd.cal_a"))  { snprintf(out, outLen, "%.4f", (double)m->_calA); return true; }
  if (!strcmp(key, "psd.cal_b"))  { snprintf(out, outLen, "%.4f", (double)m->_calB); return true; }
  if (!strcmp(key, "psd.cm_min")) { snprintf(out, outLen, "%.2f", (double)m->_cmMin); return true; }
  if (!strcmp(key, "psd.cm_max")) { snprintf(out, outLen, "%.2f", (double)m->_cmMax); return true; }
#endif

  return false;
}

bool PsdModule::setParam(UniProto&, const char* key, const char* value, void* ctx) {
  PsdModule* m = (PsdModule*)ctx;

  if (!strcmp(key, "psd.mode")) {
    long v = UniProto::parseInt(value);
    if (v < 0) v = 0;
    if (v > 5) v = 5;
    m->_mode = (uint8_t)v;
    return true;
  }

  if (!strcmp(key, "psd.vref")) {
    float v = UniProto::parseFloat(value);
    if (v < 0.1f) v = 0.1f;
    if (v > 20.0f) v = 20.0f;
    m->_vref = v;
    return true;
  }

  if (!strcmp(key, "psd.window")) {
    long w = UniProto::parseInt(value);
    if (w < 1) w = 1;
    if (w > PSD_MAX_WIN) w = PSD_MAX_WIN;
    m->setAvgWindow((uint8_t)w);
    return true;
  }

  if (!strcmp(key, "psd.cal_a")) {
    float a = UniProto::parseFloat(value);
    if (a < 1.0f) a = 1.0f;
    m->_calA = a;
    return true;
  }

  if (!strcmp(key, "psd.cal_b")) {
    float b = UniProto::parseFloat(value);
    // allow negative, but clamp to something sane
    if (b > 4.9f) b = 4.9f;
    if (b < -4.9f) b = -4.9f;
    m->_calB = b;
    return true;
  }

  if (!strcmp(key, "psd.cm_min")) {
    float cm = UniProto::parseFloat(value);
    if (cm < 1.0f) cm = 1.0f;
    m->_cmMin = cm;
    return true;
  }

  if (!strcmp(key, "psd.cm_max")) {
    float cm = UniProto::parseFloat(value);
    if (cm < 1.0f) cm = 1.0f;
    m->_cmMax = cm;
    return true;
  }

  return false;
}
