#pragma once
#include <Arduino.h>
#include "UniProto.h"
/// you can configure the streams (or overwrite the default) from main.cpp: 
// at the top you do:
// 
// AdcModule* adc = nullptr;
// instead of AdcModule adc(AdcModule::defaultUno());
//
// and in setup you do:
//
// // 1) Start from defaults
//   auto cfg = AdcModule::defaultUno();

//   // 2) Optional tweaks (example)
//   cfg.valuesCount = 2;

//   cfg.values[1].id = 3;
//   cfg.values[1].name = "adc.sel";
//   cfg.values[1].selCount = 3;
//   cfg.values[1].selIdx[0] = 0; // A0
//   cfg.values[1].selIdx[1] = 3; // A3
//   cfg.values[1].selIdx[2] = 5; // A5

//   cfg.block.sourceChanIdx = 2; // A2

//   // 3) Construct module with final config
//   static AdcModule adcInst(cfg);
//   adc = &adcInst;

//   // 4) Register streams/params/actions
//   adc->registerWith(proto);




// ---- Memory sizing (override via build_flags if desired) ----
#ifndef ADC_MAX_CH
  #if defined(ARDUINO_ARCH_AVR)
    #define ADC_MAX_CH 6   // Uno: A0..A5
  #elif defined(ARDUINO_ARCH_RP2040)
    #define ADC_MAX_CH 3   // Pico: ADC0..2 (A0..A2 = GPIO26..28)
  #else
    #define ADC_MAX_CH 8
  #endif
#endif

#ifndef ADC_MAX_WIN
  #if defined(ARDUINO_ARCH_AVR)
    #define ADC_MAX_WIN 10
  #else
    #define ADC_MAX_WIN 16
  #endif
#endif

#ifndef ADC_BLOCK_LEN
  #if defined(ARDUINO_ARCH_AVR)
    #define ADC_BLOCK_LEN 300
  #else
    #define ADC_BLOCK_LEN 500
  #endif
#endif

#ifndef ADC_MAX_VALUE_STREAMS
  #define ADC_MAX_VALUE_STREAMS 3
#endif

class AdcModule {
public:
  // A values stream can output any subset of channels (fixed order).
  // The subset is defined by "selIdx[]" indices into Config::channels[].
  struct ValuesStreamCfg {
    uint8_t id = 1;
    const char* name = "adc";
    const char* schema = "u16[m] or f32[m]";
    const char* units  = "raw or V";

    uint8_t selIdx[ADC_MAX_CH] = {0}; // indices into channels[]
    uint8_t selCount = 0;             // 0 => use all channels
  };

  struct BlockStreamCfg {
    uint8_t id = 2;
    const char* name = "adc.block";
    const char* schema = "u8[block]";
    const char* units  = "raw8";

    // which channel to sample into the byte block: index into channels[]
    uint8_t sourceChanIdx = 0;

    uint16_t sampleHz = 500;
  };

  struct Config {
    // Physical channels (pins)
    uint8_t channels[ADC_MAX_CH] = {A0, A1, A2};
    uint8_t channelCount = 3;

    // Conversion
    float vref = 5.0f;
    uint16_t adcMax = 1023;

    // Filtering
    uint8_t avgWindow = 10;

    // Streams
    ValuesStreamCfg values[ADC_MAX_VALUE_STREAMS];
    uint8_t valuesCount = 1;

    BlockStreamCfg block;
  };

  // ---- Defaults ----
  static Config defaultUno() {
    Config c;
    // A0..A5
    c.channels[0] = A0; c.channels[1] = A1; c.channels[2] = A2;
    c.channels[3] = A3; c.channels[4] = A4; c.channels[5] = A5;
    c.channelCount = 6;

    c.vref = 5.0f;
    c.adcMax = 1023;
    c.avgWindow = 10;

    // Stream 1: all channels
    c.valuesCount = 1;
    c.values[0].id = 1;
    c.values[0].name = "adc.all";
    c.values[0].schema = "u16[n] or f32[n]";
    c.values[0].units = "raw or V";
    c.values[0].selCount = 0; // 0 => all

    // Block stream: channel 0 (A0) by default
    c.block.id = 2;
    c.block.name = "adc.block";
    c.block.schema = "u8[block]";
    c.block.units = "raw8";
    c.block.sourceChanIdx = 0;
    c.block.sampleHz = 500;

    return c;
  }

