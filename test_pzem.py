#!/usr/bin/env python
"""
PZEM-004T V4.0 AC Meter Test Script
Reads power measurements using Modbus RTU protocol over UART

Hardware Connections:
- PZEM TX -> BCM 15 (Pin 10) via level shifter
- PZEM RX -> BCM 14 (Pin 8) via level shifter
- Serial port: /dev/serial0
- Baud rate: 9600, 8N1
"""

import time
import sys
import signal
from datetime import datetime

try:
    import serial
except ImportError:
    print("Error: pyserial not installed. Please run 'pip install pyserial'")
    sys.exit(1)

# Configuration
UART_PORT = '/dev/serial0'  # Default UART port on Raspberry Pi (GPIO 14 TX, 15 RX)
BAUD_RATE = 9600            # PZEM-004T default baud rate
TIMEOUT = 1.0               # Read timeout in seconds
PZEM_ADDRESS = 0x01         # Default Modbus slave address
READ_INTERVAL = 2.0         # Seconds between readings

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print("\nExiting...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def modbus_crc16(data):
    """
    Calculate Modbus RTU CRC-16 checksum
    
    Args:
        data: bytes object containing the Modbus frame (without CRC)
    
    Returns:
        tuple: (crc_low, crc_high) bytes
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return (crc & 0xFF, (crc >> 8) & 0xFF)

def read_input_registers(ser, slave_addr, start_reg, num_regs):
    """
    Send Modbus RTU Read Input Registers command (Function Code 0x04)
    
    Args:
        ser: Serial port object
        slave_addr: Modbus slave address (0x01 for PZEM-004T)
        start_reg: Starting register address (0x0000)
        num_regs: Number of registers to read (0x000A = 10)
    
    Returns:
        bytes: Response frame or None if error
    """
    # Build Modbus RTU frame: [Slave Address][Function Code][Start Address High][Start Address Low][Quantity High][Quantity Low][CRC Low][CRC High]
    frame = bytearray([
        slave_addr,           # Slave address
        0x04,                 # Function code: Read Input Registers
        (start_reg >> 8) & 0xFF,  # Start address high byte
        start_reg & 0xFF,     # Start address low byte
        (num_regs >> 8) & 0xFF,   # Quantity high byte
        num_regs & 0xFF       # Quantity low byte
    ])
    
    # Calculate and append CRC
    crc_low, crc_high = modbus_crc16(frame)
    frame.append(crc_low)
    frame.append(crc_high)
    
    # Clear input buffer
    ser.reset_input_buffer()
    
    # Send command
    ser.write(frame)
    time.sleep(0.05)  # Small delay for transmission
    
    # Read response
    # Expected response: [Slave Address][Function Code][Byte Count][Data...][CRC Low][CRC High]
    # For 10 registers (20 bytes of data): 1 + 1 + 1 + 20 + 2 = 25 bytes total
    response = ser.read(25)
    
    if len(response) < 5:  # Minimum valid response
        return None
    
    # Verify CRC
    received_crc = (response[-1] << 8) | response[-2]
    calculated_crc = (modbus_crc16(response[:-2])[1] << 8) | modbus_crc16(response[:-2])[0]
    
    if received_crc != calculated_crc:
        print(f"Warning: CRC mismatch! Received: 0x{received_crc:04X}, Calculated: 0x{calculated_crc:04X}")
        return None
    
    # Verify slave address and function code
    if response[0] != slave_addr:
        print(f"Warning: Slave address mismatch! Expected: 0x{slave_addr:02X}, Received: 0x{response[0]:02X}")
        return None
    
    if response[1] != 0x04:
        if response[1] & 0x80:  # Error response
            error_code = response[2]
            print(f"Modbus Error: Function code 0x{response[1]:02X}, Error code: 0x{error_code:02X}")
        else:
            print(f"Warning: Unexpected function code: 0x{response[1]:02X}")
        return None
    
    return response

def parse_pzem_data(response):
    """
    Parse PZEM-004T V4.0 response data according to register map
    
    Register Map (Read Input Registers - 0x04):
    - 0x0000: Voltage (0.1V units)
    - 0x0001-0x0002: Current (0.001A units, 32-bit)
    - 0x0003-0x0004: Power (0.1W units, 32-bit)
    - 0x0005-0x0006: Energy (1Wh units, 32-bit)
    - 0x0007: Frequency (0.1Hz units)
    - 0x0008: Power Factor (0.01 units)
    - 0x0009: Alarm Status (0xFFFF = Alarm, 0x0000 = No Alarm)
    
    Args:
        response: Modbus response frame bytes
    
    Returns:
        dict: Parsed measurement data
    """
    if not response or len(response) < 25:
        return None
    
    # Extract data bytes (skip: slave_addr, func_code, byte_count)
    data = response[3:-2]  # Skip header and CRC
    
    # Parse registers (each register is 2 bytes, big-endian)
    voltage_raw = (data[0] << 8) | data[1]
    current_high = (data[2] << 8) | data[3]
    current_low = (data[4] << 8) | data[5]
    power_high = (data[6] << 8) | data[7]
    power_low = (data[8] << 8) | data[9]
    energy_high = (data[10] << 8) | data[11]
    energy_low = (data[12] << 8) | data[13]
    frequency_raw = (data[14] << 8) | data[15]
    power_factor_raw = (data[16] << 8) | data[17]
    alarm_status = (data[18] << 8) | data[19]
    
    # Convert to actual values with scaling
    voltage = voltage_raw / 10.0  # 0.1V units
    current = ((current_high << 16) | current_low) / 1000.0  # 0.001A units, 32-bit
    power = ((power_high << 16) | power_low) / 10.0  # 0.1W units, 32-bit
    energy = ((energy_high << 16) | energy_low)  # 1Wh units, 32-bit
    frequency = frequency_raw / 10.0  # 0.1Hz units
    power_factor = power_factor_raw / 100.0  # 0.01 units
    alarm = (alarm_status == 0xFFFF)
    
    return {
        'voltage': voltage,
        'current': current,
        'power': power,
        'energy': energy,
        'frequency': frequency,
        'power_factor': power_factor,
        'alarm': alarm,
        'timestamp': datetime.now()
    }

def print_measurements(data):
    """Display measurements in a formatted table"""
    if not data:
        return
    
    print("\n" + "="*60)
    print(f"PZEM-004T V4.0 Measurements - {data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print(f"Voltage:        {data['voltage']:7.1f} V")
    print(f"Current:        {data['current']:7.3f} A")
    print(f"Power:          {data['power']:7.1f} W  ({data['power']/1000.0:.3f} kW)")
    print(f"Energy:         {data['energy']:7.0f} Wh  ({data['energy']/1000.0:.3f} kWh)")
    print(f"Frequency:      {data['frequency']:7.1f} Hz")
    print(f"Power Factor:   {data['power_factor']:7.2f}")
    print(f"Alarm Status:   {'ALARM' if data['alarm'] else 'OK'}")
    print("="*60)

def main():
    """Main function"""
    print("PZEM-004T V4.0 AC Meter Test Script")
    print("-" * 60)
    print(f"Port: {UART_PORT}")
    print(f"Baud Rate: {BAUD_RATE}")
    print(f"Modbus Address: 0x{PZEM_ADDRESS:02X}")
    print(f"Read Interval: {READ_INTERVAL} seconds")
    print("Press Ctrl+C to exit")
    print("-" * 60)
    
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
        else:
            print(f"Error: Could not open {UART_PORT}")
            return
        
        # Clear buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        print("\nStarting measurements...\n")
        
        read_count = 0
        error_count = 0
        
        while True:
            try:
                # Read input registers 0x0000-0x0009 (10 registers)
                response = read_input_registers(ser, PZEM_ADDRESS, 0x0000, 0x000A)
                
                if response:
                    data = parse_pzem_data(response)
                    if data:
                        print_measurements(data)
                        read_count += 1
                    else:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: Failed to parse response data")
                        error_count += 1
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: No valid response from PZEM-004T")
                    error_count += 1
                    print("   Check wiring, power, and level shifter connections")
                    print("   Verify PZEM is powered and connected to BCM 14/15")
                
                time.sleep(READ_INTERVAL)
                
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")
                error_count += 1
                time.sleep(READ_INTERVAL)
    
    except serial.SerialException as e:
        print(f"Serial port error: {e}")
        print(f"\nTroubleshooting:")
        print(f"1. Check if {UART_PORT} exists: ls -l {UART_PORT}")
        print(f"2. Verify serial console is disabled: sudo raspi-config -> Interface Options -> Serial Port")
        print(f"3. Check permissions: sudo usermod -a -G dialout $USER (then logout/login)")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if 'ser' in locals() and ser.isOpen():
            ser.close()
            print(f"\nClosed {UART_PORT}")
        print(f"\nSummary: {read_count} successful reads, {error_count} errors")

if __name__ == "__main__":
    main()



