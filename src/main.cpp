#include <Arduino.h>
#include <Wire.h>
#include "UniProto.h"
//#include "mod_adc.h"
//#include "mod_motors.h"
//#include "mod_psd.h"
#include "mod_bldc.h"

UniProto proto(Serial, "BldcNode");

//AdcModule adc(AdcModule::defaultUno());
//BldcModule bldc(BldcModule::defaultUno());
//PsdModule psd(PsdModule::defaultUnoA0());
//DualMotorModule motors(DualMotorModule::defaultUno());

// (optional) quick I2C scan for bring-up
static void i2cScan() {
  Serial.println(F("I2C scan..."));
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.print(F(" 0x"));
      if (addr < 16) Serial.print('0');
      Serial.println(addr, HEX);
    }
  }
  Serial.println(F("Done."));
}

static BldcModule::Config makeBldcConfig() {
  auto c = BldcModule::defaultUno();
  c.as5600Addr = 0x36;
  //c.invert = true;       // <--- THIS flips position sign
  c.proto = BldcModule::Config::DriverProto::V1_ADDR_0x65;
  c.driverAddrV1 = 0x65;
  c.driverAddrV2 = 0x64;

  c.polePairs = 7;
  c.controlHz = 500;
  
  return c;
}

static BldcModule bldc(makeBldcConfig());

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);

  proto.begin();

  bldc.registerWith(proto);

  //psd.registerWith(proto);
  //adc.registerWith(proto);
  //motors.registerWith(proto);

   //i2cScan();  // uncomment once for bring-up

}

void loop() {
  proto.tick();
  //motors.poll();     // control loop
  bldc.poll();
}
