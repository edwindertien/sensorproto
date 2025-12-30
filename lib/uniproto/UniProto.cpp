#include "UniProto.h"
#include "UniWriter.h"

// ---------- tiny helpers ----------
bool UniProto::streq(const char* a, const char* b) {
  while (*a && *b) if (*a++ != *b++) return false;
  return *a == 0 && *b == 0;
}
bool UniProto::startsWith(const char* s, const char* p) {
  while (*p) if (*s++ != *p++) return false;
  return true;
}
void UniProto::trimInPlace(char* s) {
  if (!s) return;

  // find first non-space
  char* start = s;
  while (*start == ' ' || *start == '\t' || *start == '\r' || *start == '\n') ++start;

  // find end
  char* end = start;
  while (*end) ++end;

  // trim trailing
  while (end > start && (end[-1] == ' ' || end[-1] == '\t' || end[-1] == '\r' || end[-1] == '\n')) --end;
  *end = '\0';

  // shift left within the same buffer if needed
  if (start != s) {
    char* dst = s;
    while (*start) *dst++ = *start++;
    *dst = '\0';
  }
}


// ---------- parsers ----------
long UniProto::parseInt(const char* s) {
  long sign = 1;
  if (*s == '-') { sign = -1; ++s; }
  long v = 0;
  while (*s >= '0' && *s <= '9') { v = v * 10 + (*s - '0'); ++s; }
  return v * sign;
}

// minimal float parser: [-]digits[.digits]
float UniProto::parseFloat(const char* s) {
  float sign = 1.0f;
  if (*s == '-') { sign = -1.0f; ++s; }
  long ip = 0;
  while (*s >= '0' && *s <= '9') { ip = ip * 10 + (*s - '0'); ++s; }
  float fp = 0.0f;
  float base = 1.0f;
  if (*s == '.') {
    ++s;
    while (*s >= '0' && *s <= '9') {
      fp = fp * 10.0f + (float)(*s - '0');
      base *= 10.0f;
      ++s;
    }
  }
  return sign * ((float)ip + fp / base);
}

// ---------- constructors ----------
UniProto::UniProto(Stream& io)
: _io(io),
  _deviceNameFlash(F("Device")),
  _deviceNameRam(nullptr),
  _csvW(*this, _io),
  _plotW(*this, _io),
  _txtW(*this, _io),
  _binW(*this, _io)
{}

UniProto::UniProto(Stream& io, const __FlashStringHelper* deviceName)
: _io(io),
  _deviceNameFlash(deviceName ? deviceName : F("Device")),
  _deviceNameRam(nullptr),
  _csvW(*this, _io),
  _plotW(*this, _io),
  _txtW(*this, _io),
  _binW(*this, _io)
{}

UniProto::UniProto(Stream& io, const char* deviceName)
: _io(io),
  _deviceNameFlash(nullptr),
  _deviceNameRam(deviceName ? deviceName : "Device"),
  _csvW(*this, _io),
  _plotW(*this, _io),
  _txtW(*this, _io),
  _binW(*this, _io)
{}

void UniProto::begin() {
  // nothing required yet
}

// ---------- registry ----------
bool UniProto::registerStream(const StreamDef& s) {
  if (_streamCount >= UNIPROTO_MAX_STREAMS) return false;
  _streams[_streamCount++] = s;
  return true;
}
bool UniProto::registerParam(const ParamDef& p) {
  if (_paramCount >= UNIPROTO_MAX_PARAMS) return false;
  _params[_paramCount++] = p;
  return true;
}
bool UniProto::registerAction(const ActionDef& a) {
  if (_actionCount >= UNIPROTO_MAX_ACTIONS) return false;
  _actions[_actionCount++] = a;
  return true;
}

