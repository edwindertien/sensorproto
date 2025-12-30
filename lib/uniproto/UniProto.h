#pragma once
#include <Arduino.h>
#include "UniWriter.h"

#ifndef UNIPROTO_MAX_STREAMS
#define UNIPROTO_MAX_STREAMS 8
#endif
#ifndef UNIPROTO_MAX_PARAMS
#define UNIPROTO_MAX_PARAMS 16
#endif
#ifndef UNIPROTO_MAX_ACTIONS
#define UNIPROTO_MAX_ACTIONS 8
#endif

// Command line buffer (tune for AVR RAM)
#ifndef UNIPROTO_CMD_BUF
  #if defined(ARDUINO_ARCH_AVR)
    #define UNIPROTO_CMD_BUF 64
  #else
    #define UNIPROTO_CMD_BUF 96
  #endif
#endif

class UniProto {
public:
  enum class Format : uint8_t { TXT, CSV, ARDUINO_PLOTTER, BINARY };

  // Streams emit via writer (formatting removed from modules)
  typedef void (*StreamEmitFn)(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);

  struct StreamDef {
    uint8_t id;
    const char* name;
    const char* schema;
    const char* units;
    StreamEmitFn emit;
    void* ctx;
  };

  enum class ParamType : uint8_t { BOOL, INT32, FLOAT };
  typedef bool (*ParamGetFn)(UniProto& p, const char* key, char* out, size_t outLen, void* ctx);
  typedef bool (*ParamSetFn)(UniProto& p, const char* key, const char* value, void* ctx);

  struct ParamDef {
    const char* key;
    ParamType type;
    ParamGetFn get;
    ParamSetFn set;
    void* ctx;
  };

  typedef bool (*ActionFn)(UniProto& p, const char* action, const char* args, Stream& out, void* ctx);
  struct ActionDef {
    const char* name;
    ActionFn fn;
    void* ctx;
  };

  // Constructors (AVR-safe: no F() in default args or global initializers needed)
  explicit UniProto(Stream& io);
  explicit UniProto(Stream& io, const __FlashStringHelper* deviceName);
  explicit UniProto(Stream& io, const char* deviceName);

  void begin();

  bool registerStream(const StreamDef& s);
  bool registerParam(const ParamDef& p);
  bool registerAction(const ActionDef& a);

  void tick();

  void setRateHz(uint16_t hz);
  uint16_t rateHz() const { return _rateHz; }

  void setTimestamp(bool on) { _timestamp = on; }
  bool timestamp() const { return _timestamp; }

  void setFormat(Format f) { _fmt = f; }
  Format format() const { return _fmt; }

  void streamOn(uint8_t id);
  void streamOff(uint8_t id);
  void streamOnly(uint8_t id);
  void streamAllOff();
  bool streamEnabled(uint8_t id) const;

  void writeTimePrefix(Stream& out) const;

  // Binary frame header helper (fixed-order fields, no keys)
  void binBegin(Stream& out, uint8_t streamId, uint16_t payloadLen, bool includeTimestamp);

  // Access writer for current format
  UniFrameWriter& writer();

  void sendCaps(Stream& out);

  static float parseFloat(const char* s);
  static long  parseInt(const char* s);

  Stream& io() { return _io; } // sometimes handy for actions/debug

private:
  Stream& _io;

  // Device name can be either flash or RAM (AVR-safe)
  const __FlashStringHelper* _deviceNameFlash = nullptr;
  const char* _deviceNameRam = nullptr;

  StreamDef _streams[UNIPROTO_MAX_STREAMS];
  uint8_t _streamCount = 0;

  ParamDef _params[UNIPROTO_MAX_PARAMS];
  uint8_t _paramCount = 0;

  ActionDef _actions[UNIPROTO_MAX_ACTIONS];
  uint8_t _actionCount = 0;

  uint16_t _activeMask = 0;

  uint16_t _rateHz = 50;
  uint32_t _lastEmitUs = 0;

  bool _timestamp = false;
  Format _fmt = Format::CSV;

  char _buf[UNIPROTO_CMD_BUF];
  uint8_t _len = 0;

  // Writers (no heap)
  UniCsvWriter     _csvW;
  UniPlotterWriter _plotW;
  UniTextWriter    _txtW;
  UniBinaryWriter  _binW;

  void pollInput();
  void handleLine(const char* line);
  void emitActiveStreams();

  int8_t findStreamIndexById(uint8_t id) const;
  const StreamDef* findStreamById(uint8_t id) const;

  const ParamDef* findParam(const char* key) const;
  const ActionDef* findAction(const char* name) const;

  bool due(uint32_t nowUs) const;

  static bool streq(const char* a, const char* b);
  static bool startsWith(const char* s, const char* p);
  static void trimInPlace(char* s);
};
