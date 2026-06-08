#pragma once
#include <Arduino.h>
#include "UniProto.h"

// ADNS-2610 picture is 18x18 = 324 pixels (6-bit grayscale in bits 5..0).
#ifndef ADNS2610_FRAME_W
  #define ADNS2610_FRAME_W 18
#endif
#ifndef ADNS2610_FRAME_H
  #define ADNS2610_FRAME_H 18
#endif
#ifndef ADNS2610_FRAME_PIXELS
  #define ADNS2610_FRAME_PIXELS (ADNS2610_FRAME_W * ADNS2610_FRAME_H)
#endif

// How many pixels to send per tick (chunk size). Tune for serial bandwidth / latency.
#ifndef ADNS2610_CHUNK_PIXELS
  #if defined(ARDUINO_ARCH_AVR)
    #define ADNS2610_CHUNK_PIXELS 54
  #else
    #define ADNS2610_CHUNK_PIXELS 108
  #endif
#endif

class Adns2610Module {
public:
  struct Config {
    // Motion stream (dx, dy)
    uint8_t streamMotionId = 6;
    const char* streamMotionName = "adns.motion";
    const char* motionSchema = "i32,i32";     // dx, dy
    const char* motionUnits  = "counts";

    // Frame stream (chunked grayscale)
    uint8_t streamFrameId = 7;
    const char* streamFrameName = "adns.frame";
    // Header + bytes:
    // u16 frame_id, u16 w, u16 h, u16 offset, u16 count, bytes[count]
    const char* frameSchema = "u16,u16,u16,u16,u16,bytes";
    const char* frameUnits  = "id,w,h,px,px,gray6";

    // Pins (bit-banged serial)
    uint8_t pinSclk = A5;
    uint8_t pinSdio = A4;

    // Timing (based on your old sketch)
    uint16_t tHoldUs = 100;
    uint16_t tPostUs = 100;
    uint16_t resyncMs = 1000;

    // Boot behavior
    bool ledOnBoot = true;

    // Streaming behavior
    bool enableMotionStream = true;
    bool allowFrame = true;
  };

  static Config defaultUno() { return Config{}; }

  explicit Adns2610Module(const Config& cfg);

  void registerWith(UniProto& proto);

private:
  // Register map (from your sketch)
  static constexpr uint8_t REG_CONFIG      = 0x00;
  static constexpr uint8_t REG_STATUS      = 0x01;
  static constexpr uint8_t REG_DELTA_Y     = 0x02;
  static constexpr uint8_t REG_DELTA_X     = 0x03;
  static constexpr uint8_t REG_SQUAL       = 0x04;
  static constexpr uint8_t REG_MAX_PIXEL   = 0x05;
  static constexpr uint8_t REG_MIN_PIXEL   = 0x06;
  static constexpr uint8_t REG_PIXEL_SUM   = 0x07;
  static constexpr uint8_t REG_PICTURE     = 0x08;
  static constexpr uint8_t REG_SHUTTER_MSB = 0x09;
  static constexpr uint8_t REG_SHUTTER_LSB = 0x0A;

  Config _cfg;
  bool _initialized = false;

  // cached diagnostics (available via params)
  int8_t  _dxLast = 0;
  int8_t  _dyLast = 0;
  uint8_t _squalLast = 0;
  uint8_t _maxPixLast = 0;
  uint8_t _minPixLast = 0;
  uint8_t _pixSumLast = 0;
  uint16_t _shutterLast = 0;
  uint8_t _statusLast = 0;

  // frame state
  uint8_t  _pixels[ADNS2610_FRAME_PIXELS] = {};
  bool     _framePending = false;     // captured and waiting to stream
  uint16_t _frameId = 0;
  uint16_t _frameOffset = 0;

  // stream emitters
  static void emitMotionFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);
  static void emitFrameFn (UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);
  void emitMotion(UniProto& p, uint8_t streamId, UniFrameWriter& w);
  void emitFrame (UniProto& p, uint8_t streamId, UniFrameWriter& w);

  // params
  static bool getParam(UniProto& p, const char* key, char* out, size_t outLen, void* ctx);
  static bool setParam(UniProto& p, const char* key, const char* value, void* ctx);

  // sensor ops
  void beginIfNeeded();
  void reSync();
  void forceAwake(bool on);

  uint8_t  readRegister(uint8_t address);
  void     writeRegister(uint8_t address, uint8_t data);

  int8_t   readDx();
  int8_t   readDy();
  uint16_t readShutter();

  bool captureFrame(); // blocking capture, fills _pixels[] with 0..63 values
};
