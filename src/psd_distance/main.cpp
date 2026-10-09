#include <Arduino.h>
#include "UniProto.h"
#include "mod_psd.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Sharp GP2Y0A710K0F (2Y0A710) long-range PSD — 100..550 cm
// Analog out on A0.
//
// Modes (!psd.mode):
//   0 raw u16   1 volts   2 avg raw   3 avg volts   4 cm   5 avg cm
//
// Useful commands:
//   !stream:5
//   !psd.mode:4                cm output
//   !psd.window:8              8-sample average
//   ?psd.cal_a                 show calibration constant A
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "PSDDistance");
PsdModule psd(PsdModule::defaultUnoA0());

void setup() {
    Serial.begin(115200);
    proto.begin();
    psd.registerWith(proto);
}

void loop() {
    proto.tick();
}
