#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"
#include "mod_motors.h"
#include "mod_psd.h"

UniProto proto(Serial, "UnoNode");

//AdcModule adc(AdcModule::defaultUno());

PsdModule psd(PsdModule::defaultUnoA0());

//DualMotorModule motors(DualMotorModule::defaultUno());

void setup() {
  Serial.begin(115200);
  proto.begin();

  psd.registerWith(proto);
  //adc.registerWith(proto);
  //motors.registerWith(proto);

}

void loop() {
  proto.tick();
  //motors.poll();     // control loop
}