// ---------- timing ----------
void UniProto::setRateHz(uint16_t hz) {
  if (hz < 1) hz = 1;
  if (hz > 500) hz = 500;
  _rateHz = hz;
}
bool UniProto::due(uint32_t nowUs) const {
  const uint32_t periodUs = (_rateHz == 0) ? 1000000UL : (1000000UL / (uint32_t)_rateHz);
  return (uint32_t)(nowUs - _lastEmitUs) >= periodUs;
}

// ---------- lookup ----------
int8_t UniProto::findStreamIndexById(uint8_t id) const {
  for (uint8_t i = 0; i < _streamCount; ++i) if (_streams[i].id == id) return (int8_t)i;
  return -1;
}
const UniProto::StreamDef* UniProto::findStreamById(uint8_t id) const {
  int8_t idx = findStreamIndexById(id);
  return (idx < 0) ? nullptr : &_streams[(uint8_t)idx];
}
const UniProto::ParamDef* UniProto::findParam(const char* key) const {
  for (uint8_t i = 0; i < _paramCount; ++i) if (streq(_params[i].key, key)) return &_params[i];
  return nullptr;
}
const UniProto::ActionDef* UniProto::findAction(const char* name) const {
  for (uint8_t i = 0; i < _actionCount; ++i) if (streq(_actions[i].name, name)) return &_actions[i];
  return nullptr;
}

// ---------- stream control ----------
void UniProto::streamOn(uint8_t id) {
  int8_t idx = findStreamIndexById(id);
  if (idx < 0) return;
  _activeMask |= (1u << (uint8_t)idx);
}
void UniProto::streamOff(uint8_t id) {
  int8_t idx = findStreamIndexById(id);
  if (idx < 0) return;
  _activeMask &= ~(1u << (uint8_t)idx);
}
void UniProto::streamOnly(uint8_t id) {
  _activeMask = 0;
  if (id) streamOn(id);
}
void UniProto::streamAllOff() {
  _activeMask = 0;
}
bool UniProto::streamEnabled(uint8_t id) const {
  int8_t idx = findStreamIndexById(id);
  if (idx < 0) return false;
  return (_activeMask & (1u << (uint8_t)idx)) != 0;
}

// ---------- output helpers ----------
void UniProto::writeTimePrefix(Stream& out) const {
  if (!_timestamp) return;
  const float t = millis() / 1000.0f;
  switch (_fmt) {
    case Format::CSV:
      out.print(t, 3); out.print(',');
      break;
    case Format::ARDUINO_PLOTTER:
      out.print(F("time:")); out.print(t, 3); out.print(',');
      break;
    case Format::TXT:
      out.print(F("[t=")); out.print(t, 3); out.print(F("] "));
      break;
    case Format::BINARY:
      break;
  }
}

void UniProto::binBegin(Stream& out, uint8_t streamId, uint16_t payloadLen, bool includeTimestamp) {
  out.write((uint8_t)0xAA);
  out.write((uint8_t)0x55);
  out.write(streamId);
  uint8_t flags = includeTimestamp ? 0x01 : 0x00;
  out.write(flags);
  out.write((uint8_t)(payloadLen & 0xFF));
  out.write((uint8_t)((payloadLen >> 8) & 0xFF));
  if (includeTimestamp) {
    uint32_t ms = millis();
    out.write((uint8_t*)&ms, sizeof(ms));
  }
}

