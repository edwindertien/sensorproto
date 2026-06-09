#pragma once
#include <Arduino.h>
#include "UniProto.h"

// HX711 24-bit ADC amplifier module.
// Bit-banged serial, no library dependency.
// Shared by: load_cell, kitchen_scales, pneumatic.
//
// Gain/channel selection via extra SCK pulses after 24-bit read:
//   1 pulse  → ch A gain 128  (default)
//   2 pulses → ch B gain 32
//   3 pulses → ch A gain 64
//
// Stream CSV: raw(i32), tared_units(f32)
// Units depend on scale factor — grams, Newtons, kg, etc.

class Hx711Module {
public:
    struct Config {
        // Pins
        uint8_t pinDout = A1;
        uint8_t pinSck  = A0;

        // Gain/channel: 128, 64 (ch A), or 32 (ch B)
        uint8_t gain = 128;

        // Stream
        uint8_t     streamId   = 1;
        const char* streamName = "load";
        const char* units      = "raw,g";   // update to "raw,N" or "raw,kg" as needed

        // Initial calibration (override after tare + known weight)
        float    scale     = 1.0f;    // counts per unit (grams, N, kg...)
        int32_t  tare      = 0;       // raw zero offset

        // Averaging: number of readings to average per emit (1 = no averaging)
        uint8_t  avgCount  = 4;

        // Param name prefix — allows two HX711s in one sketch
        // e.g. "hx" → params hx.scale, hx.tare, hx.zero, hx.units
        //      "hx2" → params hx2.scale, hx2.tare, etc.
        const char* prefix = "hx";
    };

    static Config defaultUno() { return Config{}; }

    static Config defaultUno2() {
        Config c;
        c.pinDout   = A3;
        c.pinSck    = A2;
        c.streamId  = 2;
        c.streamName = "load2";
        c.prefix    = "hx2";
        return c;
    }

    explicit Hx711Module(const Config& cfg);

    void registerWith(UniProto& proto);

    // Call from loop() if you want faster sampling than the stream rate.
    // Optional — proto.tick() calls the stream emitter which reads on demand.
    void poll();

    // Direct access for calibration
    int32_t  readRaw();
    bool     isReady() const;
    float    toUnits(int32_t raw) const;

private:
    Config   _cfg;
    int32_t  _last     = 0;
    bool     _ready   = false;
    int64_t  _avgAcc = 0;   // accumulator for non-blocking averaging
    uint8_t  _avgN   = 0;   // samples collected so far

    // param name buffers (built from prefix in constructor)
    char _keyScale[16];
    char _keyTare[16];
    char _keyZero[16];
    char _keyAvg[16];
    char _keyRaw[16];

    int32_t  readOnce();
    int32_t  readAvg(uint8_t n);
    void     setPulses();   // configure gain/channel

    static void emitFn(UniProto& p, uint8_t sid, UniFrameWriter& w, void* ctx);
    void emit(UniProto& p, uint8_t sid, UniFrameWriter& w);

    static bool getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx);
    static bool setParam(UniProto&, const char* key, const char* value, void* ctx);
};