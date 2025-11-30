#!/usr/bin/env python
"""
Simple test script to verify SSD1309 display is working
Run this to check if your display hardware is connected correctly
"""

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1309
import time

print("Testing SSD1309 Display...")
print("=" * 40)

try:
    # Try common I2C addresses and ports
    addresses_to_try = [0x3D, 0x3C]
    ports_to_try = [1, 0]  # Try port 1 first (most common), then port 0
    device = None
    
    for port in ports_to_try:
        for addr in addresses_to_try:
            try:
                print(f"Trying I2C port {port}, address 0x{addr:02X}...")
                # Initialize I2C interface
                serial = i2c(port=port, address=addr)
                # Create SSD1309 device
                device = ssd1309(serial)
                print(f"✓ Display found at port {port}, address 0x{addr:02X}")
                break
            except Exception as e:
                print(f"  No display at port {port}, 0x{addr:02X}: {e}")
                continue
        if device is not None:
            break
    
    if device is None:
        print("ERROR: Could not find display at any address!")
        print("Please check your connections and I2C address.")
        exit(1)
    
    print(f"Display size: {device.width}x{device.height} pixels")
    print("Drawing test pattern...")
    
    # Draw "Hello World" and test text using canvas
    with canvas(device) as draw:
        draw.text((0, 0), "Hello World!", fill="white")
        draw.text((0, 12), "SSD1309 Test", fill="white")
        draw.text((50, 24), "Display OK!", fill="white")
        draw.text((0, 36), "128x64 pixels", fill="white")
        draw.text((0, 48), "I2C Working", fill="white")
    
    print("=" * 40)
    print("SUCCESS! Display is working!")
    print("You should see text on your display.")
    print("Press Ctrl+C to exit.")
    print("=" * 40)
    
    # Keep it running so you can see the display
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nClearing display and exiting...")
        device.clear()
        print("Done!")

except Exception as e:
    print(f"ERROR: {e}")
    print("\nTroubleshooting:")
    print("1. Check I2C connections (SDA, SCL)")
    print("2. Verify I2C address (try 0x3C or 0x3D)")
    print("3. Make sure display is powered")
    print("4. Check if I2C is enabled on your Raspberry Pi")
    import traceback
    traceback.print_exc()
