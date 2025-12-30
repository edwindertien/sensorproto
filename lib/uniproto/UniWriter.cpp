#include "UniWriter.h"
#include "UniProto.h"

// ---- CSV ----
void UniCsvWriter::begin(uint8_t, uint16_t) {
  _first = true;
  _p.writeTimePrefix(_out);
}
void UniCsvWriter::u16(uint16_t v, const char*) {
  if (!_first) _out.print(',');
  _out.print(v);
  _first = false;
}
void UniCsvWriter::i32(int32_t v, const char*) {
  if (!_first) _out.print(',');
  _out.print(v);
  _first = false;
}
void UniCsvWriter::f32(float v, const char*, uint8_t decimals) {
  if (!_first) _out.print(',');
  _out.print(v, decimals);
  _first = false;
}
void UniCsvWriter::bytes(const uint8_t*, uint16_t) {
  // CSV is not for blocks; ignore to keep output sane
}
void UniCsvWriter::end() {
  _out.println();
}

// ---- Plotter (key:value,...) ----
void UniPlotterWriter::begin(uint8_t, uint16_t) {
  _first = true;
  _fieldIndex = 0;
  if (_p.timestamp()) _p.writeTimePrefix(_out); // prints time:...,
}

static inline void plotterFieldName(Stream& out, const char* key, uint8_t idx) {
  if (key && *key) {
    out.print(key);
  } else {
    out.print('f');
    out.print(idx);
  }
}

void UniPlotterWriter::u16(uint16_t v, const char* key) {
  if (!_first) _out.print(',');
  plotterFieldName(_out, key, _fieldIndex++);
  _out.print(':'); _out.print(v);
  _first = false;
}
void UniPlotterWriter::i32(int32_t v, const char* key) {
  if (!_first) _out.print(',');
  plotterFieldName(_out, key, _fieldIndex++);
  _out.print(':'); _out.print(v);
  _first = false;
}
void UniPlotterWriter::f32(float v, const char* key, uint8_t decimals) {
  if (!_first) _out.print(',');
  plotterFieldName(_out, key, _fieldIndex++);
  _out.print(':'); _out.print(v, decimals);
  _first = false;
}
void UniPlotterWriter::bytes(const uint8_t*, uint16_t) {
  // plotter is not for blocks
}
void UniPlotterWriter::end() {
  _out.println();
}

// ---- Text (debug) ----
void UniTextWriter::begin(uint8_t, uint16_t) {
  _first = true;
  _fieldIndex = 0;
  _p.writeTimePrefix(_out);
  _out.print('{');
}
void UniTextWriter::u16(uint16_t v, const char* key) {
  if (!_first) _out.print(',');
  if (key && *key) { _out.print(key); _out.print('='); }
  _out.print(v);
  _first = false;
  _fieldIndex++;
}
void UniTextWriter::i32(int32_t v, const char* key) {
  if (!_first) _out.print(',');
  if (key && *key) { _out.print(key); _out.print('='); }
  _out.print(v);
  _first = false;
  _fieldIndex++;
}
void UniTextWriter::f32(float v, const char* key, uint8_t decimals) {
  if (!_first) _out.print(',');
  if (key && *key) { _out.print(key); _out.print('='); }
  _out.print(v, decimals);
  _first = false;
  _fieldIndex++;
}
void UniTextWriter::bytes(const uint8_t*, uint16_t) {
  // keep debug readable
}
void UniTextWriter::end() {
  _out.println('}');
}

// ---- Binary (fixed-order, no keys) ----
void UniBinaryWriter::begin(uint8_t streamId, uint16_t payloadLen) {
  _begun = false;
  _expected = payloadLen;
  _written = 0;

  if (payloadLen == 0) {
    // must be provided in fixed-length framing
    return;
  }
  _p.binBegin(_out, streamId, payloadLen, _p.timestamp());
  _begun = true;
}

void UniBinaryWriter::u16(uint16_t v, const char*) {
  if (!_begun) return;
  if (_written + 2 > _expected) return;
  _out.write((uint8_t*)&v, 2);
  _written += 2;
}
void UniBinaryWriter::i32(int32_t v, const char*) {
  if (!_begun) return;
  if (_written + 4 > _expected) return;
  _out.write((uint8_t*)&v, 4);
  _written += 4;
}
void UniBinaryWriter::f32(float v, const char*, uint8_t) {
  if (!_begun) return;
  if (_written + 4 > _expected) return;
  _out.write((uint8_t*)&v, 4);
  _written += 4;
}
void UniBinaryWriter::bytes(const uint8_t* data, uint16_t n) {
  if (!_begun) return;
  if (_written + n > _expected) return;
  _out.write(data, n);
  _written += n;
}
void UniBinaryWriter::end() {
  // optionally enforce _written==_expected
}
