#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// Wind-speed sensor: simple optical gate — rotating chopper wheel interrupts
// an IR beam. Analog output of the optical receiver on A0 (waveform).
// Optionally a second channel A1 for reference/DC level.
//
// For frequency counting (RPM → m/s) use plot_adc_blocks.py or the block
// stream (!stream:2, !format:bin) and do FFT on the 500 Hz block.
//
// Useful commands:
//   !stream:1                  raw waveform (CSV)
//   !adc.mode:0                raw
//   !rate:200                  up to 200 Hz real-time plot
//   !stream:2  + !format:bin   binary block capture for FFT
// ─────────────────────────────────────────────────────────────────────────────

UniProto proto(Serial, "WindSpeed");

static AdcModule::Config makeCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 2;           // ch0: signal, ch1: reference (optional)
    c.channels[0]  = A0;
    c.channels[1]  = A1;
    c.avgWindow    = 1;
    c.valuesCount  = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "wind";
    c.values[0].schema = "u16,u16";
    c.values[0].units  = "signal,ref";
    c.values[0].selCount = 0;
    // Block stream: channel 0 @ 500 Hz for FFT
    c.block.sourceChanIdx = 0;
    c.block.sampleHz = 500;
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
