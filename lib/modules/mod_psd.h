#pragma once
#include <Arduino.h>
#include "UniProto.h"

// Averaging window cap (override via build_flags)
#ifndef PSD_MAX_WIN
  #if defined(ARDUINO_ARCH_AVR)
    #define PSD_MAX_WIN 10
  #else
    #define PSD_MAX_WIN 16
  #endif
#endif

class PsdModule {
public:
  struct Config {
    // Stream
    uint8_t streamId = 5;
    const char* streamName = "psd";
    const char* schema = "u16 | f32";
    const char* units  = "raw | V | cm";

    // Hardware
    uint8_t pin = A0;

    // ADC conversion
    float vref = 5.0f;
    uint16_t adcMax = 1023;

    // Averaging
    uint8_t avgWindow = 10;

    // Calibration (inverse model): cm = A / (V - B)
    // Defaults approximate for GP2Y0A710K0F.
    float calA = 137.5f;
    float calB = 1.125f;

    // Clamp output (recommended)
    float cmMin = 100.0f;
    float cmMax = 550.0f;
  };

  static Config defaultUnoA0() { return Config{}; }

  explicit PsdModule(const Config& cfg);

  void registerWith(UniProto& proto);

private:
  Config _cfg;

  // modes:
  // 0 raw (u16)
  // 1 volts (f32)
  // 2 avg raw (u16)
  // 3 avg volts (f32)
  // 4 cm (f32)
  // 5 avg cm (f32)
  uint8_t _mode = 0;

  float _vref;
  uint16_t _adcMax;

  uint8_t _win;
  uint16_t _ring[PSD_MAX_WIN] = {};
  uint8_t _pos = 0;
  uint8_t _fill = 0;

  // calibration
  float _calA;
  float _calB;
  float _cmMin;
  float _cmMax;

  // stream emitter
  static void emitFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);
  void emit(UniProto& p, uint8_t streamId, UniFrameWriter& w);

  // params
  static bool getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx);
  static bool setParam(UniProto&, const char* key, const char* value, void* ctx);

  // helpers
  void setAvgWindow(uint8_t w);
  uint16_t sampleRaw();
  void pushRing(uint16_t raw);
  uint16_t avgRaw() const;

  float toVolts(uint16_t raw) const { return ((float)raw * _vref) / (float)_adcMax; }
  float voltsToCm(float v) const;
};
