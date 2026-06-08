#include "mod_adns2610.h"
#include <stdio.h>

Adns2610Module::Adns2610Module(const Config& cfg)
: _cfg(cfg) {}

void Adns2610Module::registerWith(UniProto& proto) {
  proto.registerStream({
    _cfg.streamMotionId,
    _cfg.streamMotionName,
    _cfg.motionSchema,
    _cfg.motionUnits,
    &Adns2610Module::emitMotionFn,
    this
  });

  proto.registerStream({
    _cfg.streamFrameId,
    _cfg.streamFrameName,
    _cfg.frameSchema,
    _cfg.frameUnits,
    &Adns2610Module::emitFrameFn,
    this
  });

  // Controls
  proto.registerParam({"adns.led",         UniProto::ParamType::BOOL,  &getParam, &setParam, this});
  proto.registerParam({"adns.capture",     UniProto::ParamType::BOOL,  &getParam, &setParam, this});
  proto.registerParam({"adns.motion_on",   UniProto::ParamType::BOOL,  &getParam, &setParam, this});
  proto.registerParam({"adns.resync",      UniProto::ParamType::BOOL,  &getParam, &setParam, this});

  // Diagnostics (read-only)
  proto.registerParam({"adns.dx",          UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.dy",          UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.squal",       UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.maxpix",      UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.minpix",      UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.pixsum",      UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.shutter",     UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.status",      UniProto::ParamType::INT32, &getParam, &setParam, this});

  // Capabilities
  proto.registerParam({"adns.w",           UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.h",           UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"adns.chunk_px",    UniProto::ParamType::INT32, &getParam, &setParam, this});
}

void Adns2610Module::beginIfNeeded() {
  if (_initialized) return;

  pinMode(_cfg.pinSclk, OUTPUT);
  digitalWrite(_cfg.pinSclk, HIGH);

  pinMode(_cfg.pinSdio, INPUT); // idle

  reSync();
  forceAwake(_cfg.ledOnBoot);

  _initialized = true;
}

void Adns2610Module::reSync() {
  // from your sketch
  digitalWrite(_cfg.pinSclk, HIGH);
  delayMicroseconds(5);
  digitalWrite(_cfg.pinSclk, LOW);
  delayMicroseconds(1);
  digitalWrite(_cfg.pinSclk, HIGH);
  delay(_cfg.resyncMs);
}

void Adns2610Module::forceAwake(bool on) {
  writeRegister(REG_CONFIG, on ? 0x01 : 0x00);
}

uint8_t Adns2610Module::readRegister(uint8_t address) {
  uint8_t r = 0;

  // Address phase
  pinMode(_cfg.pinSdio, OUTPUT);
  for (int i = 7; i >= 0; i--) {
    digitalWrite(_cfg.pinSclk, LOW);
    digitalWrite(_cfg.pinSdio, (address & (1 << i)) ? HIGH : LOW);
    digitalWrite(_cfg.pinSclk, HIGH);
  }

  // Data phase
  pinMode(_cfg.pinSdio, INPUT);
  delayMicroseconds(_cfg.tHoldUs);

  for (int i = 7; i >= 0; i--) {
    digitalWrite(_cfg.pinSclk, LOW);
    digitalWrite(_cfg.pinSclk, HIGH);
    r |= (digitalRead(_cfg.pinSdio) ? 1 : 0) << i;
  }

  delayMicroseconds(_cfg.tPostUs);
  return r;
}

void Adns2610Module::writeRegister(uint8_t address, uint8_t data) {
  // MSB high indicates write
  address |= 0x80;

  pinMode(_cfg.pinSdio, OUTPUT);

  // Address
  for (int i = 7; i >= 0; i--) {
    digitalWrite(_cfg.pinSclk, LOW);
    digitalWrite(_cfg.pinSdio, (address & (1 << i)) ? HIGH : LOW);
    digitalWrite(_cfg.pinSclk, HIGH);
  }

  // Data
  for (int i = 7; i >= 0; i--) {
    digitalWrite(_cfg.pinSclk, LOW);
    digitalWrite(_cfg.pinSdio, (data & (1 << i)) ? HIGH : LOW);
    digitalWrite(_cfg.pinSclk, HIGH);
  }

  // Return to idle input
  pinMode(_cfg.pinSdio, INPUT);
}

int8_t Adns2610Module::readDx() { return (int8_t)readRegister(REG_DELTA_X); }
int8_t Adns2610Module::readDy() { return (int8_t)readRegister(REG_DELTA_Y); }

uint16_t Adns2610Module::readShutter() {
  uint16_t msb = (uint16_t)readRegister(REG_SHUTTER_MSB);
  uint16_t lsb = (uint16_t)readRegister(REG_SHUTTER_LSB);
  return (msb << 8) | lsb;
}

bool Adns2610Module::captureFrame() {
  if (!_cfg.allowFrame) return false;

  // Recommended: forced awake during capture
  forceAwake(true);

  // Arm/reset pixel grabber: any write resets pixel hardware
  writeRegister(REG_PICTURE, 0);

  // Wait for the first valid pixel (and then each next one)
  // One valid pixel per sensor frame => must wait up to ~1ms typical.
  const uint16_t perPixelTimeoutUs = 3000; // generous (3ms) for slow/blocked cases

  for (uint16_t i = 0; i < ADNS2610_FRAME_PIXELS; i++) {
    uint32_t t0 = micros();
    uint8_t pix;

    while (true) {
      pix = readRegister(REG_PICTURE);

      if (pix & 0x40) { // Data_Valid bit
        _pixels[i] = (uint8_t)(pix & 0x3F);  // 6-bit grayscale
        break;
      }

      // small wait so we don't hammer the bus pointlessly
      delayMicroseconds(80);

      if ((uint32_t)(micros() - t0) > perPixelTimeoutUs) {
        // capture failed mid-frame
        return false;
      }
    }
  }

  // optional: restore LED state
  forceAwake(_cfg.ledOnBoot);

  return true;
}

// ---- Stream emitters ----
void Adns2610Module::emitMotionFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx) {
  (void)streamId;
  ((Adns2610Module*)ctx)->emitMotion(p, ((Adns2610Module*)ctx)->_cfg.streamMotionId, w);
}

void Adns2610Module::emitFrameFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx) {
  (void)streamId;
  ((Adns2610Module*)ctx)->emitFrame(p, ((Adns2610Module*)ctx)->_cfg.streamFrameId, w);
}

void Adns2610Module::emitMotion(UniProto& p, uint8_t streamId, UniFrameWriter& w) {
  beginIfNeeded();
  if (!_cfg.enableMotionStream) return;

  _dxLast = readDx();
  _dyLast = readDy();

  // update cached diagnostics (cheap ones only every tick)
  _squalLast  = readRegister(REG_SQUAL);
  _maxPixLast = readRegister(REG_MAX_PIXEL);
  _minPixLast = readRegister(REG_MIN_PIXEL);
  _pixSumLast = readRegister(REG_PIXEL_SUM);
  _shutterLast = readShutter();
  _statusLast  = readRegister(REG_STATUS);

  // CSV/TXT/PLOTTER: just dx,dy as i32
  if (p.format() != UniProto::Format::BINARY) {
    w.begin(streamId);
    w.i32((int32_t)_dxLast, "dx");
    w.i32((int32_t)_dyLast, "dy");
    w.end();
    return;
  }

  // BINARY: compact 2-byte payload [dx,dy]
  // (BinaryWriter will frame it using payloadLen)
  uint8_t payload[2];
  payload[0] = (uint8_t)_dxLast;
  payload[1] = (uint8_t)_dyLast;

  w.begin(streamId, 2);
  w.bytes(payload, 2);
  w.end();
}

void Adns2610Module::emitFrame(UniProto& p, uint8_t streamId, UniFrameWriter& w) {
  beginIfNeeded();
  if (!_cfg.allowFrame) return;
  if (!_framePending) return;

  const uint16_t remaining = (uint16_t)(ADNS2610_FRAME_PIXELS - _frameOffset);
  uint16_t count = remaining;
  if (count > (uint16_t)ADNS2610_CHUNK_PIXELS) count = (uint16_t)ADNS2610_CHUNK_PIXELS;
  if (count == 0) {
    _framePending = false;
    _frameOffset = 0;
    return;
  }

  // Header: 5*u16 = 10 bytes, then count bytes
  const uint16_t payloadLen = (uint16_t)(10 + count);

  if (p.format() == UniProto::Format::BINARY) {
    w.begin(streamId, payloadLen);
  } else {
    w.begin(streamId);
  }

  w.u16(_frameId, "id");
  w.u16(ADNS2610_FRAME_W, "w");
  w.u16(ADNS2610_FRAME_H, "h");
  w.u16(_frameOffset, "off");
  w.u16(count, "n");

  w.bytes(&_pixels[_frameOffset], count);
  w.end();

  _frameOffset = (uint16_t)(_frameOffset + count);
  if (_frameOffset >= ADNS2610_FRAME_PIXELS) {
    _framePending = false;
    _frameOffset = 0;
  }
}

// ---- Params ----
bool Adns2610Module::getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx) {
  auto* m = (Adns2610Module*)ctx;

  if (!strcmp(key, "adns.led"))       { snprintf(out, outLen, "%d", m->_cfg.ledOnBoot ? 1 : 0); return true; }
  if (!strcmp(key, "adns.capture"))   { snprintf(out, outLen, "%d", m->_framePending ? 1 : 0); return true; }
  if (!strcmp(key, "adns.motion_on")) { snprintf(out, outLen, "%d", m->_cfg.enableMotionStream ? 1 : 0); return true; }

  if (!strcmp(key, "adns.dx"))        { snprintf(out, outLen, "%d", (int)m->_dxLast); return true; }
  if (!strcmp(key, "adns.dy"))        { snprintf(out, outLen, "%d", (int)m->_dyLast); return true; }
  if (!strcmp(key, "adns.squal"))     { snprintf(out, outLen, "%u", (unsigned)m->_squalLast); return true; }
  if (!strcmp(key, "adns.maxpix"))    { snprintf(out, outLen, "%u", (unsigned)m->_maxPixLast); return true; }
  if (!strcmp(key, "adns.minpix"))    { snprintf(out, outLen, "%u", (unsigned)m->_minPixLast); return true; }
  if (!strcmp(key, "adns.pixsum"))    { snprintf(out, outLen, "%u", (unsigned)m->_pixSumLast); return true; }
  if (!strcmp(key, "adns.shutter"))   { snprintf(out, outLen, "%u", (unsigned)m->_shutterLast); return true; }
  if (!strcmp(key, "adns.status"))    { snprintf(out, outLen, "%u", (unsigned)m->_statusLast); return true; }

  if (!strcmp(key, "adns.w"))         { snprintf(out, outLen, "%u", (unsigned)ADNS2610_FRAME_W); return true; }
  if (!strcmp(key, "adns.h"))         { snprintf(out, outLen, "%u", (unsigned)ADNS2610_FRAME_H); return true; }
  if (!strcmp(key, "adns.chunk_px"))  { snprintf(out, outLen, "%u", (unsigned)ADNS2610_CHUNK_PIXELS); return true; }

  if (!strcmp(key, "adns.resync"))    { snprintf(out, outLen, "0"); return true; } // write-only trigger

  return false;
}

bool Adns2610Module::setParam(UniProto&, const char* key, const char* value, void* ctx) {
  auto* m = (Adns2610Module*)ctx;
  m->beginIfNeeded();

  if (!strcmp(key, "adns.led")) {
    const bool on = UniProto::parseInt(value) != 0;
    m->_cfg.ledOnBoot = on;
    m->forceAwake(on);
    return true;
  }

  if (!strcmp(key, "adns.motion_on")) {
    m->_cfg.enableMotionStream = (UniProto::parseInt(value) != 0);
    return true;
  }

  if (!strcmp(key, "adns.capture")) {
    const bool on = UniProto::parseInt(value) != 0;
    if (on) {
      m->_frameId++;
      m->_frameOffset = 0;
      if (m->captureFrame()) {
        m->_framePending = true;
        return true;
      }
      return false;
    } else {
      m->_framePending = false;
      m->_frameOffset = 0;
      return true;
    }
  }

  if (!strcmp(key, "adns.resync")) {
    const bool trig = UniProto::parseInt(value) != 0;
    if (trig) m->reSync();
    return true;
  }

  // read-only keys:
  if (!strcmp(key, "adns.dx")) return false;
  if (!strcmp(key, "adns.dy")) return false;
  if (!strcmp(key, "adns.squal")) return false;
  if (!strcmp(key, "adns.maxpix")) return false;
  if (!strcmp(key, "adns.minpix")) return false;
  if (!strcmp(key, "adns.pixsum")) return false;
  if (!strcmp(key, "adns.shutter")) return false;
  if (!strcmp(key, "adns.status")) return false;
  if (!strcmp(key, "adns.w")) return false;
  if (!strcmp(key, "adns.h")) return false;
  if (!strcmp(key, "adns.chunk_px")) return false;

  return false;
}
