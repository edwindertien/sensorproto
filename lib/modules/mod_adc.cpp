#include "mod_adc.h"
#include <stdio.h>
#include <math.h>

AdcModule::AdcModule(const Config& cfg)
: _cfg(cfg),
  _vref(cfg.vref),
  _adcMax(cfg.adcMax),
  _win(cfg.avgWindow),
  _blockHz(cfg.block.sampleHz) {

  // Clamp runtime config to allocated storage
  if (_cfg.channelCount > ADC_MAX_CH) _cfg.channelCount = ADC_MAX_CH;

  // Clamp values streams count
  if (_cfg.valuesCount < 1) _cfg.valuesCount = 1;
  if (_cfg.valuesCount > ADC_MAX_VALUE_STREAMS) _cfg.valuesCount = ADC_MAX_VALUE_STREAMS;

  // Clamp each values stream selection
  for (uint8_t si = 0; si < _cfg.valuesCount; ++si) {
    ValuesStreamCfg& vs = _cfg.values[si];

    // selCount==0 means "all channels"
    if (vs.selCount > _cfg.channelCount) vs.selCount = _cfg.channelCount;

    // Clamp indices
    for (uint8_t k = 0; k < vs.selCount; ++k) {
      if (vs.selIdx[k] >= _cfg.channelCount) vs.selIdx[k] = 0;
    }
  }

  // Clamp block source channel
  if (_cfg.block.sourceChanIdx >= _cfg.channelCount) _cfg.block.sourceChanIdx = 0;

  setAvgWindow(cfg.avgWindow);
  setBlockSampleHz(cfg.block.sampleHz);
}

void AdcModule::setAvgWindow(uint8_t w) {
  if (w < 1) w = 1;
  if (w > ADC_MAX_WIN) w = ADC_MAX_WIN;
  _win = w;
  _pos = 0;
  _fill = 0;
}

void AdcModule::setBlockSampleHz(uint16_t hz) {
  if (hz < 1) hz = 1;
  if (hz > 4000) hz = 4000; // RP2040 can go higher; AVR likely limited by analogRead
  _blockHz = hz;
}

bool AdcModule::blockDue(uint32_t nowUs) const {
  const uint32_t periodUs = 1000000UL / (uint32_t)_blockHz;
  return (uint32_t)(nowUs - _lastBlockSampleUs) >= periodUs;
}

void AdcModule::registerWith(UniProto& proto) {
  // Final safety clamp (in case config was modified externally)
  if (_cfg.channelCount > ADC_MAX_CH) _cfg.channelCount = ADC_MAX_CH;
  if (_win > ADC_MAX_WIN) _win = ADC_MAX_WIN;

  if (_cfg.valuesCount < 1) _cfg.valuesCount = 1;
  if (_cfg.valuesCount > ADC_MAX_VALUE_STREAMS) _cfg.valuesCount = ADC_MAX_VALUE_STREAMS;

  // Register all value streams
  for (uint8_t i = 0; i < _cfg.valuesCount; ++i) {
    proto.registerStream({
      _cfg.values[i].id,
      _cfg.values[i].name,
      _cfg.values[i].schema,
      _cfg.values[i].units,
      &AdcModule::emitValuesFn,
      this
    });
  }

  // Register block stream
  proto.registerStream({
    _cfg.block.id,
    _cfg.block.name,
    _cfg.block.schema,
    _cfg.block.units,
    &AdcModule::emitBlockFn,
    this
  });

  // Params
  proto.registerParam({"adc.mode",     UniProto::ParamType::INT32,
                       &AdcModule::getMode,    &AdcModule::setMode,    this});
  proto.registerParam({"adc.vref",     UniProto::ParamType::FLOAT,
                       &AdcModule::getVref,    &AdcModule::setVref,    this});
  proto.registerParam({"adc.window",   UniProto::ParamType::INT32,
                       &AdcModule::getWindow,  &AdcModule::setWindow,  this});
  proto.registerParam({"adc.block_hz", UniProto::ParamType::INT32,
                       &AdcModule::getBlockHz, &AdcModule::setBlockHz, this});

  // Action
  proto.registerAction({"adc.block_reset", &AdcModule::doBlockReset, this});
}

