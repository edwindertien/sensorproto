#include <Arduino.h>
#include "UniProto.h"
#include "mod_synchro.h"

// ── DEBUG STEP 2 ──────────────────────────────────────────────────────────────
// Bare UniProto confirmed working at 115200 (step 1 passed).
// Now adding mod_synchro back in to see if Timer0/Timer1/Timer2 hijacking
// breaks communication, as suspected.
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "Synchro");
SynchroModule synchro(SynchroModule::defaultUno());

void setup() {
    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(2);
    synchro.registerWith(proto);
    synchro.begin();       // starts Timer0/1/2 hijack — watch for comms breaking
}

void loop() {
    proto.tick();
}