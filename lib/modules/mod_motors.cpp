#include "mod_motors.h"
#include <stdio.h>

DualMotorModule* DualMotorModule::_inst = nullptr;

static inline int16_t clampi16(int32_t v, int16_t lo, int16_t hi) {
  if (v < lo) return lo;
  if (v > hi) return hi;
  return (int16_t)v;
}

DualMotorModule::DualMotorModule(const Config& cfg) : _cfg(cfg) {}

void DualMotorModule::registerWith(UniProto& proto) {
  _proto = &proto;

  pinMode(_cfg.encA0, INPUT_PULLUP);
  pinMode(_cfg.encB0, INPUT_PULLUP);
  pinMode(_cfg.encA1, INPUT_PULLUP);
  pinMode(_cfg.encB1, INPUT_PULLUP);

  pinMode(_cfg.pwm0, OUTPUT);
  pinMode(_cfg.dir0, OUTPUT);
  pinMode(_cfg.pwm1, OUTPUT);
  pinMode(_cfg.dir1, OUTPUT);

  setupPwm(); // set at right frequency

  applyMotor(_cfg.pwm0, _cfg.dir0, 0);
  applyMotor(_cfg.pwm1, _cfg.dir1, 0);

  _inst = this;
  attachInterrupt(digitalPinToInterrupt(_cfg.encA0), DualMotorModule::isrEnc0, CHANGE);
  attachInterrupt(digitalPinToInterrupt(_cfg.encA1), DualMotorModule::isrEnc1, CHANGE);

  proto.registerStream({
    _cfg.streamId,
    "motors",
    "i32 pos0,i32 pos1,i32 set0,i32 set1,i32 cmd0,i32 cmd1,i32 err0,i32 err1",
    "ticks,ticks,ticks,ticks,pwm,pwm,ticks,ticks",
    &DualMotorModule::emitFn,
    this
  });

  proto.registerStream({
    _cfg.streamIdRaw,
    "enc",
    "i32 pos0,i32 pos1",
    "ticks,ticks",
    &DualMotorModule::emitRawFn,
    this
  });

  // ---- params ----
  proto.registerParam({"motor0.kp", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"motor0.ki", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"motor0.kd", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"motor0.set", UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"motor0.enable", UniProto::ParamType::BOOL, &getParam, &setParam, this});
  proto.registerParam({"motor0.pwm_lim", UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"motor0.pwm", UniProto::ParamType::INT32, &getParam, &setParam, this});

  proto.registerParam({"motor1.kp", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"motor1.ki", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"motor1.kd", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
  proto.registerParam({"motor1.set", UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"motor1.enable", UniProto::ParamType::BOOL, &getParam, &setParam, this});
  proto.registerParam({"motor1.pwm_lim", UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"motor1.pwm", UniProto::ParamType::INT32, &getParam, &setParam, this});

  proto.registerParam({"motor.hz", UniProto::ParamType::INT32, &getParam, &setParam, this});
  proto.registerParam({"motor.link", UniProto::ParamType::INT32, &getParam, &setParam, this});
proto.registerParam({"motor.link_scale", UniProto::ParamType::FLOAT, &getParam, &setParam, this});
proto.registerParam({"motor.link_offset", UniProto::ParamType::INT32, &getParam, &setParam, this});


  proto.registerAction({"motor.zero", &doZero, this});
  proto.registerAction({"motor.stop", &doStop, this});

  _lastCtrlUs = micros();
}

void DualMotorModule::poll() {
  const uint32_t now = micros();
  const uint32_t periodUs = 1000000UL / _hz;
  if ((uint32_t)(now - _lastCtrlUs) < periodUs) return;

  _lastCtrlUs += periodUs;
  const float dt = periodUs * 1e-6f;

  const int32_t p0 = readPos0();
  const int32_t p1 = readPos1();

  updateLinkedSetpoints(p0, p1);

  const int16_t c0 = _en0 ? pidStep0(dt, p0) : _cmd0;
  const int16_t c1 = _en1 ? pidStep1(dt, p1) : _cmd1;

  _cmd0 = c0;
  _cmd1 = c1;

  applyMotor(_cfg.pwm0, _cfg.dir0, c0);
  applyMotor(_cfg.pwm1, _cfg.dir1, c1);
}

// ---------- streams ----------
void DualMotorModule::emitFn(UniProto& p, uint8_t, UniFrameWriter& w, void* ctx) {
  ((DualMotorModule*)ctx)->emit(p, 0, w);
}
void DualMotorModule::emitRawFn(UniProto& p, uint8_t, UniFrameWriter& w, void* ctx) {
  ((DualMotorModule*)ctx)->emitRaw(p, 0, w);
}

void DualMotorModule::emit(UniProto& p, uint8_t, UniFrameWriter& w) {
  const int32_t pos0 = readPos0();
  const int32_t pos1 = readPos1();
  const int32_t err0 = _set0 - pos0;
  const int32_t err1 = _set1 - pos1;

  if (p.format() == UniProto::Format::BINARY) {
    w.begin(_cfg.streamId, 32);
    w.i32(pos0); w.i32(pos1);
    w.i32(_set0); w.i32(_set1);
    w.i32(_cmd0); w.i32(_cmd1);
    w.i32(err0);  w.i32(err1);
    w.end();
  } else {
    w.begin(_cfg.streamId);
    w.i32(pos0, "pos0");
    w.i32(pos1, "pos1");
    w.i32(_set0, "set0");
    w.i32(_set1, "set1");
    w.i32(_cmd0, "cmd0");
    w.i32(_cmd1, "cmd1");
    w.i32(err0, "err0");
    w.i32(err1, "err1");
    w.end();
  }
}

void DualMotorModule::emitRaw(UniProto& p, uint8_t, UniFrameWriter& w) {
  const int32_t pos0 = readPos0();
  const int32_t pos1 = readPos1();

  if (p.format() == UniProto::Format::BINARY) {
    w.begin(_cfg.streamIdRaw, 8);
    w.i32(pos0); w.i32(pos1);
    w.end();
  } else {
    w.begin(_cfg.streamIdRaw);
    w.i32(pos0, "pos0");
    w.i32(pos1, "pos1");
    w.end();
  }
}

// ---------- params ----------
bool DualMotorModule::getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx) {
  DualMotorModule* m = (DualMotorModule*)ctx;

#if defined(ARDUINO_ARCH_AVR)
  auto f2s = [&](float v) { dtostrf(v, 0, 4, out); };
#else
  auto f2s = [&](float v) { snprintf(out, outLen, "%.4f", (double)v); };
#endif

  if (!strcmp(key, "motor0.kp")) { f2s(m->_kp0); return true; }
  if (!strcmp(key, "motor0.ki")) { f2s(m->_ki0); return true; }
  if (!strcmp(key, "motor0.kd")) { f2s(m->_kd0); return true; }
  if (!strcmp(key, "motor0.set")) { snprintf(out, outLen, "%ld", (long)m->_set0); return true; }
  if (!strcmp(key, "motor0.enable")) { snprintf(out, outLen, "%d", m->_en0); return true; }
  if (!strcmp(key, "motor0.pwm")) { snprintf(out, outLen, "%d", m->_cmd0); return true; }
  if (!strcmp(key, "motor0.pwm_lim")) { snprintf(out, outLen, "%d", m->_pwmLim0); return true; }


  if (!strcmp(key, "motor1.kp")) { f2s(m->_kp1); return true; }
  if (!strcmp(key, "motor1.ki")) { f2s(m->_ki1); return true; }
  if (!strcmp(key, "motor1.kd")) { f2s(m->_kd1); return true; }
  if (!strcmp(key, "motor1.set")) { snprintf(out, outLen, "%ld", (long)m->_set1); return true; }
  if (!strcmp(key, "motor1.enable")) { snprintf(out, outLen, "%d", m->_en1); return true; }
  if (!strcmp(key, "motor1.pwm")) { snprintf(out, outLen, "%d", m->_cmd1); return true; }
  if (!strcmp(key, "motor1.pwm_lim")) { snprintf(out, outLen, "%d", m->_pwmLim1); return true; }

  if (!strcmp(key, "motor.hz")) { snprintf(out, outLen, "%u", m->_hz); return true; }
  if (!strcmp(key, "motor.link")) { snprintf(out, outLen, "%u", (unsigned)m->_link); return true; }
if (!strcmp(key, "motor.link_scale")) {
#if defined(ARDUINO_ARCH_AVR)
  dtostrf(m->_linkScale, 0, 4, out);
#else
  snprintf(out, outLen, "%.4f", (double)m->_linkScale);
#endif
  return true;
}
if (!strcmp(key, "motor.link_offset")) { snprintf(out, outLen, "%ld", (long)m->_linkOffset); return true; }


  return false;
}

bool DualMotorModule::setParam(UniProto&, const char* key, const char* value, void* ctx) {
  DualMotorModule* m = (DualMotorModule*)ctx;

  if (!strcmp(key, "motor0.pwm")) {
    m->_cmd0 = clampi16(UniProto::parseInt(value), -255, 255);
    return true;
  }
  if (!strcmp(key, "motor1.pwm")) {
    m->_cmd1 = clampi16(UniProto::parseInt(value), -255, 255);
    return true;
  }

  if (!strcmp(key, "motor0.enable")) { m->_en0 = UniProto::parseInt(value); return true; }
  if (!strcmp(key, "motor1.enable")) { m->_en1 = UniProto::parseInt(value); return true; }

  if (!strcmp(key, "motor0.kp")) { m->_kp0 = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "motor0.ki")) { m->_ki0 = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "motor0.kd")) { m->_kd0 = UniProto::parseFloat(value); return true; }

  if (!strcmp(key, "motor1.kp")) { m->_kp1 = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "motor1.ki")) { m->_ki1 = UniProto::parseFloat(value); return true; }
  if (!strcmp(key, "motor1.kd")) { m->_kd1 = UniProto::parseFloat(value); return true; }

  if (!strcmp(key, "motor0.set")) {
  m->_set0 = (int32_t)UniProto::parseInt(value);
  return true;
}
if (!strcmp(key, "motor1.set")) {
  m->_set1 = (int32_t)UniProto::parseInt(value);
  return true;
}

