#!/usr/bin/env python
"""
Test script to display images from hex data on SSD1309 display
Paste hex data (like C-style array) and it will be displayed
Supports multiple images that cycle in sequence at a configurable rate
"""

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1309
from PIL import Image
import re
import time

def parse_hex_data(text):
    """
    Parse hex data from text (handles C-style array format)
    Returns tuple: (list of integers, width, height)
    Dimensions are extracted from comments if available (e.g., "64x64px")
    """
    # Try to extract dimensions from comments
    width, height = 64, 64  # defaults
    dimension_pattern = r'(\d+)x(\d+)px'
    for line in text.split('\n'):
        match = re.search(dimension_pattern, line, re.IGNORECASE)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            print(f"Found dimensions in comment: {width}x{height}px")
            break
    
    # Remove comments (lines starting with //)
    lines = [line for line in text.split('\n') if not line.strip().startswith('//')]
    text = '\n'.join(lines)
    
    # Extract hex values (0x... format)
    hex_pattern = r'0x([0-9a-fA-F]+)'
    matches = re.findall(hex_pattern, text)
    
    # Convert to integers
    data = [int(hex_val, 16) for hex_val in matches]
    
    return data, width, height

def hex_to_image(hex_data, width=64, height=64):
    """
    Convert hex data to PIL Image
    Assumes 1 bit per pixel (monochrome)
    """
    # Calculate expected size
    expected_bytes = (width * height) // 8
    
    if len(hex_data) < expected_bytes:
        print(f"Warning: Expected {expected_bytes} bytes, got {len(hex_data)}")
        # Pad with zeros if needed
        hex_data.extend([0] * (expected_bytes - len(hex_data)))
    elif len(hex_data) > expected_bytes:
        print(f"Warning: Got {len(hex_data)} bytes, expected {expected_bytes}. Truncating.")
        hex_data = hex_data[:expected_bytes]
    
    # Create image in mode '1' (1-bit pixels, black and white)
    img = Image.new('1', (width, height), 0)  # Start with black
    
    # Convert bytes to pixels
    pixel_index = 0
    for byte_val in hex_data:
        # Each byte represents 8 pixels (MSB first for typical bitmap format)
        for bit in range(7, -1, -1):  # Bits 7 down to 0
            if pixel_index >= width * height:
                break
            x = pixel_index % width
            y = pixel_index // width
            # Set pixel to white (1) if bit is set
            if byte_val & (1 << bit):
                img.putpixel((x, y), 1)
            pixel_index += 1
    
    return img

def display_image_on_oled(image, device):
    """
    Display PIL Image on OLED display
    """
    # Resize if needed to fit display (typically 128x64)
    display_width = device.width
    display_height = device.height
    
    img_width, img_height = image.size
    
    # If image is smaller than display, center it on a black background
    # If image is larger, scale it down to fit
    if img_width > display_width or img_height > display_height:
        # Scale down to fit
        scale = min(display_width / img_width, display_height / img_height)
        new_width = int(img_width * scale)
        new_height = int(img_height * scale)
        image = image.resize((new_width, new_height), Image.NEAREST)
        img_width, img_height = image.size
    
    # Create a full-size display image (black background)
    display_image = Image.new('1', (display_width, display_height), 0)
    
    # Center the image
    x_offset = (display_width - img_width) // 2
    y_offset = (display_height - img_height) // 2
    
    # Paste the image onto the display image
    display_image.paste(image, (x_offset, y_offset))
    
    # Display using device.display() method
    device.display(display_image)

def load_hex_data_from_file(filename):
    """Load hex data from a file"""
    try:
        with open(filename, 'r') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading file {filename}: {e}")
        return None

def load_hex_files_from_directory(directory):
    """
    Load all .hex files from a directory
    Returns list of hex data strings, sorted by filename
    """
    import os
    import glob
    
    if not os.path.isdir(directory):
        print(f"Warning: Directory {directory} does not exist")
        return []
    
    hex_files = sorted(glob.glob(os.path.join(directory, '*.hex')))
    hex_data_list = []
    
    for hex_file in hex_files:
        data = load_hex_data_from_file(hex_file)
        if data:
            hex_data_list.append(data)
            print(f"  Loaded: {os.path.basename(hex_file)}")
    
    return hex_data_list

def parse_multiple_images(text_list):
    """
    Parse multiple hex data blocks into a list of images
    Each element in text_list should be a hex data string
    Returns list of PIL Images
    """
    images = []
    for i, hex_text in enumerate(text_list):
        if not hex_text or not hex_text.strip():
            continue
        try:
            hex_data, img_width, img_height = parse_hex_data(hex_text)
            img = hex_to_image(hex_data, width=img_width, height=img_height)
            images.append(img)
            print(f"  Image {i+1}: {img_width}x{img_height} pixels")
        except Exception as e:
            print(f"  Warning: Failed to parse image {i+1}: {e}")
            continue
    return images

def split_multiple_images_from_text(text, separator="---IMAGE---"):
    """
    Split a single text block into multiple image blocks
    Uses separator string to delimit images
    Returns list of text blocks
    """
    if separator in text:
        return text.split(separator)
    else:
        # If no separator, treat as single image
        return [text]

