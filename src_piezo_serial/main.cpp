#include <Arduino.h>
#include "UniProto.h"

// Single stream: A0,A1,A2,A3,dA0,dA1,dA2,dA3 (8 fields)
// while(!Serial) required for Leonardo USB CDC startup.

#define NUM_CH 4
UniProto proto(Serial, "PiezoSerial");

static float    _smooth       = 0.7f;
static uint16_t _raw[NUM_CH]  = {512,512,512,512};
static float    _sd[NUM_CH]   = {0,0,0,0};
static int16_t  _d[NUM_CH]    = {0,0,0,0};
static uint16_t _prev[NUM_CH] = {512,512,512,512};

static void emitPiezo(UniProto&, uint8_t sid, UniFrameWriter& w, void*) {
    w.begin(sid);
    for (uint8_t i=0;i<NUM_CH;i++) w.u16(_raw[i],"raw");
    for (uint8_t i=0;i<NUM_CH;i++) w.i32(_d[i],"d");
    w.end();
}

static bool getParam(UniProto&, const char* k, char* out, size_t len, void*) {
    if (!strcmp(k,"piezo.smooth")) { snprintf(out,len,"%.2f",(double)_smooth); return true; }
    return false;
}
static bool setParam(UniProto&, const char* k, const char* v, void*) {
    if (!strcmp(k,"piezo.smooth")) { _smooth=UniProto::parseFloat(v); return true; }
    return false;
}

void setup() {
    Serial.begin(115200);
    while (!Serial);   // Leonardo: wait for host DTR+RTS assertion
    proto.begin();
    proto.setRateHz(200);
    proto.registerStream({1,"piezo","u16,u16,u16,u16,i32,i32,i32,i32",
                          "A0,A1,A2,A3,dA0,dA1,dA2,dA3",emitPiezo,nullptr});
    proto.registerParam({"piezo.smooth",UniProto::ParamType::FLOAT,getParam,setParam,nullptr});
}

void loop() {
    for (uint8_t i=0;i<NUM_CH;i++) {
        _raw[i]=(uint16_t)analogRead(i);
        float d=(float)((int)_raw[i]-(int)_prev[i]);
        _sd[i]=(1.0f-_smooth)*_sd[i]+_smooth*d;
        _d[i]=(int16_t)_sd[i];
        _prev[i]=_raw[i];
    }
    proto.tick();
}