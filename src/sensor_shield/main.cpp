#include <Arduino.h>
#include <CapacitiveSensor.h>
#include "UniProto.h"

// ── Sensor Shield ─────────────────────────────────────────────────────────────
// Stream field counts (all unique — allows unambiguous Python parsing):
//   1  analog   : sid(1), A0,A1,A2,A3,A4,A5          = 7 fields
//   2  force    : sid(2), foil_g, strain_g             = 3 fields
//   3  hall     : sid(3), deg                          = 2 fields
//   4  encoder  : sid(4), pos, vel                     = 3 fields  ← different from force by sid
//   5  cap      : sid(5), capA, capB, pos_mm           = 4 fields
//   6  rc       : sid(6), count, ref_v                 = 3 fields  ← sid distinguishes from force/enc
//   7  us       : sid(7), cm                           = 2 fields  ← sid distinguishes from hall
//
// All streams start with their stream ID as a u16. Python parser reads
// the first field as stream ID and dispatches accordingly — no guessing.
//
// Timing:
//   pollFast() at 20Hz: analog, force, hall, encoder (non-blocking ADC)
//   pollSlow() at  5Hz: cap, RC-ADC, ultrasonic (blocking, sequential)
//   pollSlow() worst-case: cap~30ms + RC~20ms + US~30ms = ~80ms < 200ms budget
//
// RC-ADC isolation: D4 is left LOW (discharged) between measurements
//   so it does not inject noise into A0 during analog reads.
//   Force/strain are read in pollFast() only, never during pollSlow().
// ─────────────────────────────────────────────────────────────────────────────

// ── Supply voltage configuration ──────────────────────────────────────────────
// Arduino Vcc = 5V (ADC reference = 5V, digital threshold = 2.5V)
// Sensor shield Vcc = 3.3V (all sensor outputs swing 0..3.3V)
//
// Consequences:
//   ADC full-scale for shield sensors: 3.3/5 × 1023 = 675 counts
//   ADC midpoint for ratiometric sensors (Hall): 675/2 = 338 counts
//   RC-ADC: pot swings 0..3.3V. Digital threshold is 2.5V (Arduino).
//     Charge cycle: cap charges toward pot voltage (max 3.3V > 2.5V threshold)
//     → charge cycle WORKS when pot > 2.5V (counts 0..ADC ~512 range)
//     → charge cycle FAILS when pot < 2.5V (cap never reaches 2.5V)
//     Discharge cycle handles the lower range — cap discharges from 3.3V
//     toward pot voltage, crosses 2.5V when pot < 2.5V.
//   RC reference: scale by SHIELD_V/ADC_FS counts

#define ARDUINO_VCC   5.0f    // Arduino/ADC reference voltage
#define SHIELD_VCC    3.3f    // Sensor shield supply voltage
#define ADC_FS        1023.0f // ADC full scale counts
#define ADC_MID       338     // Shield midpoint in ADC counts (3.3/5 × 1023 / 2)
#define ADC_SHIELD_FS 675     // Shield full scale in ADC counts (3.3/5 × 1023)

CapacitiveSensor csA = CapacitiveSensor(11, 6);
CapacitiveSensor csB = CapacitiveSensor(11, 7);
#define CAP_THRESHOLD 300

// ── Encoder ISR (Timer2, 5kHz) ────────────────────────────────────────────────
volatile int  _enc_pos    = 0;
volatile int  _enc_dA     = 0;
volatile int  _enc_dB     = 0;
volatile long _enc_pul_us = 0;
volatile long _enc_lst_us = 0;

ISR(TIMER2_OVF_vect) {
    TCNT2 = 0xE7;
    int A = digitalRead(2), B = digitalRead(3);
    if ((A==1&&_enc_dA==0&&B==0)||(A==0&&_enc_dA==1&&B==1)||
        (B==1&&_enc_dB==0&&A==1)||(B==0&&_enc_dB==1&&A==0)) {
        _enc_pos++;
        _enc_pul_us = micros()-_enc_lst_us;
        _enc_lst_us = micros();
    } else if ((B==1&&_enc_dB==0&&A==0)||(B==0&&_enc_dB==1&&A==1)||
               (A==1&&_enc_dA==0&&B==1)||(A==0&&_enc_dA==1&&B==0)) {
        _enc_pos--;
        _enc_pul_us = micros()-_enc_lst_us;
        _enc_lst_us = micros();
    }
    _enc_dA=A; _enc_dB=B;
}