void AdcModule::emitValuesFn(UniProto& p, uint8_t streamId,
                            UniFrameWriter& w, void* ctx) {
  ((AdcModule*)ctx)->emitValues(p, streamId, w);
}

void AdcModule::emitBlockFn(UniProto& p, uint8_t streamId,
                            UniFrameWriter& w, void* ctx) {
  ((AdcModule*)ctx)->emitBlock(p, streamId, w);
}

void AdcModule::sampleRaw(uint16_t* raw) {
  for (uint8_t i = 0; i < _cfg.channelCount; ++i) {
    raw[i] = (uint16_t)analogRead(_cfg.channels[i]);
  }
}

void AdcModule::pushRing(const uint16_t* raw) {
  for (uint8_t ch = 0; ch < _cfg.channelCount; ++ch) {
    _ring[_pos][ch] = raw[ch];
  }
  _pos = (_pos + 1) % _win;
  if (_fill < _win) _fill++;
}

void AdcModule::computeAvg(uint16_t* avg) const {
  for (uint8_t ch = 0; ch < _cfg.channelCount; ++ch) {
    uint32_t sum = 0;
    for (uint8_t i = 0; i < _fill; ++i) sum += _ring[i][ch];
    avg[ch] = (_fill == 0) ? 0 : (uint16_t)(sum / _fill);
  }
}

uint8_t AdcModule::findValuesStreamIndexById(uint8_t streamId) const {
  for (uint8_t i = 0; i < _cfg.valuesCount; ++i) {
    if (_cfg.values[i].id == streamId) return i;
  }
  return 0xFF;
}

void AdcModule::emitSelected(const uint16_t* rawOrAvg,
                             uint8_t streamIdx,
                             UniFrameWriter& w,
                             bool asVolts) {
  const ValuesStreamCfg& vs = _cfg.values[streamIdx];
  const bool useAll = (vs.selCount == 0);

  const uint8_t m = useAll ? _cfg.channelCount : vs.selCount;

  if (asVolts) {
    for (uint8_t k = 0; k < m; ++k) {
      const uint8_t ch = useAll ? k : vs.selIdx[k];
      w.f32(toVolts(rawOrAvg[ch]), nullptr, 3);
    }
  } else {
    for (uint8_t k = 0; k < m; ++k) {
      const uint8_t ch = useAll ? k : vs.selIdx[k];
      w.u16(rawOrAvg[ch]);
    }
  }
}

void AdcModule::emitValues(UniProto& p, uint8_t streamId, UniFrameWriter& w) {
  const uint8_t streamIdx = findValuesStreamIndexById(streamId);
  if (streamIdx == 0xFF) return;

  uint16_t raw[ADC_MAX_CH];
  uint16_t avg[ADC_MAX_CH];

  sampleRaw(raw);
  pushRing(raw);
  computeAvg(avg);

  const bool wantVolts = (_mode == 1 || _mode == 3);
  const bool wantAvg   = (_mode == 2 || _mode == 3);
  const uint16_t* src  = wantAvg ? avg : raw;

  // how many channels will this stream output?
  const ValuesStreamCfg& vs = _cfg.values[streamIdx];
  const bool useAll = (vs.selCount == 0);
  const uint8_t m = useAll ? _cfg.channelCount : vs.selCount;

  if (p.format() == UniProto::Format::BINARY) {
    // In binary mode we only support raw/avg RAW u16 fields to keep framing fixed.
    // (Floats are allowed in text/csv/plotter.)
    const uint16_t payloadLen = (uint16_t)(m * 2);
    w.begin(streamId, payloadLen);
    for (uint8_t k = 0; k < m; ++k) {
      const uint8_t ch = useAll ? k : vs.selIdx[k];
      w.u16(src[ch]);
    }
    w.end();
    return;
  }

  // CSV / Plotter / Text
  w.begin(streamId);
  if (wantVolts) {
    for (uint8_t k = 0; k < m; ++k) {
      const uint8_t ch = useAll ? k : vs.selIdx[k];
      w.f32(toVolts(src[ch]), nullptr, 3);
    }
  } else {
    for (uint8_t k = 0; k < m; ++k) {
      const uint8_t ch = useAll ? k : vs.selIdx[k];
      w.i32((int32_t)src[ch], nullptr);
    }
  }
  w.end();
}

