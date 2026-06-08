#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// MMA7260 3-axis accelerometer — analog outputs X=A0, Y=A1, Z=A2.
// g-select pin wired to GND → ±1.5g range, sensitivity ~800 mV/g @ 3.3V.
// Sleep pin pulled HIGH (active).
//
// Modes (!adc.mode):  0 raw   1 volts   2 avg raw   3 avg volts
// For g values use volts mode and post-process in Python:
//   g = (V - Vzero) / sensitivity   (Vzero ≈ Vcc/2 ≈ 1.65 V @ 3.3V)
//
// Useful commands:
//   !stream:1
//   !adc.mode:1                volts output
//   !adc.window:8
//   !rate:100
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "Accelerometer");

static AdcModule::Config makeCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 3;             // X, Y, Z only
    c.channels[0]  = A0;
    c.channels[1]  = A1;
    c.channels[2]  = A2;
    c.vref         = 3.3f;          // MMA7260 runs at 3.3 V
    c.adcMax       = 1023;
    c.avgWindow    = 8;
    c.valuesCount  = 1;
    c.values[0].id   = 1;
    c.values[0].name = "accel";
    c.values[0].schema = "u16,u16,u16";
    c.values[0].units  = "raw,raw,raw";
    c.values[0].selCount = 0; // all 3
    return c;
}

AdcModule adc(makeCfg());

void setup() {
    Serial.begin(115200);
    proto.begin();
    adc.registerWith(proto);
}

void loop() {
    proto.tick();
}