// ── Cached values ─────────────────────────────────────────────────────────────
static uint16_t _a[6]        = {0};
static float    _foil_g      = 0;
static float    _strain_g    = 0;
static float    _hall_deg    = 0;
static int      _enc_p       = 0;
static float    _enc_v       = 0;
static float    _capA        = 0;
static float    _capB        = 0;
static float    _cap_pos     = -1;
static uint16_t _rc_count    = 0;
static float    _rc_ref      = 0;
static float    _us_cm       = 0;

static float _hall_prev = 0, _hall_off = 0;

// ── Poll: fast sensors (non-blocking) ─────────────────────────────────────────
static void pollFast() {
    // Read all analog channels once — D4 is LOW so no RC noise on A0
    for (uint8_t i = 0; i < 6; i++) _a[i] = (uint16_t)analogRead(i);

    // Foil: inverse calibration (original used 850000/raw - 835 for 5V)
    // Scale raw to equivalent 5V reading first: raw_5v = raw × (5/3.3)
    _foil_g   = (_a[2] > 20) ? (850000.0f / (_a[2] * ARDUINO_VCC / SHIELD_VCC) - 835.0f) : 0.0f;
    // Strain: linear, full scale 500g at shield full-scale ADC counts
    _strain_g = 500.0f * _a[3] / ADC_SHIELD_FS;

    // Hall: exact copy of original Sensors_5 algorithm
    float pA = (float)analogRead(A4) - ADC_MID;
    float pB = (float)analogRead(A5) - ADC_MID;
    float ang = (360.0f/(2.0f*(float)PI)) * atan2f(pA, pB);
    // Original uses (previousangle - angle), not (angle - previous)
    if ((_hall_prev - ang) >  180.0f) _hall_off += 360.0f;
    if ((_hall_prev - ang) < -180.0f) _hall_off -= 360.0f;
    _hall_prev = ang;
    _hall_deg  = (ang + _hall_off) * (270.0f/1440.0f);

    // Encoder: read volatile atomically
    noInterrupts();
    _enc_p = _enc_pos;
    long pul = _enc_pul_us;
    interrupts();
    _enc_v = (pul > 0 && pul < 2000000L) ? 1e6f/(float)pul : 0.0f;
}

// ── Poll: slow sensors (blocking — run at 5Hz only) ──────────────────────────
static void pollCap() {
    // CapacitiveSensor uses delayMicroseconds internally.
    // Timer2 ISR still runs during this — encoder keeps counting.
    _capA = (float)csA.capacitiveSensor(10);
    _capB = (float)csB.capacitiveSensor(10);
    bool touch = (_capA + _capB) > CAP_THRESHOLD;
    _cap_pos = touch ? (25.0f + (25.0f/0.9f)*(_capB-_capA)/(_capA+_capB)) : -1.0f;
}

static void pollRC() {
    int valueUp, valueDown;

    // ── Charge cycle ─────────────────────────────────────────────────────────
    // Discharge cap: D4=OUTPUT LOW
    pinMode(4, OUTPUT); digitalWrite(4, LOW);
    delay(15);
    // Read reference voltage (pot on A0) while cap is discharged
    // Scale by Arduino Vcc (5V reference), result is actual voltage 0..3.3V
    _rc_ref = analogRead(A0) * ARDUINO_VCC / ADC_FS;
    // Release D4: cap now charges through 100k toward A0 voltage
    // digitalRead(4) goes HIGH when cap crosses ~Vcc/2 (digital threshold)
    // At 3.3V Arduino: threshold ≈ 1.65V. At 5V: threshold ≈ 2.5V.
    pinMode(4, INPUT);
    valueUp = 10000;
    for (int n = 0; n < 10000; n++) {
        if (digitalRead(4) == HIGH) { valueUp = n; break; }
    }

    // ── Discharge cycle ───────────────────────────────────────────────────────
    // Charge cap fully: D4=OUTPUT HIGH
    pinMode(4, OUTPUT); digitalWrite(4, HIGH);
    delay(15);
    // Release D4: cap now discharges through 100k toward A0 voltage
    // digitalRead(4) goes LOW when cap crosses ~Vcc/2 threshold
    pinMode(4, INPUT);
    valueDown = 10000;
    for (int n = 0; n < 10000; n++) {
        if (digitalRead(4) == LOW) { valueDown = n; break; }
    }

    // Pick whichever cycle completed within the range.
    // When pot > 2.5V: cap charges fast (valueUp valid), discharges slow.
    // When pot < 2.5V: cap discharges fast (valueDown valid), charges slow.
    // When neither completes: return 10000 (out of range).
    if (valueUp < 10000)
        _rc_count = (uint16_t)valueUp;
    else
        _rc_count = (uint16_t)valueDown;

    // Leave discharged to avoid noise on A0 during pollFast()
    pinMode(4, OUTPUT); digitalWrite(4, LOW);
}