// ---------- caps ----------
void UniProto::sendCaps(Stream& out) {
  out.print(F("{\"device\":\""));
  if (_deviceNameFlash) out.print(_deviceNameFlash);
  else out.print(_deviceNameRam);
  out.print(F("\",\"streams\":["));

  for (uint8_t i = 0; i < _streamCount; ++i) {
    out.print(F("{\"id\":")); out.print(_streams[i].id);
    out.print(F(",\"name\":\"")); out.print(_streams[i].name);
    out.print(F("\",\"schema\":\"")); out.print(_streams[i].schema);
    out.print(F("\",\"units\":\"")); out.print(_streams[i].units);
    out.print(F("\"}"));
    if (i + 1 < _streamCount) out.print(',');
  }

  out.print(F("],\"params\":["));
  for (uint8_t i = 0; i < _paramCount; ++i) {
    out.print('\"'); out.print(_params[i].key); out.print('\"');
    if (i + 1 < _paramCount) out.print(',');
  }

  // Core params are also queryable/settable:
  // rate, format, timestamp, stream
  if (_paramCount) out.print(',');
  out.print(F("\"rate\",\"format\",\"timestamp\",\"stream\""));

  out.print(F("],\"actions\":["));
  for (uint8_t i = 0; i < _actionCount; ++i) {
    out.print('\"'); out.print(_actions[i].name); out.print('\"');
    if (i + 1 < _actionCount) out.print(',');
  }

  out.print(F("],\"cmds\":[\"?\",\"?key\",\"!key:value\",\"@action[:args]\"]}"));
  out.println();
}

// ---------- streaming ----------
void UniProto::emitActiveStreams() {
  for (uint8_t i = 0; i < _streamCount; ++i) {
    if ((_activeMask & (1u << i)) == 0) continue;
    const StreamDef& s = _streams[i];
    if (!s.emit) continue;
    UniFrameWriter& w = writer();
    s.emit(*this, s.id, w, s.ctx);
  }
}

UniFrameWriter& UniProto::writer() {
  switch (_fmt) {
    case Format::CSV:             return _csvW;
    case Format::ARDUINO_PLOTTER: return _plotW;
    case Format::TXT:             return _txtW;
    case Format::BINARY:          return _binW;
    default:                      return _csvW;
  }
}

// ---------- command input ----------
void UniProto::pollInput() {
  while (_io.available()) {
    int c = _io.read();
    if (c < 0) break;
    if (c == '\r') continue;

    if (c == '\n') {
      _buf[_len] = '\0';
      if (_len) handleLine(_buf);
      _len = 0;
      continue;
    }
    if (_len < sizeof(_buf) - 1) _buf[_len++] = (char)c;
    else _len = 0;
  }
}

// helper: parse format from string
static bool parseFmt(const char* v, UniProto::Format& outFmt) {
  // manual string compare to avoid strcmp and private helpers
  if (v[0]=='t' && v[1]=='x' && v[2]=='t' && v[3]==0) {
    outFmt = UniProto::Format::TXT; return true;
  }
  if (v[0]=='c' && v[1]=='s' && v[2]=='v' && v[3]==0) {
    outFmt = UniProto::Format::CSV; return true;
  }
  if (v[0]=='a' && v[1]=='p' && v[2]==0) {
    outFmt = UniProto::Format::ARDUINO_PLOTTER; return true;
  }
  if (v[0]=='b' && v[1]=='i' && v[2]=='n' && v[3]==0) {
    outFmt = UniProto::Format::BINARY; return true;
  }
  return false;
}
// helper: print current format string
static void printFmt(Stream& out, UniProto::Format f) {
  switch (f) {
    case UniProto::Format::TXT: out.print(F("txt")); break;
    case UniProto::Format::CSV: out.print(F("csv")); break;
    case UniProto::Format::ARDUINO_PLOTTER: out.print(F("ap")); break;
    case UniProto::Format::BINARY: out.print(F("bin")); break;
  }
}