void AdcModule::blockPushSample8() {
  if (_blockIdx >= ADC_BLOCK_LEN) return;

  const uint8_t ch = _cfg.block.sourceChanIdx;
  uint16_t v = (uint16_t)analogRead(_cfg.channels[ch]);

  // Convert to 8-bit for blocks (portable):
  // - AVR: 10-bit -> >>2
  // - RP2040: 12-bit -> >>4
  // Use adcMax to pick shift, but keep it cheap.
  uint8_t out8;
  if (_adcMax >= 4095) out8 = (uint8_t)(v >> 4);
  else                 out8 = (uint8_t)(v >> 2);

  _block[_blockIdx++] = out8;
}

void AdcModule::emitBlock(UniProto& p, uint8_t streamId, UniFrameWriter& w) {
  (void)streamId;

  // Blocks are binary-only
  if (p.format() != UniProto::Format::BINARY) return;

  uint32_t nowUs = micros();
  const uint32_t periodUs = 1000000UL / (uint32_t)_blockHz;

  // Fill block gradually without stalling the main loop too long
  uint8_t maxSamplesPerTick = 32;
  uint8_t n = 0;

  while (_blockIdx < ADC_BLOCK_LEN && n < maxSamplesPerTick) {
    if ((uint32_t)(nowUs - _lastBlockSampleUs) < periodUs) break;
    _lastBlockSampleUs += periodUs;
    blockPushSample8();
    n++;
    nowUs = micros();
  }

  if (_blockIdx >= ADC_BLOCK_LEN) {
    w.begin(_cfg.block.id, ADC_BLOCK_LEN);
    w.bytes(_block, ADC_BLOCK_LEN);
    w.end();
    _blockIdx = 0;
  }
}

// ---- Params ----
bool AdcModule::getMode(UniProto&, const char*, char* out,
                        size_t outLen, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  snprintf(out, outLen, "%u", (unsigned)m->_mode);
  return true;
}

bool AdcModule::setMode(UniProto&, const char*, const char* value, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  long v = UniProto::parseInt(value);
  if (v < 0) v = 0;
  if (v > 3) v = 3;
  m->_mode = (uint8_t)v;
  return true;
}

bool AdcModule::getVref(UniProto&, const char*, char* out,
                        size_t outLen, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
#if defined(ARDUINO_ARCH_AVR)
  dtostrf(m->_vref, 0, 3, out);
  (void)outLen;
#else
  snprintf(out, outLen, "%.3f", (double)m->_vref);
#endif
  return true;
}

bool AdcModule::setVref(UniProto&, const char*, const char* value, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  float v = UniProto::parseFloat(value);
  if (v < 0.1f) v = 0.1f;
  if (v > 20.0f) v = 20.0f;
  m->_vref = v;
  return true;
}

bool AdcModule::getWindow(UniProto&, const char*, char* out,
                          size_t outLen, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  snprintf(out, outLen, "%u", (unsigned)m->_win);
  return true;
}

bool AdcModule::setWindow(UniProto&, const char*, const char* value, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  long v = UniProto::parseInt(value);
  if (v < 1) v = 1;
  if (v > ADC_MAX_WIN) v = ADC_MAX_WIN;
  m->setAvgWindow((uint8_t)v);
  return true;
}

bool AdcModule::getBlockHz(UniProto&, const char*, char* out,
                           size_t outLen, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  snprintf(out, outLen, "%u", (unsigned)m->_blockHz);
  return true;
}

bool AdcModule::setBlockHz(UniProto&, const char*, const char* value, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  long v = UniProto::parseInt(value);
  if (v < 1) v = 1;
  if (v > 4000) v = 4000;
  m->setBlockSampleHz((uint16_t)v);
  return true;
}

// ---- Action ----
bool AdcModule::doBlockReset(UniProto&, const char*, const char*,
                             Stream& out, void* ctx) {
  AdcModule* m = (AdcModule*)ctx;
  m->_blockIdx = 0;
  out.println(F("adc.block_reset"));
  return true;
}
