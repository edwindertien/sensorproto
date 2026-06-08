#include <Arduino.h>
#include <MIDIUSB.h>
#include "UniProto.h"
#include "mod_adc.h"

// ── Device ────────────────────────────────────────────────────────────────────
// 4× piezo pressure sensors on Arduino Leonardo.
// MIDI output via MIDIUSB (Leonardo has native USB).
// Also streams raw ADC for analysis via UniProto (Serial1 = hardware UART).
//
// Piezo wiring: A0..A3, each with 1 MΩ bleed resistor to GND.
// MIDI note mapping: A0=C3 A1=D3 A2=E3 A3=G3 (adjust in MIDI_NOTE[]).
//
// NOTE: Leonardo Serial1 (TX=1, RX=0) is used for UniProto because
//       Serial (USB CDC) is shared with MIDI class on Leonardo.
//       Connect a USB-serial adapter to TX/RX for streaming.
//       Alternatively, switch to UniProto(Serial, ...) and disable MIDIUSB
//       if you only need data logging without MIDI output.
//
// Params:
//   !midi.threshold:100        velocity threshold (0..1023 raw)
//   !midi.channel:1            MIDI channel (1..16)
//   !stream:1                  ADC raw stream
// ─────────────────────────────────────────────────────────────────────────────

#define NUM_PIEZO 4
const uint8_t PIEZO_PINS[NUM_PIEZO] = {A0, A1, A2, A3};
const uint8_t MIDI_NOTE[NUM_PIEZO]  = {48, 50, 52, 55}; // C3 D3 E3 G3

UniProto proto(Serial1, "PiezoMIDI"); // Serial1 = UART on Leonardo

static uint16_t _threshold = 100;
static uint8_t  _midiCh    = 0;    // 0-indexed (channel 1)
static bool     _noteOn[NUM_PIEZO] = {};
static uint32_t _noteOnMs[NUM_PIEZO] = {};
#define NOTE_OFF_MS 80

static AdcModule::Config makeAdcCfg() {
    auto c = AdcModule::defaultUno();
    c.channelCount = 4;
    for (uint8_t i = 0; i < 4; i++) c.channels[i] = PIEZO_PINS[i];
    c.avgWindow   = 1;
    c.valuesCount = 1;
    c.values[0].id     = 1;
    c.values[0].name   = "piezo";
    c.values[0].schema = "u16,u16,u16,u16";
    c.values[0].units  = "p0,p1,p2,p3";
    c.values[0].selCount = 0;
    return c;
}
AdcModule rawAdc(makeAdcCfg());

static bool getMidi(UniProto&, const char* key, char* out, size_t outLen, void*) {
    if (!strcmp(key, "midi.threshold")) { snprintf(out, outLen, "%u", (unsigned)_threshold); return true; }
    if (!strcmp(key, "midi.channel"))   { snprintf(out, outLen, "%u", (unsigned)(_midiCh+1)); return true; }
    return false;
}
static bool setMidi(UniProto&, const char* key, const char* value, void*) {
    if (!strcmp(key, "midi.threshold")) { _threshold = (uint16_t)UniProto::parseInt(value); return true; }
    if (!strcmp(key, "midi.channel")) {
        long v = UniProto::parseInt(value) - 1;
        if (v < 0) v = 0; if (v > 15) v = 15;
        _midiCh = (uint8_t)v; return true;
    }
    return false;
}

void setup() {
    Serial1.begin(115200);
    proto.begin();
    proto.setRateHz(100);
    rawAdc.registerWith(proto);
    proto.registerParam({"midi.threshold", UniProto::ParamType::INT32, getMidi, setMidi, nullptr});
    proto.registerParam({"midi.channel",   UniProto::ParamType::INT32, getMidi, setMidi, nullptr});
}

void loop() {
    proto.tick();

    uint32_t now = millis();
    for (uint8_t i = 0; i < NUM_PIEZO; i++) {
        uint16_t v = (uint16_t)analogRead(PIEZO_PINS[i]);

        // Note on: peak detected above threshold
        if (!_noteOn[i] && v > _threshold) {
            uint8_t vel = (uint8_t)((v > 1023 ? 1023 : v) * 127 / 1023);
            if (vel < 1) vel = 1;
            midiEventPacket_t on = {0x09, (uint8_t)(0x90 | _midiCh), MIDI_NOTE[i], vel};
            MidiUSB.sendMIDI(on);
            MidiUSB.flush();
            _noteOn[i]   = true;
            _noteOnMs[i] = now;
        }

        // Note off: after timeout
        if (_noteOn[i] && (uint32_t)(now - _noteOnMs[i]) >= NOTE_OFF_MS) {
            midiEventPacket_t off = {0x08, (uint8_t)(0x80 | _midiCh), MIDI_NOTE[i], 0};
            MidiUSB.sendMIDI(off);
            MidiUSB.flush();
            _noteOn[i] = false;
        }
    }
}
