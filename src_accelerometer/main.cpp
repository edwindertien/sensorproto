#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// MMA7260 3-axis accelerometer — analog outputs X=A0, Y=A1, Z=A2.
//
// Control pins:
//   SLEEP = pin 2  HIGH=active, LOW=sleep
//   GS1   = pin 3  \  g-select (see table below)
//   GS2   = pin 4  /
//
// g-select table:
//   GS1=0 GS2=0 → ±1.5g  sensitivity ~800 mV/g
//   GS1=1 GS2=0 → ±2g    sensitivity ~600 mV/g
//   GS1=0 GS2=1 → ±4g    sensitivity ~300 mV/g
//   GS1=1 GS2=1 → ±6g    sensitivity ~200 mV/g
//
// Currently set to ±1.5g (GS1=0, GS2=0) — change defines below if needed.
//
// Useful commands:
//   !stream:1
//   !adc.mode:0   raw (default, convert in Python)
//   !rate:50
// ─────────────────────────────────────────────────────────────────────────────

#define PIN_SLEEP  2
#define PIN_GS1    3
#define PIN_GS2    4

// g-select: 0,0 = ±1.5g
#define GS1_VAL    LOW
#define GS2_VAL    LOW

UniProto proto(Serial, "Accelerometer");

static AdcModule::Config makeCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 3;
    c.channels[0]  = A0;  // X
    c.channels[1]  = A1;  // Y
    c.channels[2]  = A2;  // Z
    c.vref         = 3.3f;
    c.adcMax       = 1023;
    c.avgWindow    = 8;
    c.valuesCount  = 1;
    c.values[0].id       = 1;
    c.values[0].name     = "accel";
    c.values[0].schema   = "u16,u16,u16";
    c.values[0].units    = "raw,raw,raw";
    c.values[0].selCount = 0;
    return c;
}

AdcModule adc(makeCfg());

void setup() {
    // Wake the sensor and set g-range before reading
    pinMode(PIN_SLEEP, OUTPUT);
    pinMode(PIN_GS1,   OUTPUT);
    pinMode(PIN_GS2,   OUTPUT);
    digitalWrite(PIN_GS1,   GS1_VAL);
    digitalWrite(PIN_GS2,   GS2_VAL);
    digitalWrite(PIN_SLEEP, HIGH);     // active
    delay(1);                          // 1ms wake-up time per datasheet

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(50);
    adc.registerWith(proto);
}

void loop() {
    proto.tick();
}