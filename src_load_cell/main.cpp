#include <Arduino.h>
#include "UniProto.h"
#include "mod_hx711.h"

// ── Device ────────────────────────────────────────────────────────────────────
// One or two HX711 load cell amplifiers.
// Each has its own stream, scale, and tare — calibrate independently.
//
// Load cell 1 (default):  DOUT=A1, SCK=A0  → stream 1, prefix "hx"
// Load cell 2 (optional): DOUT=A3, SCK=A2  → stream 2, prefix "hx2"
//
// To use only one load cell: comment out hx2 lines below.
//
// ── Calibration procedure ────────────────────────────────────────────────────
// 1. Flash and open visualiser
// 2. Remove all weight from load cell
// 3. Click "zero hx" (or send !hx.zero:1) — captures tare
// 4. Place a known weight (e.g. 500g)
// 5. Read the raw value: ?hx.raw
// 6. Calculate: scale = (raw - tare) / known_weight_in_grams
//    e.g. if raw-tare = 412500 and weight = 500g → scale = 825.0
// 7. Send !hx.scale:825.0
// 8. Verify the reading matches the known weight
// 9. Repeat steps 2-8 for hx2 if using two cells
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "LoadCell");

Hx711Module hx(Hx711Module::defaultUno());   // DOUT=A1, SCK=A0
Hx711Module hx2(Hx711Module::defaultUno2()); // DOUT=A3, SCK=A2

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(5);   // 5 Hz default — HX711 is 10 SPS at normal rate
    hx.registerWith(proto);
    hx2.registerWith(proto);
}

void loop() {
    proto.tick();
}