  static Config defaultPico() {
    Config c;
    // Earle Philhower RP2040 core: A0..A2 map to GPIO26..28
    c.channels[0] = A0; c.channels[1] = A1; c.channels[2] = A2;
    c.channelCount = 3;

    c.vref = 3.3f;
    c.adcMax = 4095; // RP2040 ADC is 12-bit (returned as 0..4095 in that core)
    c.avgWindow = 10;

    c.valuesCount = 1;
    c.values[0].id = 1;
    c.values[0].name = "adc.all";
    c.values[0].schema = "u16[n] or f32[n]";
    c.values[0].units = "raw or V";
    c.values[0].selCount = 0;

    c.block.id = 2;
    c.block.name = "adc.block";
    c.block.schema = "u8[block]";
    c.block.units = "raw8";
    c.block.sourceChanIdx = 0;
    c.block.sampleHz = 1000;

    return c;
  }

  explicit AdcModule(const Config& cfg);

  void registerWith(UniProto& proto);

private:
  Config _cfg;

  // modes:
  // 0 raw (u16)
  // 1 volts (f32)
  // 2 avg raw (u16)
  // 3 avg volts (f32)
  uint8_t  _mode = 0;
  float    _vref = 5.0f;
  uint16_t _adcMax = 1023;
  uint8_t  _win = 10;

  // ring for averaging (platform-sized)
  uint16_t _ring[ADC_MAX_WIN][ADC_MAX_CH] = {};
  uint8_t _pos = 0;
  uint8_t _fill = 0;

  // block buffer
  uint8_t  _block[ADC_BLOCK_LEN];
  uint16_t _blockIdx = 0;
  uint16_t _blockHz = 500;
  uint32_t _lastBlockSampleUs = 0;

  // stream emitters
  static void emitValuesFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);
  static void emitBlockFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);

  void emitValues(UniProto& p, uint8_t streamId, UniFrameWriter& w);
  void emitBlock(UniProto& p, uint8_t streamId, UniFrameWriter& w);

  // params/actions
  static bool getMode(UniProto&, const char*, char* out, size_t outLen, void* ctx);
  static bool setMode(UniProto&, const char*, const char* value, void* ctx);

  static bool getVref(UniProto&, const char*, char* out, size_t outLen, void* ctx);
  static bool setVref(UniProto&, const char*, const char* value, void* ctx);

  static bool getWindow(UniProto&, const char*, char* out, size_t outLen, void* ctx);
  static bool setWindow(UniProto&, const char*, const char* value, void* ctx);

  static bool getBlockHz(UniProto&, const char*, char* out, size_t outLen, void* ctx);
  static bool setBlockHz(UniProto&, const char*, const char* value, void* ctx);

  static bool doBlockReset(UniProto&, const char*, const char*, Stream& out, void* ctx);

  // helpers
  void setAvgWindow(uint8_t w);
  void setBlockSampleHz(uint16_t hz);

  void sampleRaw(uint16_t* raw);
  void pushRing(const uint16_t* raw);
  void computeAvg(uint16_t* avg) const;

  float toVolts(uint16_t raw) const { return ((float)raw * _vref) / (float)_adcMax; }

  bool blockDue(uint32_t nowUs) const;
  void blockPushSample8();

  // selection helpers
  uint8_t findValuesStreamIndexById(uint8_t streamId) const;
  void emitSelected(const uint16_t* rawOrAvg, uint8_t streamIdx, UniFrameWriter& w, bool asVolts);
};
