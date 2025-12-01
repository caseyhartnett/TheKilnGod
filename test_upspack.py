#!/usr/bin/env python
import time
import sys
import signal
import re
from datetime import datetime

try:
    import serial
except ImportError:
    print("Error: pyserial not installed. Please run 'pip install pyserial'")
    sys.exit(1)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: RPi.GPIO not found. Pin 18 monitoring disabled.")

# Configuration
UART_PORT = '/dev/serial0'  # Default UART port on Raspberry Pi (GPIO 14 TX, 15 RX)
BAUD_RATE = 115200          # Standard baud rate for UPSPack V3 Plus
TIMEOUT = 1.0               # Read timeout in seconds
HALT_PIN = 18               # GPIO Pin for halt signal (BCM 18)

def signal_handler(sig, frame):
    print("\nExiting...")
    if GPIO_AVAILABLE:
        GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def parse_ups_data(data_str):
    """
    Parse UPSPack data string.
    Expected formats might be:
    - "Good! V:4.15V C:100%"
    - "Voltage: 4.15V, Capacity: 100%"
    - "4.15 100"
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parsed = {}

    # Common regex patterns for UPS data
    # Voltage (e.g., 4.15V, 4.15 V, 4150mV)
    v_match = re.search(r'(\d+\.?\d*)\s*[vV]', data_str)
    if v_match:
        parsed['voltage'] = float(v_match.group(1))
    
    # Capacity (e.g., 100%, 95 %)
    c_match = re.search(r'(\d+\.?\d*)\s*%', data_str)
    if c_match:
        parsed['capacity'] = float(c_match.group(1))
        
    # Status indicators
    if "Good" in data_str:
        parsed['status'] = "Normal"
    elif "Low" in data_str:
        parsed['status'] = "Low Battery"
    elif "Shutdown" in data_str:
        parsed['status'] = "Shutdown Imminent"
        
    if parsed:
        print(f"[{timestamp}] PARSED DATA:")
        if 'voltage' in parsed:
            print(f"  - Voltage:  {parsed['voltage']:.2f} V")
        if 'capacity' in parsed:
            print(f"  - Capacity: {parsed['capacity']:.1f} %")
        if 'status' in parsed:
            print(f"  - Status:   {parsed['status']}")
    else:
        print(f"[{timestamp}] Unrecognized data format")

def main():
    print(f"UPSPack V3 Plus UART Test")
    print(f"-------------------------")
    print(f"Port: {UART_PORT}")
    print(f"Baud Rate: {BAUD_RATE}")
    print(f"Press Ctrl+C to exit")
    print(f"-------------------------")

    # Setup GPIO for Halt Pin
    if GPIO_AVAILABLE:
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(HALT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            print(f"Monitoring Pin {HALT_PIN} (BCM) for halt signal...")
        except Exception as e:
            print(f"Error setting up GPIO {HALT_PIN}: {e}")

    try:
        # Initialize serial connection
        ser = serial.Serial(
            port=UART_PORT,
            baudrate=BAUD_RATE,
            timeout=TIMEOUT,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS
        )
        
        if ser.isOpen():
            print(f"Successfully opened {UART_PORT}")
        
        # Clear buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print("Waiting for data...")
        print("Attempting to wake up board with commands...")
        
        # List of common wake-up/query commands
        commands = [b'\n', b'help\n', b'?\n', b'get\n', b'info\n', b'$V\n']
        cmd_index = 0
        last_cmd_time = time.time()
        
        last_pin_state = None

        while True:
            # Send a command every 2 seconds if silent
            if time.time() - last_cmd_time > 2.0:
                cmd = commands[cmd_index % len(commands)]
                print(f"Sending query: {cmd}")
                ser.write(cmd)
                last_cmd_time = time.time()
                cmd_index += 1

            # Check Halt Pin
            if GPIO_AVAILABLE:
                try:
                    current_pin_state = GPIO.input(HALT_PIN)
                    if current_pin_state != last_pin_state:
                        state_str = "HIGH" if current_pin_state else "LOW"
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Pin {HALT_PIN} changed to {state_str}")
                        last_pin_state = current_pin_state
                except Exception as e:
                    print(f"GPIO Error: {e}")

            if ser.in_waiting > 0:
                # Read line if available
                try:
                    # Try decoding as UTF-8 first (common for debug output)
                    raw_data = ser.readline()
                    
                    # Print raw bytes for debugging
                    hex_data = raw_data.hex(' ')
                    print(f"RAW HEX: {hex_data}")
                    
                    try:
                        decoded_data = raw_data.decode('utf-8').strip()
                        if decoded_data:
                            print(f"ASCII: {decoded_data}")
                            parse_ups_data(decoded_data)
                    except UnicodeDecodeError:
                        print(f"ASCII: <binary/undecodable>")
                        
                except Exception as e:
                    print(f"Error reading data: {e}")
            
            time.sleep(0.1)

    except serial.SerialException as e:
        print(f"Serial Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check if UART is enabled in /boot/config.txt (enable_uart=1)")
        print("2. Check if the user has permission (sudo usermod -a -G dialout $USER)")
        print("3. Check connections on GPIO 14 (TX) and 15 (RX)")
        print("4. Ensure no other process is using the serial port")

    except Exception as e:
        print(f"Unexpected Error: {e}")
    
    finally:
        if 'ser' in locals() and ser.isOpen():
            ser.close()
            print("Serial port closed")
        if GPIO_AVAILABLE:
            GPIO.cleanup()
            print("GPIO cleaned up")

if __name__ == "__main__":
    main()

