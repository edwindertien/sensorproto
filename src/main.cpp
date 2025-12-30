#include <Arduino.h>
#include "UniProto.h"
#include "mod_adc.h"
#include "mod_motors.h"

// #ifdef ARDUINO_ARCH_AVR
// extern unsigned int __heap_start;
// extern void *__brkval;
// static int freeRam() {
//   int v;
//   return (int)&v - (__brkval == 0 ? (int)&__heap_start : (int)__brkval);
// }
// #endif

UniProto proto(Serial, "UnoNode");

AdcModule adc(AdcModule::defaultUno());

//DualMotorModule motors(DualMotorModule::defaultUno());

void setup() {
  Serial.begin(115200);
  proto.begin();

  adc.registerWith(proto);
  //motors.registerWith(proto);

//   #ifdef ARDUINO_ARCH_AVR
// Serial.print(F("freeRam="));
// Serial.println(freeRam());
// #endif

}

void loop() {
  proto.tick();
  //motors.poll();     // control loop
}
