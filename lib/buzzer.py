import time
import logging
import config

try:
    import RPi.GPIO as GPIO
except ImportError:
    # Allow running on non-Pi hardware for simulation/testing
    from unittest.mock import MagicMock
    GPIO = MagicMock()

log = logging.getLogger(__name__)

class Buzzer:
    def __init__(self):
        self.pin = getattr(config, 'gpio_buzzer', 12)
        self.enabled = True
        self.pwm = None
        
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.pin, GPIO.OUT)
            self.pwm = GPIO.PWM(self.pin, 100) # Start with 100Hz
        except Exception as e:
            log.error(f"Failed to initialize buzzer on pin {self.pin}: {e}")
            self.enabled = False

    def play_tone(self, frequency, duration):
        if not self.enabled or not self.pwm:
            return
        
        try:
            self.pwm.ChangeFrequency(frequency)
            self.pwm.start(50) # 50% duty cycle
            time.sleep(duration)
            self.pwm.stop()
        except Exception as e:
            log.error(f"Error playing tone: {e}")

    def startup(self):
        """Ascending 3-note chime (C-E-G)"""
        log.info("Buzzer: Startup")
        if not self.enabled: return
        
        # C5 (523), E5 (659), G5 (784)
        self.play_tone(523, 0.15)
        time.sleep(0.05)
        self.play_tone(659, 0.15)
        time.sleep(0.05)
        self.play_tone(784, 0.3)

    def start_firing(self):
        """Long ascending 'power up' slide"""
        log.info("Buzzer: Start Firing")
        if not self.enabled or not self.pwm: return
        
        try:
            self.pwm.start(50)
            # Slide from 200Hz to 2000Hz
            for freq in range(200, 2001, 50):
                self.pwm.ChangeFrequency(freq)
                time.sleep(0.02)
            self.pwm.stop()
        except Exception as e:
            log.error(f"Error in start_firing: {e}")

    def firing_complete(self):
        """Victory fanfare (rapid arpeggio)"""
        log.info("Buzzer: Firing Complete")
        if not self.enabled: return

        # Major triad arpeggio: C-E-G-C
        notes = [523, 659, 784, 1046]
        for note in notes:
            self.play_tone(note, 0.1)
            time.sleep(0.05)
        
        # Final long note
        self.play_tone(1046, 0.6)

    def error(self):
        """Rapid high-low siren alarm"""
        log.info("Buzzer: Error")
        if not self.enabled or not self.pwm: return
        
        try:
            self.pwm.start(50)
            for _ in range(3):
                self.pwm.ChangeFrequency(800)
                time.sleep(0.3)
                self.pwm.ChangeFrequency(1200)
                time.sleep(0.3)
            self.pwm.stop()
        except Exception as e:
            log.error(f"Error in error: {e}")

    def manual_stop(self):
        """Descending 'power down' slide"""
        log.info("Buzzer: Manual Stop")
        if not self.enabled or not self.pwm: return
        
        try:
            self.pwm.start(50)
            # Slide from 1000Hz to 100Hz
            for freq in range(1000, 99, -50):
                self.pwm.ChangeFrequency(freq)
                time.sleep(0.02)
            self.pwm.stop()
        except Exception as e:
            log.error(f"Error in manual_stop: {e}")

    def cleanup(self):
        if self.pwm:
            self.pwm.stop()
        # We don't call GPIO.cleanup() here because it might mess up other components
        # just stop the PWM
