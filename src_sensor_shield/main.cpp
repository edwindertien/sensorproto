#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"
#include "mod_motors.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Standard SensorShield — multiple sensors on one board.
//
// Sensors (fill in exact pins from shield doc when available):
//   INA122 load cell amp   → A0
//   Foil pressure sensor   → A1
//   Double hall-effect enc → pins 2,3 (interrupts), 4,5 (B channels)
//   Capacitive slider      → A2
//   Incremental encoder    → pins 18,19 if Mega; or 2,3 on Uno (shared above)
//
// TODO: verify exact pinout from shield documentation.
//       Placeholder wiring used below — adjust before flashing.
//
// Streams:
//   1  adc.shield  — all 6 analog channels raw
//   3  enc         — incremental encoder (DualMotorModule)
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "SensorShield");

// All ADC channels
static AdcModule::Config makeAdcCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 6;
    c.channels[0] = A0; // INA122 load cell
    c.channels[1] = A1; // foil pressure
    c.channels[2] = A2; // cap slider
    c.channels[3] = A3;
    c.channels[4] = A4;
    c.channels[5] = A5;
    c.avgWindow   = 4;
    c.valuesCount = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "adc.shield";
    c.values[0].schema = "u16,u16,u16,u16,u16,u16";
    c.values[0].units  = "load,pres,cap,a3,a4,a5";
    c.values[0].selCount = 0;
    return c;
}
AdcModule shieldAdc(makeAdcCfg());

// Encoder (hall-effect double on INT0/INT1)
static DualMotorModule::Config makeEncCfg() {
    DualMotorModule::Config c;
    c.encA0 = 2; c.encB0 = 4;
    c.encA1 = 3; c.encB1 = 5;
    // Motor driver pins — not connected on this shield; set to unused pins
    c.pwm0 = 6; c.dir0 = 7;
    c.pwm1 = 8; c.dir1 = 9;
    c.streamId    = 3;
    c.streamIdRaw = 4;
    return c;
}
DualMotorModule enc(makeEncCfg());

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);
    shieldAdc.registerWith(proto);
    enc.registerWith(proto);
}

void loop() {
    proto.tick();
    enc.poll(); // runs encoder ISR dispatch; motors have 0 PWM so no drive
}
