"""
SSD1309 OLED Display Module for Kiln Controller
Displays temperature, target, state, profile, and time information

Uses luma.oled library for proper SSD1309 support with correct voltage booster configuration
"""

from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1309
import logging
import config

log = logging.getLogger("kiln-controller.display")


class KilnDisplay:
    """Manages the SSD1309 OLED display for kiln information"""
    
    def __init__(self, width=None, height=None, i2c_address=None, i2c_port=None):
        """
        Initialize the display
        
        Args:
            width: Display width in pixels (default from config or 128)
            height: Display height in pixels (default from config or 64)
            i2c_address: I2C address of the display (default from config or 0x3C)
            i2c_port: I2C port number (default from config or 1)
        """
        # Get defaults from config if available, otherwise use hardcoded defaults
        config_width = getattr(config, 'display_width', 128)
        config_height = getattr(config, 'display_height', 64)
        config_address = getattr(config, 'display_i2c_address', 0x3C)
        config_port = getattr(config, 'display_i2c_port', 1)
        config_enabled = getattr(config, 'display_enabled', True)

        self.width = width if width is not None else config_width
        self.height = height if height is not None else config_height
        address = i2c_address if i2c_address is not None else config_address
        port = i2c_port if i2c_port is not None else config_port
        
        self.device = None
        self.initialized = False
        
        if not config_enabled:
            log.info("Display disabled in config")
            return

        try:
            # Initialize I2C interface
            serial = i2c(port=port, address=address)
            
            # Create SSD1309 device
            self.device = ssd1309(serial, width=self.width, height=self.height)
            
            # Clear display
            self.device.clear()
            
            self.initialized = True
            log.info(f"SSD1309 display initialized successfully at address 0x{address:02X}")
            
        except Exception as e:
            log.warning(f"Failed to initialize display: {e}")
            self.initialized = False
    
    def format_temperature(self, temp, scale="f"):
        """Format temperature for display"""
        if temp is None:
            return "---"
        if scale.lower() == "f":
            return f"{temp:.0f}°F"
        else:
            return f"{temp:.0f}°C"
    
    def format_time(self, seconds):
        """Format time in seconds to HH:MM:SS or MM:SS"""
        if seconds is None or seconds < 0:
            return "--:--"
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"
    
    def update(self, oven_state, temp_scale="f"):
        """
        Update the display with current oven state
        
        Args:
            oven_state: Dictionary from oven.get_state() containing:
                - temperature: Current temperature
                - target: Target temperature
                - state: Current state (IDLE, RUNNING, PAUSED, etc.)
                - profile: Profile name (or None)
                - runtime: Current runtime in seconds
                - totaltime: Total profile time in seconds
                - heat_rate: Heating rate in degrees/hour
            temp_scale: Temperature scale ("f" or "c")
        """
        if not self.initialized:
            return
        
        try:
            # Get state values with defaults
            temp = oven_state.get('temperature', 0)
            target = oven_state.get('target', 0)
            state = oven_state.get('state', 'IDLE')
            profile = oven_state.get('profile', None)
            runtime = oven_state.get('runtime', 0)
            totaltime = oven_state.get('totaltime', 0)
            heat_rate = oven_state.get('heat_rate', 0)
            
            # Calculate time remaining
            time_remaining = totaltime - runtime if totaltime > 0 else 0
            
            # Draw using canvas context manager
            with canvas(self.device) as draw:
                # Line 1: State and Profile
                state_text = f"{state}"
                if profile:
                    # Truncate profile name if too long
                    profile_text = profile[:12] if len(profile) > 12 else profile
                    state_text = f"{state} - {profile_text}"
                
                draw.text((0, 0), state_text, fill="white")
                
                # Line 2: Current Temperature
                temp_text = f"Temp: {self.format_temperature(temp, temp_scale)}"
                draw.text((0, 12), temp_text, fill="white")
                
                # Line 3: Target Temperature
                target_text = f"Targ: {self.format_temperature(target, temp_scale)}"
                draw.text((0, 24), target_text, fill="white")
                
                # Line 4: Time information
                if state in ['RUNNING', 'PAUSED'] and totaltime > 0:
                    time_text = f"Time: {self.format_time(runtime)} / {self.format_time(totaltime)}"
                    draw.text((0, 36), time_text, fill="white")
                    
                    # Line 5: Time remaining and heat rate
                    remaining_text = f"Rem: {self.format_time(time_remaining)}"
                    if heat_rate > 0:
                        rate_text = f" {heat_rate:.0f}°/hr"
                        remaining_text += rate_text
                    draw.text((0, 48), remaining_text, fill="white")
                else:
                    # Show heat rate if available
                    if heat_rate > 0:
                        rate_text = f"Rate: {heat_rate:.0f}°/hr"
                        draw.text((0, 36), rate_text, fill="white")
            
        except Exception as e:
            log.error(f"Error updating display: {e}")
    
    def clear(self):
        """Clear the display"""
        if not self.initialized:
            return
        
        try:
            self.device.clear()
        except Exception as e:
            log.error(f"Error clearing display: {e}")
    
    def show_message(self, message, line=0):
        """
        Display a simple message on the display
        
        Args:
            message: Text to display
            line: Line number (0-4 for 64px height, 0-2 for 32px height)
        """
        if not self.initialized:
            return
        
        try:
            with canvas(self.device) as draw:
                y_pos = line * 12
                draw.text((0, y_pos), message[:21], fill="white")  # Limit to 21 chars
        except Exception as e:
            log.error(f"Error showing message: {e}")


# Example usage function
def example_usage():
    """Example of how to use the display"""
    display = KilnDisplay()
    
    # Example state data
    example_state = {
        'temperature': 1250,
        'target': 1300,
        'state': 'RUNNING',
        'profile': 'Cone 6 Glaze',
        'runtime': 3600,
        'totaltime': 7200,
        'heat_rate': 150
    }
    
    display.update(example_state, temp_scale='f')
