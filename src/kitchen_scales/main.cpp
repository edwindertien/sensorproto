#include <Arduino.h>
#include "UniProto.h"
#include "mod_hx711.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Kitchen scales — load cell + HX711.
// Same mod_hx711 module as load_cell, different wiring (DOUT=A1, SCK=A0).
// Calibrated for cooking range (~0..5000 g).
//
// Use plot_load_cell.py for calibration and monitoring.
// Calibration procedure same as load_cell — see README.
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "KitchenScales");

static Hx711Module::Config makeCfg() {
    auto c = Hx711Module::defaultUno();  // DOUT=A1, SCK=A0
    c.gain       = 128;
    c.avgCount   = 4;
    c.streamId   = 1;
    c.streamName = "scale";
    c.units      = "raw,g";
    c.prefix     = "hx";
    return c;
}

Hx711Module hx(makeCfg());

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(5);
    hx.registerWith(proto);
}

void loop() {
    hx.poll();
    proto.tick();
}