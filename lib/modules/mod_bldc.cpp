#include "mod_bldc.h"
#include <math.h>
#include <string.h>
#include <stdio.h>

static float clampf(float x, float a, float b) { return (x < a) ? a : (x > b) ? b : x; }

BldcModule::BldcModule(const Config& cfg) : _cfg(cfg) {
  _w  = _cfg.wire ? _cfg.wire : &Wire;
  _hz = _cfg.controlHz ? _cfg.controlHz : 500;
}

void BldcModule::registerWith(UniProto& proto) {
  _proto = &proto;

  proto.registerStream({
    _cfg.streamId, _cfg.streamName, _cfg.schema, _cfg.units,
    &BldcModule::emitFn, this
  });

  // Core
  proto.registerParam({"bldc.enable", UniProto::ParamType::BOOL,  &getParam, &setParam, this});
  proto.registerParam({"bldc.src",    UniProto::ParamType::INT32, &getParam, &setParam, this}); // 0/1/2

  // External loop
  proto.registerParam({"bldc.mode",   UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"bldc.cmd",    UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"bldc.set",    UniProto::ParamType::FLOAT, &getParam, &setParam, this});

  proto.registerParam({"bldc.kp",     UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.ki",     UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.kd",     UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.i_lim",  UniProto::ParamType::FLOAT, &getParam, &setParam, this});

  proto.registerParam({"bldc.spring_k", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.damp_b",   UniProto::ParamType::FLOAT, &getParam, &setParam, this});

  proto.registerParam({"bldc.min",    UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.max",    UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.stop_k", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.stop_b", UniProto::ParamType::FLOAT, &getParam, &setParam, this});

  proto.registerParam({"bldc.detent_step", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.detent_k",    UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.detent_b",    UniProto::ParamType::FLOAT, &getParam, &setParam, this});

  proto.registerParam({"bldc.vel_a",  UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.cmd_lim",UniProto::ParamType::INT32, &getParam, &setParam, this});

  // Driver (STM32) setpoints
  proto.registerParam({"bldc.rpm",    UniProto::ParamType::FLOAT, &getParam, &setParam, this}); // speed setpoint
  proto.registerParam({"bldc.pos",    UniProto::ParamType::FLOAT, &getParam, &setParam, this}); // position setpoint (V2)

  // Driver PID (best-effort; V1 scaling is clear, V2 differs)
  proto.registerParam({"bldc.drv_p",  UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.drv_i",  UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"bldc.drv_d",  UniProto::ParamType::FLOAT, &getParam, &setParam, this});

  // Motor config
  proto.registerParam({"bldc.pole_pairs", UniProto::ParamType::INT32, &getParam, &setParam, this});

  // Actions
  proto.registerAction({"bldc.zero", &doZero, this});
  proto.registerAction({"bldc.stop", &doStop, this});

  // Apply initial pole-pairs if using V1
  if (_cfg.proto == Config::DriverProto::V1_ADDR_0x65) {
    drvV1_setPolePairs(_cfg.polePairs);
  }
}

void BldcModule::poll() {
  const uint32_t nowUs = micros();
  const uint32_t periodUs = 1000000UL / (uint32_t)_hz;
  if (_lastUs && (uint32_t)(nowUs - _lastUs) < periodUs) return;

  float dt = (_lastUs == 0) ? (1.0f / (float)_hz) : ((nowUs - _lastUs) * 1e-6f);
  _lastUs = nowUs;

  // Update AS5600 position/velocity always (useful telemetry even in STM32 mode)
  updatePosition(dt);

  // Read driver feedback (best-effort)
  if (_cfg.proto == Config::DriverProto::V1_ADDR_0x65) {
    float rpm = 0.0f;
    if (drvV1_readRpmFloat(rpm)) _rpmFb = rpm;
  } else {
    int32_t x100 = 0;
    if (drvV2_readSpeedX100(x100)) _rpmFb = (float)x100 / 100.0f;
  }

  if (!_enable) {
    driverEnable(false);
    driverApplyExternalEffort(0);
    return;
  }

  driverEnable(true);

  // Apply control based on source
  if (_src == 0) {
    const float posRad = countsToRad(_posCounts);
    const float velRad = (_velCounts * (2.0f * (float)M_PI)) / (float)_cfg.as5600CountsPerRev;
    const int16_t effort = computeExternalEffort(dt, posRad, velRad);
    driverApplyExternalEffort(effort);
  } else if (_src == 1) {
    driverApplySpeedRpm(_rpmSet);
  } else { // _src == 2
    driverApplyPosition(_posSet);
  }
}

// ------------------ STREAM ------------------

void BldcModule::emitFn(UniProto& p, uint8_t, UniFrameWriter& w, void* ctx) {
  ((BldcModule*)ctx)->emit(p, w);
}

void BldcModule::emit(UniProto& p, UniFrameWriter& w) {
  const float posRad = countsToRad(_posCounts);
  const float velRad = (_velCounts * (2.0f * (float)M_PI)) / (float)_cfg.as5600CountsPerRev;

  if (p.format() == UniProto::Format::BINARY) {
    // f32 pos, f32 vel, f32 set, i16 cmd, u8 mode, u8 src, f32 rpmfb
    // payload = 4+4+4 +2+1+1 +4 = 20 bytes
    w.begin(_cfg.streamId, 20);
    w.f32(posRad);
    w.f32(velRad);
    w.f32(_setRad);
    w.u16((uint16_t)_cmd);     // store raw bits; if you prefer signed in binary, switch to i32
    w.u16((uint16_t)((_mode & 0xFF) | ((_src & 0xFF) << 8)));
    w.f32(_rpmFb);
    w.end();
    return;
  }

  w.begin(_cfg.streamId);
  w.f32(posRad, nullptr, 4);
  w.f32(velRad, nullptr, 3);
  w.f32(_setRad, nullptr, 4);
  w.i32((int32_t)_cmd);
  w.i32((int32_t)_mode);
  w.i32((int32_t)_src);
  w.f32(_rpmFb, nullptr, 2);
  w.end();
}

// ------------------ PARAMS ------------------

static void ftoa_avr(float v, char* out, size_t outLen, uint8_t dec=3) {
#if defined(ARDUINO_ARCH_AVR)
  (void)outLen;
  dtostrf(v, 0, dec, out);
#else
  snprintf(out, outLen, "%.*f", dec, (double)v);
#endif
}

bool BldcModule::getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx) {
  BldcModule* m = (BldcModule*)ctx;

  if (!strcmp(key, "bldc.enable")) { snprintf(out, outLen, "%d", m->_enable?1:0); return true; }
  if (!strcmp(key, "bldc.src"))    { snprintf(out, outLen, "%u", (unsigned)m->_src); return true; }

  if (!strcmp(key, "bldc.mode"))   { snprintf(out, outLen, "%u", (unsigned)m->_mode); return true; }
  if (!strcmp(key, "bldc.cmd"))    { snprintf(out, outLen, "%d", (int)m->_cmd); return true; }
  if (!strcmp(key, "bldc.set"))    { ftoa_avr(m->_setRad, out, outLen, 4); return true; }

  if (!strcmp(key, "bldc.kp"))     { ftoa_avr(m->_kp, out, outLen, 4); return true; }
  if (!strcmp(key, "bldc.ki"))     { ftoa_avr(m->_ki, out, outLen, 4); return true; }
  if (!strcmp(key, "bldc.kd"))     { ftoa_avr(m->_kd, out, outLen, 4); return true; }
  if (!strcmp(key, "bldc.i_lim"))  { ftoa_avr(m->_iLim, out, outLen, 2); return true; }

  if (!strcmp(key, "bldc.spring_k")) { ftoa_avr(m->_springK, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.damp_b"))   { ftoa_avr(m->_dampB, out, outLen, 3); return true; }

  if (!strcmp(key, "bldc.min"))    { ftoa_avr(m->_minRad, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.max"))    { ftoa_avr(m->_maxRad, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.stop_k")) { ftoa_avr(m->_stopK, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.stop_b")) { ftoa_avr(m->_stopB, out, outLen, 3); return true; }

  if (!strcmp(key, "bldc.detent_step")) { ftoa_avr(m->_detentStep, out, outLen, 4); return true; }
  if (!strcmp(key, "bldc.detent_k"))    { ftoa_avr(m->_detentK, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.detent_b"))    { ftoa_avr(m->_detentB, out, outLen, 3); return true; }

  if (!strcmp(key, "bldc.vel_a"))  { ftoa_avr(m->_velAlpha, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.cmd_lim")){ snprintf(out, outLen, "%d", (int)m->_cfg.cmdLimit); return true; }

  if (!strcmp(key, "bldc.rpm"))    { ftoa_avr(m->_rpmSet, out, outLen, 2); return true; }
  if (!strcmp(key, "bldc.pos"))    { ftoa_avr(m->_posSet, out, outLen, 3); return true; }

  if (!strcmp(key, "bldc.drv_p"))  { ftoa_avr(m->_drvP, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.drv_i"))  { ftoa_avr(m->_drvI, out, outLen, 3); return true; }
  if (!strcmp(key, "bldc.drv_d"))  { ftoa_avr(m->_drvD, out, outLen, 3); return true; }

  if (!strcmp(key, "bldc.pole_pairs")) { snprintf(out, outLen, "%u", (unsigned)m->_cfg.polePairs); return true; }

  return false;
}

bool BldcModule::setParam(UniProto&, const char* key, const char* value, void* ctx) {
  BldcModule* m = (BldcModule*)ctx;

  if (!strcmp(key, "bldc.enable")) {
    m->_enable = (UniProto::parseInt(value) != 0);
    m->resetIntegrator();
    m->driverEnable(m->_enable);
    if (!m->_enable) m->driverApplyExternalEffort(0);
    return true;
  }

  if (!strcmp(key, "bldc.src")) {
    long v = UniProto::parseInt(value);
    if (v < 0) v = 0;
    if (v > 2) v = 2;
    m->_src = (uint8_t)v;
    m->resetIntegrator();
    return true;
  }

  if (!strcmp(key, "bldc.mode")) {
    long v = UniProto::parseInt(value);
    if (v < 0) v = 0;
    if (v > 4) v = 4;
    m->_mode = (uint8_t)v;
    m->resetIntegrator();
    return true;
  }

  if (!strcmp(key, "bldc.cmd")) {
    m->_cmd = (int16_t)UniProto::parseInt(value);
    m->_cmd = m->clampCmd(m->_cmd);
    return true;
  }

  if (!strcmp(key, "bldc.set"))      { m->_setRad = UniProto::parseFloat(value); return true; }

  if (!strcmp(key, "bldc.kp"))       { m->_kp = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.ki"))       { m->_ki = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.kd"))       { m->_kd = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.i_lim"))    { m->_iLim = fabsf(UniProto::parseFloat(value)); return true; }

  if (!strcmp(key, "bldc.spring_k")) { m->_springK = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.damp_b"))   { m->_dampB = UniProto::parseFloat(value); return true; }

  if (!strcmp(key, "bldc.min"))      { m->_minRad = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.max"))      { m->_maxRad = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.stop_k"))   { m->_stopK = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.stop_b"))   { m->_stopB = UniProto::parseFloat(value); return true; }

  if (!strcmp(key, "bldc.detent_step")) { m->_detentStep = fabsf(UniProto::parseFloat(value)); return true; }
  if (!strcmp(key, "bldc.detent_k"))    { m->_detentK = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.detent_b"))    { m->_detentB = UniProto::parseFloat(value); return true; }

  if (!strcmp(key, "bldc.vel_a")) {
    float a = UniProto::parseFloat(value);
    m->_velAlpha = clampf(a, 0.01f, 0.99f);
    return true;
  }

  if (!strcmp(key, "bldc.cmd_lim")) {
    long lim = UniProto::parseInt(value);
    if (lim < 1) lim = 1;
    if (lim > 2000) lim = 2000;
    m->_cfg.cmdLimit = (int16_t)lim;
    return true;
  }

  // STM32 driver setpoints
  if (!strcmp(key, "bldc.rpm")) { m->_rpmSet = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.pos")) { m->_posSet = UniProto::parseFloat(value); return true; }

  // driver pid
  if (!strcmp(key, "bldc.drv_p")) { m->_drvP = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.drv_i")) { m->_drvI = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "bldc.drv_d")) { m->_drvD = UniProto::parseFloat(value); return true; }

  if (!strcmp(key, "bldc.pole_pairs")) {
    long pp = UniProto::parseInt(value);
    if (pp < 1) pp = 1;
    if (pp > 255) pp = 255;
    m->_cfg.polePairs = (uint8_t)pp;
    // V1 supports writing pole pairs via 0x70 :contentReference[oaicite:6]{index=6}
    if (m->_cfg.proto == Config::DriverProto::V1_ADDR_0x65) m->drvV1_setPolePairs(m->_cfg.polePairs);
    return true;
  }

  return false;
}

// ------------------ ACTIONS ------------------

bool BldcModule::doZero(UniProto&, const char*, const char*, Stream& out, void* ctx) {
  BldcModule* m = (BldcModule*)ctx;
  m->_posCounts = 0;
  m->_haveLast = false;
  m->resetIntegrator();
  out.println(F("bldc.zero"));
  return true;
}

bool BldcModule::doStop(UniProto&, const char*, const char*, Stream& out, void* ctx) {
  BldcModule* m = (BldcModule*)ctx;
  m->_enable = false;
  m->_cmd = 0;
  m->resetIntegrator();
  m->driverEnable(false);
  m->driverApplyExternalEffort(0);
  out.println(F("bldc.stop"));
  return true;
}

// ------------------ AS5600 ------------------

bool BldcModule::readAs5600Raw(uint16_t& outRaw) {
  // RAW ANGLE registers 0x0C/0x0D (12-bit)
  const uint8_t reg = 0x0C;
  _w->beginTransmission(_cfg.as5600Addr);
  _w->write(reg);
  if (_w->endTransmission(false) != 0) return false;

  if (_w->requestFrom((int)_cfg.as5600Addr, (int)2) != 2) return false;
  uint16_t hi = _w->read();
  uint16_t lo = _w->read();
  outRaw = (uint16_t)((hi << 8) | lo);
  outRaw &= 0x0FFF;
  return true;
}

void BldcModule::updatePosition(float dt) {
  uint16_t raw = 0;
  if (!readAs5600Raw(raw)) return;

  if (!_haveLast) {
    _lastRaw = raw;
    _haveLast = true;
    _posCounts = 0;
    _velCounts = 0;
    return;
  }

  int16_t d = (int16_t)raw - (int16_t)_lastRaw;
  const int16_t half = (int16_t)(_cfg.as5600CountsPerRev / 2);
  if (d > half)  d -= (int16_t)_cfg.as5600CountsPerRev;
  if (d < -half) d += (int16_t)_cfg.as5600CountsPerRev;

  _lastRaw = raw;

  if (_cfg.invert) d = -d;

  _posCounts += (int32_t)d;

  const float v = (dt > 1e-6f) ? ((float)d / dt) : 0.0f;
  _velCounts = _velAlpha * v + (1.0f - _velAlpha) * _velCounts;
}

float BldcModule::countsToRad(int32_t c) const {
  return ((float)c * (2.0f * (float)M_PI)) / (float)_cfg.as5600CountsPerRev;
}

// ------------------ EXTERNAL CONTROL ------------------

void BldcModule::resetIntegrator() {
  _i = 0.0f;
  _lastErr = 0.0f;
}

int16_t BldcModule::clampCmd(int16_t c) const {
  const int16_t lim = (int16_t)abs(_cfg.cmdLimit);
  if (c > lim) return lim;
  if (c < -lim) return -lim;
  return c;
}

int16_t BldcModule::computeExternalEffort(float dt, float posRad, float velRad) {
  if (_mode == 0) return clampCmd(_cmd);

  if (_mode == 1) { // PID position
    const float err = (_setRad - posRad);
    _i += err * dt;
    _i = clampf(_i, -_iLim, _iLim);
    const float derr = (err - _lastErr) / (dt > 1e-6f ? dt : 1e-6f);
    _lastErr = err;
    const float u = _kp * err + _ki * _i + _kd * derr;
    return clampCmd((int16_t)lroundf(u));
  }

  if (_mode == 2) { // spring-damper
    const float err = (_setRad - posRad);
    const float u = _springK * err - _dampB * velRad;
    return clampCmd((int16_t)lroundf(u));
  }

  if (_mode == 3) { // endstops
    float u = 0.0f;
    if (posRad >= _minRad && posRad <= _maxRad) {
      const float err = (_setRad - posRad);
      u = _springK * err - _dampB * velRad;
    } else if (posRad < _minRad) {
      const float err = (_minRad - posRad);
      u = _stopK * err - _stopB * velRad;
    } else {
      const float err = (_maxRad - posRad);
      u = _stopK * err - _stopB * velRad;
    }
    return clampCmd((int16_t)lroundf(u));
  }

  // detents
  if (_mode == 4) {
    if (_detentStep < 1e-4f) _detentStep = 0.2f;
    const int32_t k = (int32_t)lroundf(posRad / _detentStep);
    const float target = (float)k * _detentStep;
    const float err = (target - posRad);
    const float u = _detentK * err - _detentB * velRad;
    return clampCmd((int16_t)lroundf(u));
  }

  return 0;
}

// ------------------ DRIVER I2C LOW LEVEL ------------------

uint8_t BldcModule::driverAddr() const {
  return (_cfg.proto == Config::DriverProto::V1_ADDR_0x65) ? _cfg.driverAddrV1 : _cfg.driverAddrV2;
}

bool BldcModule::i2cWrite(uint8_t addr, uint8_t reg, const uint8_t* data, uint8_t n) {
  _w->beginTransmission(addr);
  _w->write(reg);
  for (uint8_t i = 0; i < n; i++) _w->write(data[i]);
  return (_w->endTransmission() == 0);
}

bool BldcModule::i2cRead(uint8_t addr, uint8_t reg, uint8_t* data, uint8_t n) {
  _w->beginTransmission(addr);
  _w->write(reg);
  if (_w->endTransmission(false) != 0) return false;
  if (_w->requestFrom((int)addr, (int)n) != n) return false;
  for (uint8_t i = 0; i < n; i++) data[i] = _w->read();
  return true;
}

// ------------------ V1 PROTOCOL (0x65) ------------------
// From 2023/12/5 doc:
// 0x00 Mode (0 open loop; 1 closed loop)
// 0x10 PWM-L PWM-H (0..2047)
// 0x40 Setting RPM float / 0xD0 Setting RPM x100 int
// 0x50 PID x100 (P/I/D each 4 bytes) :contentReference[oaicite:7]{index=7}
// 0x60 Direction
// 0x70 Motor model + Pole pairs
// 0x20 Readback RPM float :contentReference[oaicite:8]{index=8}

bool BldcModule::drvV1_setMode(uint8_t mode0_open1_closed) {
  uint8_t v = (mode0_open1_closed ? 1 : 0);
  return i2cWrite(_cfg.driverAddrV1, 0x00, &v, 1);
}

bool BldcModule::drvV1_setDirection(uint8_t dir0_1) {
  uint8_t v = (dir0_1 ? 1 : 0);
  return i2cWrite(_cfg.driverAddrV1, 0x60, &v, 1);
}

bool BldcModule::drvV1_setPolePairs(uint8_t polePairs) {
  // reg 0x70: motor model + pole pairs (2 bytes) :contentReference[oaicite:9]{index=9}
  uint8_t data[2];
  data[0] = 1; // motor model (0 low speed / 1 high speed) per doc :contentReference[oaicite:10]{index=10}
  data[1] = polePairs;
  return i2cWrite(_cfg.driverAddrV1, 0x70, data, 2);
}

bool BldcModule::drvV1_setOpenLoopPwm(uint16_t pwm0_2047) {
  if (pwm0_2047 > 2047) pwm0_2047 = 2047;
  uint8_t data[2] = { (uint8_t)(pwm0_2047 & 0xFF), (uint8_t)((pwm0_2047 >> 8) & 0xFF) };
  return i2cWrite(_cfg.driverAddrV1, 0x10, data, 2);
}

bool BldcModule::drvV1_setRpmX100(int32_t rpm_x100) {
  uint8_t data[4] = {
    (uint8_t)(rpm_x100 & 0xFF),
    (uint8_t)((rpm_x100 >> 8) & 0xFF),
    (uint8_t)((rpm_x100 >> 16) & 0xFF),
    (uint8_t)((rpm_x100 >> 24) & 0xFF)
  };
  return i2cWrite(_cfg.driverAddrV1, 0xD0, data, 4);
}

bool BldcModule::drvV1_setPidX100(float p, float i, float d) {
  // doc: store as value*100 into u32 (little endian) :contentReference[oaicite:11]{index=11}
  int32_t P = (int32_t)lroundf(p * 100.0f);
  int32_t I = (int32_t)lroundf(i * 100.0f);
  int32_t D = (int32_t)lroundf(d * 100.0f);
  uint8_t data[12] = {
    (uint8_t)(P & 0xFF), (uint8_t)((P>>8)&0xFF), (uint8_t)((P>>16)&0xFF), (uint8_t)((P>>24)&0xFF),
    (uint8_t)(I & 0xFF), (uint8_t)((I>>8)&0xFF), (uint8_t)((I>>16)&0xFF), (uint8_t)((I>>24)&0xFF),
    (uint8_t)(D & 0xFF), (uint8_t)((D>>8)&0xFF), (uint8_t)((D>>16)&0xFF), (uint8_t)((D>>24)&0xFF)
  };
  return i2cWrite(_cfg.driverAddrV1, 0x50, data, 12);
}

bool BldcModule::drvV1_readRpmFloat(float& rpm) {
  uint8_t data[4];
  if (!i2cRead(_cfg.driverAddrV1, 0x20, data, 4)) return false;
  float f;
  memcpy(&f, data, 4);
  rpm = f;
  return true;
}

// ------------------ V2 PROTOCOL (0x64) ------------------
// From 2024/6/3 doc (Addr 0x64):
// 0x00 Output on/off + Mode etc
// 0x40 Speed Setting x100 int
// 0x60 Speed Readback x100 int
// 0x80 Position Setting x100 int :contentReference[oaicite:12]{index=12}

bool BldcModule::drvV2_setOutput(bool on) {
  // 0x00: "Output 0:off 1:on" is the first field in the config register. :contentReference[oaicite:13]{index=13}
  // For simplicity we write a single byte with output bit only if device accepts it.
  // If your unit needs a packed config byte, we can adjust once tested.
  uint8_t v = on ? 1 : 0;
  return i2cWrite(_cfg.driverAddrV2, 0x00, &v, 1);
}

bool BldcModule::drvV2_setMode(uint8_t mode1_speed2_pos3_current4_encoder) {
  // V2 packs multiple fields in 0x00; without the full bit layout here,
  // we keep this as a best-effort: write mode in second byte (common pattern).
  // If needed, we’ll patch once you confirm behavior on hardware.
  uint8_t data[2] = { 1, mode1_speed2_pos3_current4_encoder }; // output=1, mode=...
  return i2cWrite(_cfg.driverAddrV2, 0x00, data, 2);
}

bool BldcModule::drvV2_setSpeedX100(int32_t speed_x100) {
  uint8_t data[4] = {
    (uint8_t)(speed_x100 & 0xFF),
    (uint8_t)((speed_x100 >> 8) & 0xFF),
    (uint8_t)((speed_x100 >> 16) & 0xFF),
    (uint8_t)((speed_x100 >> 24) & 0xFF)
  };
  return i2cWrite(_cfg.driverAddrV2, 0x40, data, 4);
}

bool BldcModule::drvV2_setPositionX100(int32_t pos_x100) {
  uint8_t data[4] = {
    (uint8_t)(pos_x100 & 0xFF),
    (uint8_t)((pos_x100 >> 8) & 0xFF),
    (uint8_t)((pos_x100 >> 16) & 0xFF),
    (uint8_t)((pos_x100 >> 24) & 0xFF)
  };
  return i2cWrite(_cfg.driverAddrV2, 0x80, data, 4);
}

bool BldcModule::drvV2_readSpeedX100(int32_t& speed_x100) {
  uint8_t data[4];
  if (!i2cRead(_cfg.driverAddrV2, 0x60, data, 4)) return false;
  speed_x100 = (int32_t)(
    ((uint32_t)data[0]) |
    ((uint32_t)data[1] << 8) |
    ((uint32_t)data[2] << 16) |
    ((uint32_t)data[3] << 24)
  );
  return true;
}

// ------------------ UNIFIED DRIVER APPLY ------------------

void BldcModule::driverEnable(bool en) {
  if (_cfg.proto == Config::DriverProto::V1_ADDR_0x65) {
    // V1 has no explicit output enable; we just set mode and pwm/rpm.
    // (You can also use motor status/registers if needed.)
    (void)en;
  } else {
    drvV2_setOutput(en);
  }
}

void BldcModule::driverApplyExternalEffort(int16_t effort) {
  effort = clampCmd(effort);

  uint8_t dir = (effort < 0) ? 1 : 0;
  uint16_t mag = (uint16_t)abs(effort);

  // scale effort -> pwm (0..pwmMax)
  const int16_t lim = (int16_t)abs(_cfg.cmdLimit);
  uint16_t pwm = 0;
  if (lim > 0) pwm = (uint16_t)((uint32_t)mag * (uint32_t)_cfg.pwmMax / (uint32_t)lim);
  if (pwm > 2047) pwm = 2047;

  if (_cfg.proto == Config::DriverProto::V1_ADDR_0x65) {

    // Ensure open-loop mode (write once)
    if (_v1_lastMode != 0) {
      drvV1_setMode(0);
      _v1_lastMode = 0;
      _v1_lastDir = 255;
      _v1_lastPwm = 0xFFFF;
    }

    // ---- Safe direction change ----
    // If direction changes while PWM is nonzero, many drivers ignore it unless PWM==0.
    if (_v1_lastDir != 255 && dir != _v1_lastDir) {
      if (_v1_lastPwm != 0 && _v1_lastPwm != 0xFFFF) {
        drvV1_setOpenLoopPwm(0);
        _v1_lastPwm = 0;
        delayMicroseconds(300); // small dead-time
      }
      drvV1_setDirection(dir);
      _v1_lastDir = dir;
      delayMicroseconds(300);   // small dead-time
      // fall through to write pwm below
    } else {
      // Direction not set yet, or unchanged
      if (_v1_lastDir == 255) {
        drvV1_setDirection(dir);
        _v1_lastDir = dir;
      }
    }

    // PWM update (only if changed)
    if (pwm != _v1_lastPwm) {
      drvV1_setOpenLoopPwm(pwm);
      _v1_lastPwm = pwm;
    }

    return;
  }

  // (V2 path unchanged)
  drvV2_setMode(1);
  drvV2_setSpeedX100((int32_t)(effort * 10));
}



void BldcModule::driverApplySpeedRpm(float rpm) {
  if (_cfg.proto == Config::DriverProto::V1_ADDR_0x65) {
    drvV1_setPolePairs(_cfg.polePairs);
    drvV1_setPidX100(_drvP, _drvI, _drvD);      // :contentReference[oaicite:17]{index=17}
    drvV1_setMode(1);                            // closed-loop :contentReference[oaicite:18]{index=18}
    drvV1_setRpmX100((int32_t)lroundf(rpm * 100.0f));
  } else {
    drvV2_setMode(1); // speed mode :contentReference[oaicite:19]{index=19}
    drvV2_setSpeedX100((int32_t)lroundf(rpm * 100.0f)); // x100 :contentReference[oaicite:20]{index=20}
  }
}

void BldcModule::driverApplyPosition(float posUser) {
  // V1 protocol does not document position mode; V2 does. :contentReference[oaicite:21]{index=21}
  if (_cfg.proto == Config::DriverProto::V1_ADDR_0x65) {
    // fallback: hold still using speed=0
    drvV1_setMode(1);
    drvV1_setRpmX100(0);
    return;
  }

  // V2: position setting is x100 int at 0x80. :contentReference[oaicite:22]{index=22}
  // The doc doesn’t state units in the excerpt; many M5 motion units use degrees.
  // We treat posUser as "degrees" for now; tune later if needed.
  drvV2_setMode(2);
  drvV2_setPositionX100((int32_t)lroundf(posUser * 100.0f));
}