if (!strcmp(key, "motor0.pwm_lim")) {
  m->_pwmLim0 = clampi16(UniProto::parseInt(value), 0, 255);
  return true;
}
if (!strcmp(key, "motor1.pwm_lim")) {
  m->_pwmLim1 = clampi16(UniProto::parseInt(value), 0, 255);
  return true;
}


  if (!strcmp(key, "motor.hz")) { m->_hz = clampi16(UniProto::parseInt(value), 10, 500); return true; }
if (!strcmp(key, "motor.link")) {
  long v = UniProto::parseInt(value);
  if (v < 0) v = 0;
  if (v > 4) v = 4;

  const uint8_t newLink = (uint8_t)v;

  // Track old enables so we can reset integrators on transitions
  const bool oldEn0 = m->_en0;
  const bool oldEn1 = m->_en1;

  m->_link = newLink;

  // Default enable behavior per mode:
  // 0: no change
  // 1: m0 follows m1 => m0 PID ON,  m1 PID OFF
  // 2: m1 follows m0 => m1 PID ON,  m0 PID OFF
  // 3: bidir hard link => both ON
  // 4: spring-damper => both ON
  if (m->_link == 1) {
    m->_en0 = true;
    m->_en1 = false;

    // Make leader passive immediately
    m->_cmd1 = 0;
    m->applyMotor(m->_cfg.pwm1, m->_cfg.dir1, 0);
  } else if (m->_link == 2) {
    m->_en1 = true;
    m->_en0 = false;

    m->_cmd0 = 0;
    m->applyMotor(m->_cfg.pwm0, m->_cfg.dir0, 0);
  } else if (m->_link == 3 || m->_link == 4) {
    m->_en0 = true;
    m->_en1 = true;
  } else {
    // link == 0: leave enables unchanged
  }

  // Reset integrators / last error if enable state changed
  if (oldEn0 != m->_en0) {
    m->_i0 = 0.0f;
    m->_lastErr0 = 0.0f;
  }
  if (oldEn1 != m->_en1) {
    m->_i1 = 0.0f;
    m->_lastErr1 = 0.0f;
  }

  return true;
}



