#include <Arduino.h>
#include "UniProto.h"
#include "mod_hx711.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Single HX711 load cell amplifier, channel A (gain 128).
// DOUT=A3, SCK=A2
//
// ── Calibration procedure ────────────────────────────────────────────────────
// 1. Flash and open plot_load_cell.py
// 2. Remove all weight → click "zero" (captures tare)
// 3. Place a known weight (e.g. 500 g)
// 4. Enter known weight in box → click "calc scale"
// 5. Click "verify" to confirm
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "LoadCell");

static Hx711Module::Config makeCfg() {
    auto c = Hx711Module::defaultUno2();  // DOUT=A3, SCK=A2
    c.gain       = 128;
    c.avgCount   = 4;
    c.streamId   = 1;
    c.streamName = "load";
    c.units      = "raw,g";
    c.prefix     = "hx";   // use "hx" not "hx2"
    return c;
}

Hx711Module hx(makeCfg());

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(10);
    hx.registerWith(proto);
}

void loop() {
    hx.poll();    // non-blocking averaging accumulation
    proto.tick();
}