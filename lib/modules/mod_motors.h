#pragma once
#include <Arduino.h>
#include "UniProto.h"

class DualMotorModule {
public:
  struct Config {
    // Encoder pins
    uint8_t encA0 = 2;  // INT0
    uint8_t encB0 = 4;
    uint8_t encA1 = 3;  // INT1
    uint8_t encB1 = 5;

    // Motor driver pins
    uint8_t pwm0 = 10;
    uint8_t dir0 = 8;
    uint8_t pwm1 = 11;
    uint8_t dir1 = 9;

    // How to drive motor pins:
    // - DIR_PWM: dirPin is direction, pwmPin is enable/PWM
    // - IN1_IN2: pwmPin and dirPin are IN1/IN2 of H-bridge (PWM one side, other LOW)
    enum class DriveMode : uint8_t { DIR_PWM, IN1_IN2 };
    DriveMode driveMode = DriveMode::IN1_IN2;

    // Some L293 wiring ends up inverting PWM when DIR=HIGH.
    // If true: pwmOut = 255 - mag when dir is HIGH.
    bool invertPwmOnDirHigh = true;
    // Set to 0 to keep Arduino defaults.
    // Uno on Timer1 pins (10/11): 31372 Hz works well (prescaler=1, 8-bit fast PWM).
    uint16_t pwmHz = 31372;


    // Optional direction polarity inversion per motor
    bool invertDir0 = false;
    bool invertDir1 = false;

    // Stream ids
    uint8_t streamId = 3;
    uint8_t streamIdRaw = 4;  // raw encoder positions
  };

 static Config defaultUno() {
  Config c;

  // L293 setup (your observed behavior)
  c.driveMode = Config::DriveMode::DIR_PWM;
  c.invertPwmOnDirHigh = true;

  c.pwmHz = 31372; // ultrasonic

  // Your motor0 currently won't reverse without this (based on tests).
  // If it reverses the wrong way, flip these.
  c.invertDir0 = true;
  c.invertDir1 = true;

  return c;
}


  explicit DualMotorModule(const Config& cfg);

  void registerWith(UniProto& proto);
  void poll();

private:
  Config _cfg;
  UniProto* _proto = nullptr;

  // encoder counts (ISR-updated)
  volatile int32_t _pos0 = 0;
  volatile int32_t _pos1 = 0;

  // control state
  bool _en0 = false;
  bool _en1 = false;

  float _kp0 = 0.5f, _ki0 = 0.0f, _kd0 = 0.0f;
  float _kp1 = 0.5f, _ki1 = 0.0f, _kd1 = 0.0f;

  int32_t _set0 = 0;
  int32_t _set1 = 0;

  int16_t _pwmLim0 = 255;
  int16_t _pwmLim1 = 255;

  float _i0 = 0.0f, _i1 = 0.0f;
  float _lastErr0 = 0.0f, _lastErr1 = 0.0f;

  uint16_t _hz = 200;
  uint32_t _lastCtrlUs = 0;

  // linking
  // 0=off, 1: m0 follows m1, 2: m1 follows m0, 3: bidir
  uint8_t _link = 0;
  float   _linkScale = 1.0f;
  int32_t _linkOffset = 0;

  // last command output (for telemetry and open-loop)
  int16_t _cmd0 = 0;
  int16_t _cmd1 = 0;

  // --- Streams ---
  static void emitFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);
  void emit(UniProto& p, uint8_t streamId, UniFrameWriter& w);

  static void emitRawFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);
  void emitRaw(UniProto& p, uint8_t streamId, UniFrameWriter& w);

  // --- Params ---
  static bool getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx);
  static bool setParam(UniProto&, const char* key, const char* value, void* ctx);

  // --- Actions ---
  static bool doZero(UniProto&, const char* action, const char* args, Stream& out, void* ctx);
  static bool doStop(UniProto&, const char* action, const char* args, Stream& out, void* ctx);

  // --- ISR hookup ---
  static DualMotorModule* _inst;
  static void isrEnc0();
  static void isrEnc1();
  inline void handleEnc0();
  inline void handleEnc1();

  // --- helpers ---
  int32_t readPos0() const;
  int32_t readPos1() const;

  // for changing PWM frequency:
  void setupPwm();

  // Drive motor (pinA=_cfg.pwmX, pinB=_cfg.dirX)
  void applyMotor(uint8_t pinA, uint8_t pinB, int16_t cmd);

  // Determine which motor's config applies from pins (used for invertDir0/1)
  inline bool isMotor0Pins(uint8_t pinA, uint8_t pinB) const { return (pinA == _cfg.pwm0 && pinB == _cfg.dir0); }
  inline bool isMotor1Pins(uint8_t pinA, uint8_t pinB) const { return (pinA == _cfg.pwm1 && pinB == _cfg.dir1); }

  int16_t pidStep0(float dt, int32_t pos);
  int16_t pidStep1(float dt, int32_t pos);

  void updateLinkedSetpoints(int32_t pos0, int32_t pos1);
  void setControlHz(uint16_t hz);
};