if (!strcmp(key, "motor.link_scale")) { m->_linkScale = UniProto::parseFloat(value); return true; }
if (!strcmp(key, "motor.link_offset")) { m->_linkOffset = (int32_t)UniProto::parseInt(value); return true; }


  return false;
}

// ---------- actions ----------
bool DualMotorModule::doZero(UniProto&, const char*, const char*, Stream& out, void* ctx) {
  DualMotorModule* m = (DualMotorModule*)ctx;
  noInterrupts();
  m->_pos0 = m->_pos1 = 0;
  interrupts();
  m->_set0 = m->_set1 = 0;
  m->_cmd0 = m->_cmd1 = 0;
  out.println(F("motor.zero"));
  return true;
}

bool DualMotorModule::doStop(UniProto&, const char*, const char*, Stream& out, void* ctx) {
  DualMotorModule* m = (DualMotorModule*)ctx;
  m->_en0 = m->_en1 = false;
  m->_cmd0 = m->_cmd1 = 0;
  m->applyMotor(m->_cfg.pwm0, m->_cfg.dir0, 0);
  m->applyMotor(m->_cfg.pwm1, m->_cfg.dir1, 0);
  out.println(F("motor.stop"));
  return true;
}

// ---------- encoder ISRs ----------
void DualMotorModule::isrEnc0() { if (_inst) _inst->handleEnc0(); }
void DualMotorModule::isrEnc1() { if (_inst) _inst->handleEnc1(); }