static void pollUS() {
    digitalWrite(8, HIGH); delayMicroseconds(10); digitalWrite(8, LOW);
    unsigned long t = pulseIn(12, HIGH, 58000);   // 58ms = ~10m range
    _us_cm = (t > 0) ? t * 0.01715f : 999.0f;    // 0 = timeout, show 999
}

// ── UniProto streams ──────────────────────────────────────────────────────────
UniProto proto(Serial, "SensorShield");

// Each stream prepends its own ID as the first field.
// Python reads first field as stream ID → no ambiguity regardless of count.

static void emitAnalog(UniProto&,uint8_t sid,UniFrameWriter& w,void*) {
    w.begin(sid);
    w.u16(sid,"sid");
    for (uint8_t i=0;i<6;i++) w.u16(_a[i],"raw");
    w.end();
}
static void emitForce(UniProto&,uint8_t sid,UniFrameWriter& w,void*) {
    w.begin(sid);
    w.u16(sid,"sid"); w.f32(_foil_g,"foil",1); w.f32(_strain_g,"strain",1);
    w.end();
}
static void emitHall(UniProto&,uint8_t sid,UniFrameWriter& w,void*) {
    w.begin(sid);
    w.u16(sid,"sid"); w.f32(_hall_deg,"deg",2);
    w.end();
}
static void emitEncoder(UniProto&,uint8_t sid,UniFrameWriter& w,void*) {
    w.begin(sid);
    w.u16(sid,"sid"); w.i32(_enc_p,"pos"); w.f32(_enc_v,"vel",1);
    w.end();
}
static void emitCap(UniProto&,uint8_t sid,UniFrameWriter& w,void*) {
    w.begin(sid);
    w.u16(sid,"sid"); w.f32(_capA,"A",1); w.f32(_capB,"B",1); w.f32(_cap_pos,"mm",1);
    w.end();
}
static void emitRC(UniProto&,uint8_t sid,UniFrameWriter& w,void*) {
    w.begin(sid);
    w.u16(sid,"sid"); w.u16(_rc_count,"cnt"); w.f32(_rc_ref,"ref",3);
    w.end();
}
static void emitUS(UniProto&,uint8_t sid,UniFrameWriter& w,void*) {
    w.begin(sid);
    w.u16(sid,"sid"); w.f32(_us_cm,"cm",1);
    w.end();
}

// ── setup ─────────────────────────────────────────────────────────────────────
void setup() {
    pinMode(2, INPUT_PULLUP);
    pinMode(3, INPUT_PULLUP);
    pinMode(8, OUTPUT);
    pinMode(12, INPUT);
    // D4 starts discharged
    pinMode(4, OUTPUT); digitalWrite(4, LOW);

    // Timer2 for encoder — configured after global constructors
    // (CapacitiveSensor global init cannot overwrite this)
    TCCR2A = 0; TCCR2B = 4; TIMSK2 = 1<<TOIE2; TCNT2 = 0xE7;

    Serial.begin(115200);
    proto.begin();
    proto.setRateHz(20);

    proto.registerStream({1,"analog",  "u16,u16,u16,u16,u16,u16,u16","sid,A0,A1,A2,A3,A4,A5",emitAnalog, nullptr});
    proto.registerStream({2,"force",   "u16,f32,f32",  "sid,foil_g,strain_g",                 emitForce,  nullptr});
    proto.registerStream({3,"hall",    "u16,f32",      "sid,deg",                              emitHall,   nullptr});
    proto.registerStream({4,"encoder", "u16,i32,f32",  "sid,pos,vel",                         emitEncoder,nullptr});
    proto.registerStream({5,"cap",     "u16,f32,f32,f32","sid,A,B,pos_mm",                    emitCap,    nullptr});
    proto.registerStream({6,"rc",      "u16,u16,f32",  "sid,count,ref_v",                     emitRC,     nullptr});
    proto.registerStream({7,"us",      "u16,f32",      "sid,cm",                              emitUS,     nullptr});
}

// ── loop ──────────────────────────────────────────────────────────────────────
static uint32_t _fast_next = 0;
static uint32_t _slow_next = 0;
static uint8_t  _slow_phase = 0;   // rotate slow sensors to spread blocking time

void loop() {
    uint32_t now = millis();

    if (now >= _fast_next) {
        _fast_next = now + 50;   // 20Hz
        pollFast();
    }

    if (now >= _slow_next) {
        _slow_next = now + 67;   // ~15Hz cycle across 3 slow sensors
        switch (_slow_phase) {
            case 0: pollCap(); break;
            case 1: pollRC();  break;
            case 2: pollUS();  break;
        }
        _slow_phase = (_slow_phase + 1) % 3;   // each sensor runs at ~5Hz
    }

    proto.tick();
}