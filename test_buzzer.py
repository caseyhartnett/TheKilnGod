#!/usr/bin/env python
"""
Test script for the piezo buzzer.
Allows testing each sound pattern individually or custom tones.
"""

import sys
import os
import time

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))

from buzzer import Buzzer

def print_menu():
    print("\n" + "="*50)
    print("Buzzer Test Menu")
    print("="*50)
    print("1. Startup sound (Ascending 3-note chime)")
    print("2. Start Firing sound (Power up slide)")
    print("3. Firing Complete sound (Victory fanfare)")
    print("4. Error sound (Siren alarm)")
    print("5. Manual Stop sound (Power down slide)")
    print("6. Custom tone (frequency and duration)")
    print("7. Test all sounds in sequence")
    print("0. Exit")
    print("="*50)

def test_custom_tone(buzzer):
    try:
        freq = float(input("Enter frequency (Hz, e.g., 440 for A4): "))
        duration = float(input("Enter duration (seconds, e.g., 0.5): "))
        print(f"Playing {freq}Hz for {duration}s...")
        buzzer.play_tone(freq, duration)
        print("Done!")
    except ValueError:
        print("Invalid input. Please enter numbers.")
    except Exception as e:
        print(f"Error: {e}")

def test_all(buzzer):
    print("\nTesting all sounds in sequence...")
    sounds = [
        ("Startup", buzzer.startup),
        ("Start Firing", buzzer.start_firing),
        ("Firing Complete", buzzer.firing_complete),
        ("Error", buzzer.error),
        ("Manual Stop", buzzer.manual_stop),
    ]
    
    for name, func in sounds:
        print(f"\nPlaying: {name}")
        try:
            func()
            time.sleep(0.5)  # Brief pause between sounds
        except Exception as e:
            print(f"Error playing {name}: {e}")
    
    print("\nAll sounds tested!")

def main():
    print("Initializing buzzer...")
    try:
        buzzer = Buzzer()
        if not buzzer.enabled:
            print("WARNING: Buzzer is not enabled. Check GPIO configuration.")
            return
        print("Buzzer initialized successfully!")
    except Exception as e:
        print(f"ERROR: Failed to initialize buzzer: {e}")
        return
    
    # Check for command line arguments
    if len(sys.argv) > 1:
        sound_map = {
            '1': ('startup', buzzer.startup),
            '2': ('start_firing', buzzer.start_firing),
            '3': ('firing_complete', buzzer.firing_complete),
            '4': ('error', buzzer.error),
            '5': ('manual_stop', buzzer.manual_stop),
        }
        
        arg = sys.argv[1].lower()
        if arg in sound_map:
            name, func = sound_map[arg]
            print(f"Playing: {name}")
            try:
                func()
            except Exception as e:
                print(f"Error: {e}")
        elif arg == 'all':
            test_all(buzzer)
        elif arg == 'custom':
            if len(sys.argv) >= 4:
                try:
                    freq = float(sys.argv[2])
                    duration = float(sys.argv[3])
                    buzzer.play_tone(freq, duration)
                except ValueError:
                    print("Usage: test_buzzer.py custom <frequency> <duration>")
            else:
                print("Usage: test_buzzer.py custom <frequency> <duration>")
        else:
            print(f"Unknown sound: {arg}")
            print("Available: 1, 2, 3, 4, 5, all, custom")
        return
    
    # Interactive menu
    while True:
        print_menu()
        try:
            choice = input("\nEnter your choice: ").strip()
            
            if choice == '0':
                print("Exiting...")
                break
            elif choice == '1':
                print("Playing startup sound...")
                buzzer.startup()
            elif choice == '2':
                print("Playing start firing sound...")
                buzzer.start_firing()
            elif choice == '3':
                print("Playing firing complete sound...")
                buzzer.firing_complete()
            elif choice == '4':
                print("Playing error sound...")
                buzzer.error()
            elif choice == '5':
                print("Playing manual stop sound...")
                buzzer.manual_stop()
            elif choice == '6':
                test_custom_tone(buzzer)
            elif choice == '7':
                test_all(buzzer)
            else:
                print("Invalid choice. Please try again.")
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")
    
    # Cleanup
    try:
        buzzer.cleanup()
    except:
        pass

if __name__ == "__main__":
    main()