inline void DualMotorModule::handleEnc0() {
  const uint8_t a = digitalRead(_cfg.encA0);
  const uint8_t b = digitalRead(_cfg.encB0);
  if (a == b) _pos0++; else _pos0--;
}

inline void DualMotorModule::handleEnc1() {
  const uint8_t a = digitalRead(_cfg.encA1);
  const uint8_t b = digitalRead(_cfg.encB1);
  if (a == b) _pos1++; else _pos1--;
}

int32_t DualMotorModule::readPos0() const { noInterrupts(); int32_t v = _pos0; interrupts(); return v; }
int32_t DualMotorModule::readPos1() const { noInterrupts(); int32_t v = _pos1; interrupts(); return v; }

// ---------- PID ----------
int16_t DualMotorModule::pidStep0(float dt, int32_t pos) {
  const float err = (float)(_set0 - pos);
  _i0 += err * dt;
  _i0 = constrain(_i0, -10000.0f, 10000.0f);
  const float d = (err - _lastErr0) / dt;
  _lastErr0 = err;
  float u = _kp0 * err + _ki0 * _i0 + _kd0 * d;
  return clampi16((int32_t)u, -_pwmLim0, _pwmLim0);
}

int16_t DualMotorModule::pidStep1(float dt, int32_t pos) {
  const float err = (float)(_set1 - pos);
  _i1 += err * dt;
  _i1 = constrain(_i1, -10000.0f, 10000.0f);
  const float d = (err - _lastErr1) / dt;
  _lastErr1 = err;
  float u = _kp1 * err + _ki1 * _i1 + _kd1 * d;
  return clampi16((int32_t)u, -_pwmLim1, _pwmLim1);
}

