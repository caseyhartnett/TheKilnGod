#!/usr/bin/env python
"""
Example of how to integrate the KilnDisplay with the kiln controller

This shows how to create a background thread that updates the display
periodically with the current oven state.
"""

import time
import threading
import logging
from display import KilnDisplay
import config

log = logging.getLogger("kiln-controller.display-example")


class DisplayUpdater(threading.Thread):
    """Background thread that updates the display periodically"""
    
    def __init__(self, oven, update_interval=2.0):
        """
        Initialize the display updater
        
        Args:
            oven: The oven object (RealOven or SimulatedOven)
            update_interval: How often to update the display in seconds (default 2.0)
        """
        threading.Thread.__init__(self)
        self.daemon = True
        self.oven = oven
        self.update_interval = update_interval
        self.display = KilnDisplay()
        
        if self.display.initialized:
            self.display.show_message("Kiln Controller", line=2)
            time.sleep(1)
            log.info("Display updater initialized")
        else:
            log.warning("Display not initialized, updater will not update display")
    
    def run(self):
        """Main loop that updates the display"""
        while True:
            try:
                if self.display.initialized:
                    # Get current state from oven
                    state = self.oven.get_state()
                    
                    # Update display with current state
                    self.display.update(state, temp_scale=config.temp_scale)
                
                # Sleep until next update
                time.sleep(self.update_interval)
                
            except Exception as e:
                log.error(f"Error in display updater: {e}")
                time.sleep(self.update_interval)


# Example of how to integrate this into kiln-controller.py:
#
# In kiln-controller.py, after creating the oven object:
#
#   from display_example import DisplayUpdater
#   
#   # Create and start display updater
#   display_updater = DisplayUpdater(oven, update_interval=2.0)
#   display_updater.start()
#
# The display will automatically update every 2 seconds with the current
# kiln state information.

if __name__ == "__main__":
    # Simple test/demo
    logging.basicConfig(level=logging.INFO)
    
    # Create a mock display for testing
    display = KilnDisplay()
    
    if display.initialized:
        # Test with example data
        test_states = [
            {
                'temperature': 75,
                'target': 0,
                'state': 'IDLE',
                'profile': None,
                'runtime': 0,
                'totaltime': 0,
                'heat_rate': 0
            },
            {
                'temperature': 1250,
                'target': 1300,
                'state': 'RUNNING',
                'profile': 'Cone 6 Glaze',
                'runtime': 3600,
                'totaltime': 7200,
                'heat_rate': 150
            },
            {
                'temperature': 1800,
                'target': 1800,
                'state': 'PAUSED',
                'profile': 'Cone 10',
                'runtime': 5400,
                'totaltime': 10800,
                'heat_rate': 0
            }
        ]
        
        for i, state in enumerate(test_states):
            print(f"Displaying test state {i+1}...")
            display.update(state, temp_scale='f')
            time.sleep(3)
        
        print("Test complete!")
    else:
        print("Display not initialized. Make sure your hardware is connected.")
