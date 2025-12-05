#!/usr/bin/env python
"""
Test script to display icons and animations on SSD1309 display
Demonstrates how to use custom icons, logos, and animations.
"""

from luma.core.render import canvas
from display import KilnDisplay
import time
import sys
import argparse

def test_icons(display):
    """Test displaying static icons"""
    print("\nTesting Static Icons")
    print("-" * 20)
    
    # Load icons
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

    # Cycle through icons
    scenarios = [
        ('flame', "Temp: 1250°F"),
        ('clock', "Time: 01:30:00"),
        ('stop_sign', "STOPPED"),
        ('snowflake', "Cooling...")
    ]

    for icon_name, text in scenarios:
        with canvas(display.device) as draw:
            icon = icons.get(icon_name)
            if icon:
                draw.bitmap((0, 0), icon, fill="white")
            draw.text((24, 2), text, fill="white")
        time.sleep(2)

    # All icons grid
    with canvas(display.device) as draw:
        x_positions = [0, 20, 40, 60]
        for i, name in enumerate(['flame', 'clock', 'stop_sign', 'snowflake']):
            if icons.get(name):
                draw.bitmap((x_positions[i], 0), icons[name], fill="white")
        draw.text((0, 20), "All Icons", fill="white")
    time.sleep(2)

def test_logo(display):
    """Test displaying Kiln God logo animation"""
    print("\nTesting Kiln God Logo Animation")
    print("-" * 20)
    
    # Load animation frames
    frames = []
    for i in range(6):
        name = f'kiln_god_{i}'
        icon = display.load_icon_from_hex(name)
        if icon:
            frames.append(icon)
            print(f"  ✓ {name}: {icon.size[0]}x{icon.size[1]} pixels")
        else:
            print(f"  ✗ {name}: Failed to load")
    
    if not frames:
        print("No frames loaded for logo animation")
        return

    # Animate
    print("Animating logo...")
    start_time = time.time()
    while time.time() - start_time < 10:  # Run for 10 seconds
        for frame in frames:
            with canvas(display.device) as draw:
                # Center the image (assuming 128x64 display and image)
                draw.bitmap((0, 0), frame, fill="white")
            time.sleep(0.2)  # Animation speed

def test_pottery(display):
    """Test displaying Pottery animation"""
    print("\nTesting Pottery Flame Animation")
    print("-" * 20)
    
    # Load frames
    # pottery base image + 5 flame frames
    frames = {}
    
    # Base pottery image
    pottery = display.load_icon_from_hex('pottery')
    if pottery:
        print(f"  ✓ pottery: {pottery.size[0]}x{pottery.size[1]} pixels")
    else:
        print(f"  ✗ pottery: Failed to load")
        
    # Flame frames
    flame_frames = []
    for i in range(1, 6):
        name = f'pottery_flame_{i}'
        icon = display.load_icon_from_hex(name)
        if icon:
            flame_frames.append(icon)
            print(f"  ✓ {name}: {icon.size[0]}x{icon.size[1]} pixels")
        else:
            print(f"  ✗ {name}: Failed to load")

    if not pottery or not flame_frames:
        print("Insufficient frames loaded for pottery animation")
        return

    # Animate
    print("Animating pottery...")
    start_time = time.time()
    while time.time() - start_time < 10:  # Run for 10 seconds
        # Sequence: pottery -> flame 1 -> ... -> flame 5 -> repeat?
        # We cycle all of them including base pottery to create a flickering effect
        sequence = [pottery] + flame_frames + flame_frames[::-1] # Ping pong effect
        
        for frame in sequence:
            with canvas(display.device) as draw:
                # Draw centered horizontally
                x = (display.width - frame.width) // 2
                draw.bitmap((x, 0), frame, fill="white")
            time.sleep(0.15)

def main():
    parser = argparse.ArgumentParser(description='Test Kiln Controller Display Images')
    parser.add_argument('--test', choices=['all', 'icons', 'logo', 'pottery'], default='all',
                        help='Specific test to run (default: all)')
    args = parser.parse_args()

    display = KilnDisplay()
    if not display.initialized:
        print("ERROR: Display not initialized")
        sys.exit(1)
        
    print("Display initialized successfully")
    print("Press Ctrl+C to exit current test")
    
    try:
        if args.test in ['all', 'icons']:
            test_icons(display)
            if args.test == 'all': time.sleep(1)
            
        if args.test in ['all', 'logo']:
            test_logo(display)
            if args.test == 'all': time.sleep(1)
            
        if args.test in ['all', 'pottery']:
            test_pottery(display)
        
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        print("\nClearing display...")
        display.clear()
        print("Done!")

if __name__ == "__main__":
    main()
