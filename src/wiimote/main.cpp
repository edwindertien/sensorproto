#include <Arduino.h>
#include <Wire.h>
#include "UniProto.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Wiimote IR camera (OV7670-derived sensor in Wii remote).
// Interface: I2C, address 0xB0>>1 = 0x58, on shield with 20 MHz crystal.
//
// The camera outputs up to 4 IR blob centroids (x,y,size) at ~100 Hz.
// Initialisation sequence: write specific register bytes to put it in
// basic tracking mode.  Two init sequences are in common use:
//   "Continuous" (0x33, 0x00) — simpler, used here.
//   "Enhanced"   (0x30, 0x01, ...) — more blob data.
//
// Stream 1: up to 4 blobs — x(0..1023), y(0..767), size(0..15) for each.
//           Invalid blobs reported as (1023, 1023, 15).
//
// TODO: verify exact shield I2C address and clock requirements.
//       Shield uses 20 MHz crystal — normal Wire at 400 kHz should work.
// ─────────────────────────────────────────────────────────────────────────────

#define CAM_ADDR  0x58
#define NUM_BLOBS 4

UniProto proto(Serial, "WiimoteCam");

struct Blob { int16_t x, y; uint8_t size; };
static Blob _blobs[NUM_BLOBS];
static bool _initialized = false;

static bool camWrite(uint8_t reg, uint8_t val) {
    Wire.beginTransmission(CAM_ADDR);
    Wire.write(reg);
    Wire.write(val);
    return Wire.endTransmission() == 0;
}

static bool camInit() {
    // Continuous basic mode init sequence (commonly referenced for Wii IR cam)
    bool ok = true;
    ok &= camWrite(0x30, 0x01);
    delay(1);
    ok &= camWrite(0x30, 0x08);
    delay(1);
    ok &= camWrite(0x06, 0x90);
    delay(1);
    ok &= camWrite(0x08, 0xC0);
    delay(1);
    ok &= camWrite(0x1A, 0x40);
    delay(1);
    ok &= camWrite(0x33, 0x33);
    delay(10);
    return ok;
}

static bool readBlobs() {
    Wire.beginTransmission(CAM_ADDR);
    Wire.write(0x36);
    if (Wire.endTransmission() != 0) return false;
    if (Wire.requestFrom((int)CAM_ADDR, 16) != 16) return false;

    for (uint8_t i = 0; i < NUM_BLOBS; i++) {
        uint8_t b0 = Wire.read(), b1 = Wire.read(), b2 = Wire.read(), b3 = Wire.read();
        _blobs[i].x    = (int16_t)(b0 | ((b2 & 0x30) << 4));
        _blobs[i].y    = (int16_t)(b1 | ((b2 & 0xC0) << 2));
        _blobs[i].size = (uint8_t)(b2 & 0x0F);
        (void)b3;
    }
    return true;
}

static void emitCam(UniProto& p, uint8_t sid, UniFrameWriter& w, void* /*ctx*/) {
    if (!_initialized) {
        _initialized = camInit();
        if (!_initialized) return;
    }
    if (!readBlobs()) return;

    w.begin(sid);
    for (uint8_t i = 0; i < NUM_BLOBS; i++) {
        w.i32((int32_t)_blobs[i].x, nullptr);
        w.i32((int32_t)_blobs[i].y, nullptr);
        w.u16(_blobs[i].size, nullptr);
    }
    w.end();
}

static bool doReinit(UniProto&, const char*, const char*, Stream& out, void*) {
    _initialized = false; out.println(F("cam.reinit")); return true;
}

void setup() {
    Serial.begin(115200);
    Wire.begin();
    Wire.setClock(400000);
    proto.begin();
    proto.setRateHz(50);

    // 4 blobs × (x i32, y i32, size u16) = 4×(4+4+2) = 40 bytes
    proto.registerStream({1, "ir.blobs",
        "i32,i32,u16, i32,i32,u16, i32,i32,u16, i32,i32,u16",
        "x0,y0,s0,x1,y1,s1,x2,y2,s2,x3,y3,s3",
        emitCam, nullptr});
    proto.registerAction({"cam.reinit", doReinit, nullptr});
}

void loop() {
    proto.tick();
}