def main():
    import sys
    import argparse
    import os
    
    parser = argparse.ArgumentParser(description='Display images from hex data on SSD1309 OLED')
    parser.add_argument('file', nargs='?', help='File containing hex data (optional)')
    parser.add_argument('--rate', type=float, default=0.5, 
                       help='Frame rate in seconds per image (default: 0.5)')
    parser.add_argument('--single', action='store_true',
                       help='Display single image only (no animation loop)')
    parser.add_argument('--dir', type=str, default=None,
                       help='Directory containing .hex files (default: images/hex/)')
    args = parser.parse_args()
    
    print("Image Display Test for SSD1309")
    print("=" * 40)
    
    # Default images directory
    default_images_dir = os.path.join(os.path.dirname(__file__), 'images', 'hex')
    
    # Determine image source
    hex_data_text = None
    image_texts = []
    
    if args.file:
        # Single file provided
        print(f"Reading hex data from file: {args.file}")
        hex_data_text = load_hex_data_from_file(args.file)
        if hex_data_text is None:
            print("Failed to read file")
            exit(1)
        # Check if file is empty or contains no valid hex data
        if not hex_data_text or not hex_data_text.strip():
            print(f"ERROR: File {args.file} is empty or contains no data")
            print("The file must contain hex data in 0x... format")
            exit(1)
        # Split file content into multiple images if separator exists
        image_texts = split_multiple_images_from_text(hex_data_text)
        # Check if any of the image texts contain valid hex data
        hex_pattern = r'0x([0-9a-fA-F]+)'
        has_valid_hex = False
        for img_text in image_texts:
            if img_text and img_text.strip():
                matches = re.findall(hex_pattern, img_text)
                if matches:
                    has_valid_hex = True
                    break
        if not has_valid_hex:
            print(f"ERROR: File {args.file} contains no valid hex data")
            print("The file must contain hex values in 0x... format (e.g., 0xFF, 0x00)")
            print("You can:")
            print("  1. Check that the file contains hex data in the correct format")
            print("  2. Provide a different file: python test_image_display.py <filename>")
            print("  3. Use directory mode: python test_image_display.py --dir <directory>")
            exit(1)
        print(f"Found {len(image_texts)} image(s) in file")
    else:
        # Load from directory
        images_dir = args.dir if args.dir else default_images_dir
        print(f"Loading images from directory: {images_dir}")
        image_texts = load_hex_files_from_directory(images_dir)
        
        if len(image_texts) == 0:
            print(f"No .hex files found in {images_dir}")
            print("You can:")
            print("  1. Add .hex files to the images/hex/ directory")
            print("  2. Provide a file: python test_image_display.py <filename>")
            print("  3. Specify a directory: python test_image_display.py --dir <directory>")
            exit(1)
        
        print(f"Loaded {len(image_texts)} image file(s) from directory")
    

    try:
        # Try to find display
        addresses_to_try = [0x3D, 0x3C]
        ports_to_try = [1, 0]
        device = None
        
        for port in ports_to_try:
            for addr in addresses_to_try:
                try:
                    print(f"Trying I2C port {port}, address 0x{addr:02X}...")
                    serial = i2c(port=port, address=addr)
                    device = ssd1309(serial)
                    print(f"✓ Display found at port {port}, address 0x{addr:02X}")
                    break
                except Exception as e:
                    print(f"  No display at port {port}, 0x{addr:02X}: {e}")
                    continue
            if device is not None:
                break
        
        if device is None:
            print("ERROR: Could not find display!")
            print("You can still test image conversion (without display)")
            print("=" * 40)
            # Parse and show image info even without display
            images = parse_multiple_images(image_texts)
            print(f"Created {len(images)} image(s)")
            for i, img in enumerate(images):
                print(f"  Image {i+1}: {img.size[0]}x{img.size[1]} pixels")
            print("Images created successfully (but no display to show them on)")
            exit(1)
        
        print(f"Display size: {device.width}x{device.height} pixels")
        print("Converting hex data to images...")
        
        # Parse all images
        images = parse_multiple_images(image_texts)
        
        if len(images) == 0:
            print("ERROR: No valid images found!")
            exit(1)
        
        print(f"Successfully loaded {len(images)} image(s)")
        
        # Display images
        if args.single or len(images) == 1:
            # Single image mode
            print("Displaying single image on OLED...")
            display_image_on_oled(images[0], device)
            print("=" * 40)
            print("SUCCESS! Image displayed!")
            print("Press Ctrl+C to exit.")
            print("=" * 40)
            
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nClearing display and exiting...")
                device.clear()
                print("Done!")
        else:
            # Animation mode - cycle through images
            print(f"Starting animation sequence ({len(images)} images, {args.rate}s per frame)...")
            print("=" * 40)
            print("Press Ctrl+C to exit.")
            print("=" * 40)
            
            try:
                frame_count = 0
                while True:
                    for i, img in enumerate(images):
                        display_image_on_oled(img, device)
                        frame_count += 1
                        if frame_count % len(images) == 0:
                            print(f"Cycle {frame_count // len(images)} complete", end='\r')
                        time.sleep(args.rate)
            except KeyboardInterrupt:
                print("\n\nClearing display and exiting...")
                device.clear()
                print(f"Displayed {frame_count} frames total")
                print("Done!")
    
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