void UniProto::handleLine(const char* lineIn) {
  char* line = _buf;
  (void)lineIn;

  trimInPlace(line);
  if (*line == 0) return;

  // ---- CAPS ----
  if (streq(line, "?")) { sendCaps(_io); return; }

  // ---- GET ----
  if (*line == '?' && line[1] != '\0') {
    const char* key = line + 1;

    // Core GETs
    if (streq(key, "rate")) {
      _io.print(F("rate:")); _io.println((unsigned)_rateHz);
      return;
    }
    if (streq(key, "timestamp")) {
      _io.print(F("timestamp:")); _io.println(_timestamp ? 1 : 0);
      return;
    }
    if (streq(key, "format")) {
      _io.print(F("format:")); printFmt(_io, _fmt); _io.println();
      return;
    }
    if (streq(key, "stream")) {
      // report enabled stream IDs (comma list) or 0
      _io.print(F("stream:"));
      bool first = true;
      for (uint8_t i = 0; i < _streamCount; ++i) {
        if ((_activeMask & (1u << i)) == 0) continue;
        if (!first) _io.print(',');
        _io.print(_streams[i].id);
        first = false;
      }
      if (first) _io.print('0');
      _io.println();
      return;
    }

    // Param GET
    const ParamDef* pd = findParam(key);
    if (!pd || !pd->get) { _io.println(F("ERR no-such-param")); return; }
    char out[48];
    if (pd->get(*this, pd->key, out, sizeof(out), pd->ctx)) {
      _io.print(pd->key); _io.print(':');
      _io.println(out);
    } else {
      _io.println(F("ERR get-failed"));
    }
    return;
  }

  // ---- SET ----
  if (*line == '!') {
    // !key:value  (value may be empty -> treated as error)
    char* p = line + 1;
    if (*p == '\0') { _io.println(F("ERR set-missing-key")); return; }

    char* key = p;
    while (*p && *p != ':') ++p;
    if (*p != ':') { _io.println(F("ERR set-missing-colon")); return; }
    *p++ = '\0';
    const char* value = p;

    if (*key == '\0') { _io.println(F("ERR set-missing-key")); return; }

    // Core SETs
    if (streq(key, "rate")) {
      setRateHz((uint16_t)parseInt(value));
      _io.println(F("OK"));
      return;
    }
    if (streq(key, "timestamp")) {
      _timestamp = (parseInt(value) != 0);
      _io.println(F("OK"));
      return;
    }
    if (streq(key, "format")) {
      UniProto::Format nf;
      if (!parseFmt(value, nf)) { _io.println(F("ERR bad-format")); return; }
      _fmt = nf;
      _io.println(F("OK"));
      return;
    }
    if (streq(key, "stream")) {
      // !stream:0      -> all off
      // !stream:3      -> only 3
      // !stream:+3     -> on 3
      // !stream:-3     -> off 3
      if (*value == '\0') { _io.println(F("ERR set-missing-value")); return; }
      if (value[0] == '+') {
        uint8_t id = (uint8_t)parseInt(value + 1);
        streamOn(id);
        _io.println(F("OK"));
        return;
      }
      if (value[0] == '-') {
        uint8_t id = (uint8_t)parseInt(value + 1);
        streamOff(id);
        _io.println(F("OK"));
        return;
      }
      uint8_t id = (uint8_t)parseInt(value);
      if (id == 0) streamAllOff();
      else streamOnly(id);
      _io.println(F("OK"));
      return;
    }

    // Param SET
    const ParamDef* pd = findParam(key);
    if (!pd || !pd->set) { _io.println(F("ERR no-such-param")); return; }
    if (pd->set(*this, pd->key, value, pd->ctx)) _io.println(F("OK"));
    else _io.println(F("ERR set-failed"));
    return;
  }

  // ---- ACTION ----
  if (*line == '@') {
    // @name[:args]
    char* p = line + 1;
    if (*p == '\0') { _io.println(F("ERR no-such-action")); return; }

    char* name = p;
    while (*p && *p != ':') ++p;

    const char* args = "";
    if (*p == ':') { *p++ = '\0'; args = p; }

    const ActionDef* ad = findAction(name);
    if (!ad || !ad->fn) { _io.println(F("ERR no-such-action")); return; }

    if (ad->fn(*this, ad->name, args, _io, ad->ctx)) _io.println(F("OK"));
    else _io.println(F("ERR action-failed"));
    return;
  }

  _io.println(F("ERR unknown-cmd"));
}

void UniProto::tick() {
  pollInput();
  if (_activeMask == 0) return;
  uint32_t nowUs = micros();
  if (!due(nowUs)) return;
  _lastEmitUs = nowUs;
  emitActiveStreams();
}
