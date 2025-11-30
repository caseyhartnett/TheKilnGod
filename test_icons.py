#!/usr/bin/env python
"""
Test script to display icons on SSD1309 display
Demonstrates how to use the custom icons (flame, snowflake, stop_sign, clock)
"""

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1309
from PIL import Image
from display import KilnDisplay
import time

def test_icons():
    """Test displaying icons on the OLED display"""
    print("Testing Icons on SSD1309 Display")
    print("=" * 40)
    
    # Initialize display
    display = KilnDisplay()
    
    if not display.initialized:
        print("ERROR: Display not initialized")
        return
    
    print("Display initialized successfully")
    print("Loading icons...")
    
    # Load all icons
    icons = {
        'flame': display.load_icon_from_hex('flame'),
        'snowflake': display.load_icon_from_hex('snowflake'),
        'stop_sign': display.load_icon_from_hex('stop_sign'),
        'clock': display.load_icon_from_hex('clock')
    }
    
    # Check which icons loaded successfully
    for name, icon in icons.items():
        if icon:
            print(f"  ✓ {name}: {icon.size[0]}x{icon.size[1]} pixels")
        else:
            print(f"  ✗ {name}: Failed to load")
    
    print("\nDisplaying icons with text...")
    print("Press Ctrl+C to exit")
    print("=" * 40)
    
    try:
        while True:
            # Example 1: Flame icon with temperature
            with canvas(display.device) as draw:
                flame_icon = icons['flame']
                if flame_icon:
                    draw.bitmap((0, 0), flame_icon, fill="white")
                draw.text((20, 2), "Temp: 1250°F", fill="white")
            
            time.sleep(2)
            
            # Example 2: Clock icon with time
            with canvas(display.device) as draw:
                clock_icon = icons['clock']
                if clock_icon:
                    draw.bitmap((0, 0), clock_icon, fill="white")
                draw.text((20, 2), "Time: 01:30:00", fill="white")
            
            time.sleep(2)
            
            # Example 3: Stop sign
            with canvas(display.device) as draw:
                stop_icon = icons['stop_sign']
                if stop_icon:
                    draw.bitmap((0, 0), stop_icon, fill="white")
                draw.text((20, 2), "STOPPED", fill="white")
            
            time.sleep(2)
            
            # Example 4: Snowflake (for cooling)
            with canvas(display.device) as draw:
                snow_icon = icons['snowflake']
                if snow_icon:
                    draw.bitmap((0, 0), snow_icon, fill="white")
                draw.text((20, 2), "Cooling...", fill="white")
            
            time.sleep(2)
            
            # Example 5: All icons in a grid
            with canvas(display.device) as draw:
                if icons['flame']:
                    draw.bitmap((0, 0), icons['flame'], fill="white")
                if icons['clock']:
                    draw.bitmap((20, 0), icons['clock'], fill="white")
                if icons['stop_sign']:
                    draw.bitmap((40, 0), icons['stop_sign'], fill="white")
                if icons['snowflake']:
                    draw.bitmap((60, 0), icons['snowflake'], fill="white")
                draw.text((0, 20), "All Icons", fill="white")
            
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n\nClearing display...")
        display.clear()
        print("Done!")

if __name__ == "__main__":
    test_icons()

