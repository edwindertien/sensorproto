#include <Arduino.h>
#include "UniProto.h"
#include "mod_adns2610.h"

// ── Device ────────────────────────────────────────────────────────────────────
// A2610 optical mouse sensor, bit-banged serial on A4/A5.
// Streams: adns.motion (stream 6)  — dx,dy counts
//          adns.frame  (stream 7)  — 18×18 px grayscale image
//
// Useful commands once connected:
//   ?                          caps
//   !stream:6                  motion only
//   !stream:7                  (then) !adns.capture:1   grab a frame
//   !adns.motion_on:0          stop motion to free bandwidth during frame read
//   !format:ap                 switch to Arduino Serial Plotter
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "OpticalMouse");
Adns2610Module adns(Adns2610Module::defaultUno());

void setup() {
    Serial.begin(115200);
    proto.begin();
    adns.registerWith(proto);
}

void loop() {
    proto.tick();
}
