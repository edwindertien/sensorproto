#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Grove biosensors: GSR (galvanic skin response) on A0,
//                   ear-clip heart rate on A1.
//
// GSR: higher ADC value = lower skin resistance (higher conductance).
//      Good baseline rate: 10 Hz, no averaging.
// Heart rate: optical pulse. Sample at 100 Hz, filter in Python.
//
// Useful commands:
//   !stream:1                  start
//   !rate:100                  100 Hz for heart rate
//   !adc.mode:1                volts (easier to compare)
//   !adc.window:1              no averaging — keep pulse shape
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "Biosensors");

static AdcModule::Config makeCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 2;
    c.channels[0]  = A0; // GSR
    c.channels[1]  = A1; // heart rate
    c.vref         = 5.0f;
    c.avgWindow    = 1;  // no averaging — keep waveform shape
    c.valuesCount  = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "bio";
    c.values[0].schema = "u16,u16";
    c.values[0].units  = "gsr,hr";
    c.values[0].selCount = 0;
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