// ---------- motor drive ----------
void DualMotorModule::applyMotor(uint8_t pinA, uint8_t pinB, int16_t cmd) {
  if (_cfg.driveMode == Config::DriveMode::DIR_PWM) {
    if (cmd == 0) {
      digitalWrite(pinB, LOW);
      analogWrite(pinA, 0);
      return;
    }

    const bool isM0 = (pinA == _cfg.pwm0);
    bool dirHigh = (cmd >= 0);
    if ((isM0 && _cfg.invertDir0) || (!isM0 && _cfg.invertDir1)) {
      dirHigh = !dirHigh;
    }

    uint8_t mag = (uint8_t)abs(cmd);
    digitalWrite(pinB, dirHigh ? HIGH : LOW);

    uint8_t pwmOut = mag;
    if (_cfg.invertPwmOnDirHigh && dirHigh) pwmOut = 255 - mag;

    analogWrite(pinA, pwmOut);
    return;
  }

  // IN1/IN2
  if (cmd == 0) {
    digitalWrite(pinA, LOW);
    digitalWrite(pinB, LOW);
    return;
  }

  uint8_t mag = (uint8_t)abs(cmd);
  if (cmd > 0) {
    analogWrite(pinA, mag);
    digitalWrite(pinB, LOW);
  } else {
    digitalWrite(pinA, LOW);
    analogWrite(pinB, mag);
  }
}

void DualMotorModule::setupPwm() {
  if (_cfg.pwmHz == 0) return;

#if defined(ARDUINO_ARCH_AVR)
  // UNO/Nano (ATmega328P): pins 10/11 are Timer1 (OC1B/OC1A).
  // We'll configure Timer1 for 8-bit fast PWM, TOP=0x00FF, prescaler=1 (~31.372 kHz).
  // This affects ONLY pins 9 and 10 on Uno (Timer1 outputs). Pin 11 is Timer2 on Uno.
  //
  // IMPORTANT for your wiring:
  // - You said PWM pins are 10 and 11.
  // - Pin 10 will be ~31kHz after this.
  // - Pin 11 is Timer2; we optionally configure Timer2 too (also ~31kHz).

  // --- Timer1 (pins 9,10) ---
  // Fast PWM 8-bit: WGM10=1, WGM11=0, WGM12=1, WGM13=0  => mode 5
  // Non-inverting on OC1A/OC1B: COM1A1=1, COM1B1=1
  // Prescaler = 1: CS10=1
  TCCR1A = (1 << WGM10) | (1 << COM1A1) | (1 << COM1B1);
  TCCR1B = (1 << WGM12) | (1 << CS10);

  // --- Timer2 (pins 3,11) ---
  // Fast PWM: WGM20=1, WGM21=1 => mode 3
  // Non-inverting on OC2A/OC2B: COM2A1=1, COM2B1=1
  // Prescaler = 1: CS20=1 => ~31.372 kHz
  //
  // NOTE: This will affect PWM on pins 3 and 11.
  // You use pin 3 for encoder interrupt (digitalRead), that's fine.
  TCCR2A = (1 << WGM20) | (1 << WGM21) | (1 << COM2A1) | (1 << COM2B1);
  TCCR2B = (1 << CS20);

  (void)_cfg; // silence unused if needed

#elif defined(ARDUINO_ARCH_RP2040)
  // Earle Philhower RP2040 core provides analogWriteFreq()
  // Set global PWM frequency (applies to subsequent analogWrite on pins).
  analogWriteFreq(_cfg.pwmHz);
  // Optionally set resolution (default is 8-bit on many cores; leave as-is)
  // analogWriteRange(255);

#else
  // Other cores: no-op (keep default PWM settings)
#endif
}

void DualMotorModule::updateLinkedSetpoints(int32_t pos0, int32_t pos1) {
  switch (_link) {
    case 1: // motor0 follows motor1
      _set0 = (int32_t)(pos1 * _linkScale) + _linkOffset;
      break;
    case 2: // motor1 follows motor0
      _set1 = (int32_t)(pos0 * _linkScale) + _linkOffset;
      break;
    case 3: { // bidirectional
      const int32_t s0 = (int32_t)(pos1 * _linkScale) + _linkOffset;
      const int32_t s1 = (int32_t)(pos0 * _linkScale) + _linkOffset;
      _set0 = s0;
      _set1 = s1;
      break;
    }
    default:
      break; // link off
  }
}
