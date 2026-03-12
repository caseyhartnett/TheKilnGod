#!/usr/bin/env python
import datetime
import time

import adafruit_bitbangio as bitbangio
import config
from digitalio import DigitalInOut

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    import sys
    sys.exit()

########################################################################
#
# To test your thermocouple...
#
# Edit config.py and set the following in that file to match your
# hardware setup: SPI_SCLK, SPI_MOSI, SPI_MISO, SPI_CS
#
# then run this script...
# 
# ./test-thermocouple.py
#
# It will output a temperature in degrees every second. Touch your
# thermocouple to heat it up and make sure the value changes. Accuracy
# of my thermocouple is .25C.
########################################################################

spi = None
if(hasattr(config,'spi_sclk') and
   hasattr(config,'spi_mosi') and
   hasattr(config,'spi_miso')):
    spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
    print("Software SPI selected for reading thermocouple")
    print("SPI configured as:\n")
    print("    config.spi_sclk = %s BCM pin" % (config.spi_sclk))
    print("    config.spi_mosi = %s BCM pin" % (config.spi_mosi))
    print("    config.spi_miso = %s BCM pin" % (config.spi_miso))
    print("    config.spi_cs   = %s BCM pin\n" % (config.spi_cs))
else:
    spi = board.SPI();
    print("Hardware SPI selected for reading thermocouple")

cs = DigitalInOut(config.spi_cs)
cs.switch_to_output(value=True)
sensor = None

print("\nboard: %s" % (board.board_id))
if(config.max31855):
    import adafruit_max31855
    print("thermocouple: adafruit max31855")
    sensor = adafruit_max31855.MAX31855(spi, cs)
if(config.max31856):
    import adafruit_max31856
    print("thermocouple: adafruit max31856")
    sensor = adafruit_max31856.MAX31856(spi, cs)

print("Degrees displayed in %s\n" % (config.temp_scale))


def format_temp(temp_c):
    value = temp_c
    scale = "C"
    if config.temp_scale == "f":
        value = temp_c * (9 / 5) + 32
        scale = "F"
    return f"{value:0.2f}{scale}"


try:
    while True:
        time.sleep(1)
        try:
            temp_c = sensor.temperature
            if config.max31856:
                ref_c = sensor.reference_temperature
                fault = sensor.fault
                print(
                    f"{datetime.datetime.now()} "
                    f"probe={format_temp(temp_c)} "
                    f"ref={format_temp(ref_c)} "
                    f"fault={fault}"
                )
                if temp_c == 0.0 and ref_c == 0.0 and not any(fault.values()):
                    print(
                        "  note: both readings are 0.0C with no faults; "
                        "this often means SPI comms are returning all zeros"
                    )
            else:
                print("%s %s" % (datetime.datetime.now(), format_temp(temp_c)))
        except Exception as error:
            print("error: ", error)
except KeyboardInterrupt:
    print("\nstopped")
