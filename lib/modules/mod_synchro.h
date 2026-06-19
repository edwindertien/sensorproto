#pragma once
#include <Arduino.h>
#include "UniProto.h"

// Synchro transformer driver — 3-phase PWM excitation + filtered receiver input.
//
// Generates a 3-phase sine wave on pins 9, 5, 10 (0°, 120°, 240°) at 100Hz
// using a 48-sample sine table clocked by Timer2 at 5kHz (48 samples/cycle).
// Simultaneously samples the receiver coil on an analog pin in the same ISR,
// capturing exactly 480 samples = 10 full cycles per frame.
//
// Hardware:
//   Pin 9  -> 1k + 10uF RC filter -> phase A (0°)   excitation output
//   Pin 5  -> 1k + 10uF RC filter -> phase B (120°)  excitation output
//   Pin 10 -> 1k + 10uF RC filter -> phase C (240°)  excitation output
//   Receiver coil -> (selectable 100nF cap) -> analog input pin
//
// Two outputs:
//   Stream "syn.angle" — single f32 angle in degrees, computed via
//     cross-correlation of the captured frame against the reference sine.
//   Stream "syn.frame" — full 480-sample raw capture, chunked, for use as
//     a low-frequency oscilloscope / insight into signal quality.
//
// Timer2 is fully owned by this module (TCCR2A/B, TIMSK2, TCNT2) — do not
// use Timer2 elsewhere in a sketch that includes this module (this also
// means analogWrite() on pins 3 and 11 will not work as expected, since
// those share Timer2 on most AVR boards).

#define SYNCHRO_FRAME_SAMPLES   480
#define SYNCHRO_SAMPLES_PER_CYCLE 48
#define SYNCHRO_CHUNK_SAMPLES   60   // 480 / 60 = 8 chunks per frame

class SynchroModule {
public:
    struct Config {
        uint8_t pinA = 9;    // 0°   phase output (PWM)
        uint8_t pinB = 5;    // 120° phase output (PWM)
        uint8_t pinC = 10;   // 240° phase output (PWM)
        uint8_t pinIn = A1;  // receiver coil input

        uint8_t streamAngleId   = 1;
        const char* streamAngleName = "syn.angle";

        uint8_t streamFrameId   = 2;
        const char* streamFrameName = "syn.frame";
    };

    static Config defaultUno() { return Config{}; }

    explicit SynchroModule(const Config& cfg);

    void registerWith(UniProto& proto);
    void begin();   // call once from setup() — configures Timer2 and starts ISR

    // Must be a free function / static for the ISR to call into.
    // Call this once globally; only one SynchroModule instance is supported
    // per sketch (Timer2 is a singleton resource on AVR).
    static void isrHandler();

private:
    Config _cfg;

    static SynchroModule* _activeInstance;  // Timer2 ISR needs a global hook

    // sine excitation table (0..255), 48 samples/cycle
    uint8_t  _sineTable[SYNCHRO_SAMPLES_PER_CYCLE];

    // capture buffer — one full frame (480 samples)
    volatile uint8_t  _capture[SYNCHRO_FRAME_SAMPLES];
    volatile uint16_t _writeIdx   = 0;
    volatile uint16_t _frameCount = 0;   // increments each completed frame

    // frame transmission state (non-ISR context)
    uint16_t _frameId      = 0;
    uint16_t _txFrameId    = 0;
    uint16_t _txOffset     = 0;
    bool     _txPending    = false;
    uint16_t _lastSeenFrameCount = 0;

    // angle result (computed in emitAngle, not in ISR)
    float _angleDeg = 0.0f;
    float _offsetDeg = 0.0f;   // user-settable zero offset

    void buildSineTable();
    void onTimerTick();   // called from the static ISR via _activeInstance

    static void emitAngleFn(UniProto& p, uint8_t sid, UniFrameWriter& w, void* ctx);
    void emitAngle(UniProto& p, uint8_t sid, UniFrameWriter& w);

    static void emitFrameFn(UniProto& p, uint8_t sid, UniFrameWriter& w, void* ctx);
    void emitFrame(UniProto& p, uint8_t sid, UniFrameWriter& w);

    static bool getParam(UniProto&, const char* key, char* out, size_t outLen, void* ctx);
    static bool setParam(UniProto&, const char* key, const char* value, void* ctx);

    float computeAngle();   // cross-correlation against sine table
};