#pragma once
#include <Arduino.h>
#include <Wire.h>
#include "UniProto.h"

class BldcModule {
public:
  struct Config {
    // ---- I2C ----
    TwoWire* wire = &Wire;

    // AS5600 (angle sensor)
    uint8_t as5600Addr = 0x36;
    uint16_t as5600CountsPerRev = 4096;

    // M5 Unit BLDC Driver (STM32+DRV11873)
    // V1 protocol typically at 0x65; V2 protocol doc shows 0x64.
    enum class DriverProto : uint8_t { V1_ADDR_0x65, V2_ADDR_0x64 };
    DriverProto proto = DriverProto::V1_ADDR_0x65;

    uint8_t driverAddrV1 = 0x65;
    uint8_t driverAddrV2 = 0x64;

    // Motor specifics
    uint8_t polePairs = 7; // 14 poles -> 7 pole pairs

    // ---- Stream ----
    uint8_t streamId = 6;
    const char* streamName = "bldc";
    // CSV/plotter fields: pos(rad), vel(rad/s), set, cmd, mode, src, rpm_fb
    const char* schema = "f32,f32,f32,i16,u8,u8,f32";
    const char* units  = "rad,rad/s,rad,cmd,mode,src,rpm";

    // ---- Timing ----
    uint16_t controlHz = 500;

    // ---- Output mapping (external loop -> open-loop PWM on driver) ----
    // M5 V1 open-loop PWM range: 0..2047 :contentReference[oaicite:3]{index=3}
    uint16_t pwmMax = 2047;
    int16_t  cmdLimit = 255;   // your internal effort command range

    // optional inversion
    bool invert = false;
  };

  static Config defaultUno() { return Config{}; }

  explicit BldcModule(const Config& cfg);

  void registerWith(UniProto& proto);

  // call often from loop()
  void poll();

private:
  Config _cfg;
  UniProto* _proto = nullptr;
  TwoWire* _w = nullptr;

  // ----- control source -----
  // 0: External (AS5600) haptics loop -> driver open-loop PWM
  // 1: STM32 driver closed-loop speed
  // 2: STM32 driver closed-loop position (only V2)
  uint8_t _src = 0;

  bool _enable = false;


  // cache last values we actually sent to the driver (V1)
uint8_t  _v1_lastMode = 255;
uint8_t  _v1_lastDir  = 255;
uint16_t _v1_lastPwm  = 0xFFFF;
  // --- AS5600 unwrapped position (counts) ---
  int32_t _posCounts = 0;
  uint16_t _lastRaw = 0;
  bool _haveLast = false;

  // velocity LPF
  float _velCounts = 0.0f;
  float _velAlpha  = 0.25f;

  // --- loop timing ---
  uint32_t _lastUs = 0;
  uint16_t _hz = 500;

  // --- external haptics modes (when src=0) ---
  // 0=open-loop (bldc.cmd)
  // 1=PID position (bldc.set)
  // 2=spring-damper around set
  // 3=endstops
  // 4=detents
  uint8_t _mode = 0;

  int16_t _cmd = 0;     // signed effort
  float _setRad = 0.0f; // position setpoint (rad)

  // PID (external)
  float _kp = 2.0f, _ki = 0.0f, _kd = 0.0f;
  float _i = 0.0f, _iLim = 200.0f;
  float _lastErr = 0.0f;

  // spring-damper
  float _springK = 5.0f;
  float _dampB   = 0.2f;

  // endstops
  float _minRad = -3.14159f;
  float _maxRad =  3.14159f;
  float _stopK  = 10.0f;
  float _stopB  = 0.3f;

  // detents
  float _detentStep = 0.2f;
  float _detentK = 6.0f;
  float _detentB = 0.15f;

  // ---- STM32 driver setpoints ----
  float _rpmSet = 0.0f;     // speed mode setpoint (rpm)
  float _posSet = 0.0f;     // position mode setpoint (units depend on V2 doc; we use "deg" or "counts"? see notes)

  // driver PID (we only support V1 x100 here directly; V2 scaling differs)
  float _drvP = 0.50f, _drvI = 0.00f, _drvD = 0.00f;

  // feedback
  float _rpmFb = 0.0f;

  // ---- streams ----
  static void emitFn(UniProto& p, uint8_t streamId, UniFrameWriter& w, void* ctx);
  void emit(UniProto& p, UniFrameWriter& w);

  // ---- params/actions ----
  static bool getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx);
  static bool setParam(UniProto&, const char* key, const char* value, void* ctx);

  static bool doZero(UniProto&, const char* action, const char* args, Stream& out, void* ctx);
  static bool doStop(UniProto&, const char* action, const char* args, Stream& out, void* ctx);

  // ---- helpers: AS5600 ----
  bool readAs5600Raw(uint16_t& outRaw);
  void updatePosition(float dt);
  float countsToRad(int32_t c) const;

  // ---- helpers: external control ----
  void resetIntegrator();
  int16_t clampCmd(int16_t c) const;
  int16_t computeExternalEffort(float dt, float posRad, float velRad);

  // ---- helpers: driver I2C ----
  uint8_t driverAddr() const;

  bool i2cWrite(uint8_t addr, uint8_t reg, const uint8_t* data, uint8_t n);
  bool i2cRead (uint8_t addr, uint8_t reg, uint8_t* data, uint8_t n);

  // V1 (0x65) ops (from 2023/12/5 protocol) :contentReference[oaicite:4]{index=4}
  bool drvV1_setMode(uint8_t mode0_open1_closed);
  bool drvV1_setDirection(uint8_t dir0_1);
  bool drvV1_setPolePairs(uint8_t polePairs);
  bool drvV1_setOpenLoopPwm(uint16_t pwm0_2047);
  bool drvV1_setRpmX100(int32_t rpm_x100);
  bool drvV1_setPidX100(float p, float i, float d);
  bool drvV1_readRpmFloat(float& rpm);

  // V2 (0x64) ops (from 2024/6/3 protocol) :contentReference[oaicite:5]{index=5}
  bool drvV2_setOutput(bool on);
  bool drvV2_setMode(uint8_t mode1_speed2_pos3_current4_encoder);
  bool drvV2_setSpeedX100(int32_t speed_x100);
  bool drvV2_setPositionX100(int32_t pos_x100);
  bool drvV2_readSpeedX100(int32_t& speed_x100);

  // unified: apply command to driver based on src
  void driverEnable(bool en);
  void driverApplyExternalEffort(int16_t effort);
  void driverApplySpeedRpm(float rpm);
  void driverApplyPosition(float posUser);
};
