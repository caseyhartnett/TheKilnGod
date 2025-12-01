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
BAUD_RATE = 9600            # TRYING 9600 BAUD
TIMEOUT = 1.0               # Read timeout in seconds
HALT_PIN = 18               # GPIO Pin for halt signal (BCM 18)

def signal_handler(sig, frame):
    print("\nExiting...")
    if GPIO_AVAILABLE:
        GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def parse_ups_data(data_str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] RAW DATA: {data_str}")

def main():
    print(f"UPSPack V3 Plus UART Test (9600 BAUD)")
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
        
        last_pin_state = None

        while True:
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
                    raw_data = ser.readline()
                    hex_data = raw_data.hex(' ')
                    print(f"RAW HEX: {hex_data}")
                    
                    try:
                        decoded_data = raw_data.decode('utf-8').strip()
                        if decoded_data:
                            print(f"ASCII: {decoded_data}")
                    except UnicodeDecodeError:
                        pass
                        
                except Exception as e:
                    print(f"Error reading data: {e}")
            
            time.sleep(0.1)

    except Exception as e:
        print(f"Error: {e}")
    
    finally:
        if 'ser' in locals() and ser.isOpen():
            ser.close()
        if GPIO_AVAILABLE:
            GPIO.cleanup()

if __name__ == "__main__":
    main()

