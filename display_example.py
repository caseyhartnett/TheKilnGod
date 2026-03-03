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
        self.last_state = None
        self.last_profile = None
        self.last_retry = 0.0
        self.retry_interval = 30.0

        if self.display.initialized:
            self.display.show_message("Kiln Controller", line=2)
            time.sleep(1)
            log.info("Display updater initialized")
        else:
            log.warning("Display not initialized, updater will retry")

    def _retry_init_display(self):
        now = time.time()
        if now - self.last_retry < self.retry_interval:
            return
        self.last_retry = now
        self.display = KilnDisplay()
        if self.display.initialized:
            self.display.show_message("Display Ready", line=2)
            time.sleep(0.5)
            log.info("Display re-initialized")

    def _render_transition_banner(self, state, profile):
        if not self.display.initialized:
            return
        profile_name = (profile or "")[:18]
        if state == "RUNNING":
            self.display.show_message("Firing Started", line=1)
            if profile_name:
                self.display.show_message(profile_name, line=2)
        elif state == "PAUSED":
            self.display.show_message("Firing Paused", line=1)
            if profile_name:
                self.display.show_message(profile_name, line=2)
        elif state == "IDLE":
            self.display.show_message("Kiln Idle", line=1)
        else:
            self.display.show_message(f"State: {state}", line=1)
        time.sleep(0.8)
    
    def run(self):
        """Main loop that updates the display"""
        while True:
            try:
                if not self.display.initialized:
                    self._retry_init_display()
                if self.display.initialized:
                    # Get current state from oven
                    state = self.oven.get_state()
                    current_state = state.get('state', 'IDLE')
                    current_profile = state.get('profile')

                    # Show a short transition banner on state/profile changes.
                    if (self.last_state != current_state) or (
                        current_state == "RUNNING" and self.last_profile != current_profile
                    ):
                        self._render_transition_banner(current_state, current_profile)
                        self.last_state = current_state
                        self.last_profile = current_profile
                    
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
