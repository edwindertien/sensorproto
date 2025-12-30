#pragma once
#include <Arduino.h>

class UniProto;

// Minimal writer used by stream modules.
// - Keys are optional; CSV/BIN ignore them, Plotter uses them.
class UniFrameWriter {
public:
  // Note: no virtual destructor to keep AVR footprint smaller.
  // Writers are not deleted polymorphically; they live as UniProto members.
  ~UniFrameWriter() {}

  // payloadLen is required for BINARY (so the header can be written correctly).
  virtual void begin(uint8_t streamId, uint16_t payloadLen = 0) = 0;

  // Fixed-order fields (no keys needed). If key is provided, only Plotter/Text may use it.
  virtual void u16(uint16_t v, const char* key = nullptr) = 0;
  virtual void i32(int32_t v, const char* key = nullptr) = 0;
  virtual void f32(float v, const char* key = nullptr, uint8_t decimals = 3) = 0;

  // Raw bytes payload (blocks)
  virtual void bytes(const uint8_t* data, uint16_t n) = 0;

  virtual void end() = 0;
};

// Concrete writers
class UniCsvWriter : public UniFrameWriter {
public:
  UniCsvWriter(UniProto& p, Stream& out) : _p(p), _out(out) {}
  void begin(uint8_t streamId, uint16_t payloadLen = 0) override;
  void u16(uint16_t v, const char* key = nullptr) override;
  void i32(int32_t v, const char* key = nullptr) override;
  void f32(float v, const char* key = nullptr, uint8_t decimals = 3) override;
  void bytes(const uint8_t* data, uint16_t n) override;
  void end() override;

private:
  UniProto& _p;
  Stream& _out;
  bool _first = true;
};

class UniPlotterWriter : public UniFrameWriter {
public:
  UniPlotterWriter(UniProto& p, Stream& out) : _p(p), _out(out) {}
  void begin(uint8_t streamId, uint16_t payloadLen = 0) override;
  void u16(uint16_t v, const char* key = nullptr) override;
  void i32(int32_t v, const char* key = nullptr) override;
  void f32(float v, const char* key = nullptr, uint8_t decimals = 3) override;
  void bytes(const uint8_t* data, uint16_t n) override;
  void end() override;

private:
  UniProto& _p;
  Stream& _out;
  bool _first = true;
  uint8_t _fieldIndex = 0;
};

class UniTextWriter : public UniFrameWriter {
public:
  UniTextWriter(UniProto& p, Stream& out) : _p(p), _out(out) {}
  void begin(uint8_t streamId, uint16_t payloadLen = 0) override;
  void u16(uint16_t v, const char* key = nullptr) override;
  void i32(int32_t v, const char* key = nullptr) override;
  void f32(float v, const char* key = nullptr, uint8_t decimals = 3) override;
  void bytes(const uint8_t* data, uint16_t n) override;
  void end() override;

private:
  UniProto& _p;
  Stream& _out;
  bool _first = true;
  uint8_t _fieldIndex = 0;
};

class UniBinaryWriter : public UniFrameWriter {
public:
  UniBinaryWriter(UniProto& p, Stream& out) : _p(p), _out(out) {}
  void begin(uint8_t streamId, uint16_t payloadLen = 0) override;
  void u16(uint16_t v, const char* key = nullptr) override;
  void i32(int32_t v, const char* key = nullptr) override;
  void f32(float v, const char* key = nullptr, uint8_t decimals = 3) override;
  void bytes(const uint8_t* data, uint16_t n) override;
  void end() override;

private:
  UniProto& _p;
  Stream& _out;
  bool _begun = false;
  uint16_t _expected = 0;
  uint16_t _written = 0;
};
