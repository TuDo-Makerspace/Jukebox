"""
 Copyright (C) 2024 TuDo Makerspace

 This program is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 This program is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with this program.  If not, see <http://www.gnu.org/licenses/>.

Description: Main script to control our Jukebox

Dependencies:
- bpm-tag: For analyzing song BPM.
- ffplay: For playing audio files.
- libsox-fmt-mp3: For MP3 format support.

Contributors:
- Patrick Pedersen <ctx.xda@gmail.com>
"""

import re
import os
import glob
import time
import signal
import random
import argparse
import threading
import subprocess
import RPi.GPIO as GPIO
from pathlib import Path

################################################################
# Globals
################################################################

JUKEBOX_SONGS_PATH = None

################################################################
# Lamps
################################################################

# Note: Lamps are active low.

LAMP_ON = GPIO.LOW
LAMP_OFF = GPIO.HIGH

GPIO_TOP_LAMPS = 12  # PWM capable
GPIO_LR_LAMPS = 13  # PWM capable
GPIO_BOT_LAMPS = 18  # PWM capable

################################################################
# Keypad GPIOs
################################################################

KEYPAD_GPIO_PINS = [5, 6, 7, 8]  # Example GPIO pins for the keypad

################################################################
# Light patterns
################################################################

LIGHT_PATTERN_BLINK_ALL = [
    [1, 1, 1],
    [0, 0, 0],
    [1, 1, 1],
    [0, 0, 0],
    [1, 1, 1],
    [0, 0, 0],
    [1, 1, 1],
    [0, 0, 0],
]

LIGHT_PATTERN_DOWN_UP = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
]

LIGHT_PATTERN_UP_DOWN = [
    [0, 1, 0],
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
]

LIGHT_PATTERN_TB_LR = [
    [1, 0, 1],
    [0, 1, 0],
    [1, 0, 1],
    [0, 1, 0],
    [1, 0, 1],
    [0, 1, 0],
    [1, 0, 1],
    [0, 1, 0],
]

ALL_LIGHT_PATTERNS = [
    LIGHT_PATTERN_BLINK_ALL,
    LIGHT_PATTERN_DOWN_UP,
    LIGHT_PATTERN_UP_DOWN,
    LIGHT_PATTERN_TB_LR,
]

################################################################
# Functions
################################################################


def clear_terminal():
    """Clear the terminal screen."""
    os.system("clear")


def init_gpios():
    """
    Initialize the GPIO pins for the keypad and lights.
    """
    GPIO.setmode(GPIO.BCM)

    # Set the GPIO pins for the keypad as inputs with pull-down resistors
    for pin in KEYPAD_GPIO_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    # Set the GPIO pins for the lights as outputs
    GPIO.setup(GPIO_TOP_LAMPS, GPIO.OUT)
    GPIO.setup(GPIO_LR_LAMPS, GPIO.OUT)
    GPIO.setup(GPIO_BOT_LAMPS, GPIO.OUT)


def song_path(number):
    """
    Get the file path of the song based on the input number.

    Args:
        number (int): The song number.

    Returns:
        str: Path to the song file, or None if no match is found.
    """
    songs_path = Path(JUKEBOX_SONGS_PATH)
    song_pattern = f"{number}_*.mp3 {number}_*.wav"
    song_files = []

    for pattern in song_pattern.split():
        song_files.extend(glob.glob(str(songs_path / pattern)))

    if len(song_files) > 1:
        print(
            f"Warning: Found multiple files for number {number}, using the first one."
        )

    return song_files[0] if song_files else None


def bpm_tag(file_path):
    """
    Analyze the BPM of a song using bpm-tag.

    Note: If the song hasn't been analyzed/tagged before, this may take some time.

    Args:
        file_path (str): Path to the song file.

    Returns:
        float: The detected BPM, or a fallback value of 120 if detection fails.
    """
    result = subprocess.run(
        ["bpm-tag", file_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    output = result.stdout + result.stderr
    match = re.search(r"([\d.]+) BPM", output)
    bpm = float(match.group(1)) if match else 120

    if not match:
        print(
            f"Error: Failed to detect BPM for {file_path}! Using 120 BPM as fallback."
        )

    return bpm


def play_song(song_path):
    """
    Play a song using ffplay.

    Args:
        song_path (str): Path to the song file.
    """
    try:
        subprocess.run(["ffplay", "-nodisp", "-autoexit", song_path], check=True)
    except FileNotFoundError:
        print("Error: 'ffplay' not found. Please install it.")
    except subprocess.CalledProcessError:
        print(f"Failed to play {song_path}")


def show_light_pattern(pattern, bpm):
    """
    Display a light pattern synchronized with the song's BPM.

    Args:
        pattern (list): Light pattern represented as a list of frames.
        bpm (float): Beats per minute of the song.
    """
    delay = 60 / bpm  # Convert bpm to delay between steps

    for frame in pattern:
        GPIO.output(GPIO_TOP_LAMPS, LAMP_ON if frame[0] else LAMP_OFF)
        GPIO.output(GPIO_LR_LAMPS, LAMP_ON if frame[1] else LAMP_OFF)
        GPIO.output(GPIO_BOT_LAMPS, LAMP_ON if frame[2] else LAMP_OFF)
        time.sleep(delay)


def show_random_light_pattern(bpm):
    """
    Display a random light pattern.

    Args:
        bpm (float): Beats per minute of the song.
    """
    pattern = random.choice(ALL_LIGHT_PATTERNS)
    show_light_pattern(pattern, bpm)


def await_keypad_input():
    """
    Wait for and return input from the keypad.

    Returns:
        int: The song number entered by the user.
    """
    # TODO: Implement keypad input
    return 0


def test_lights(args):
    """
    Test specific lights.

    Args:
        args (Namespace): Parsed command-line arguments.
    """
    if args.lights_top or args.lights:
        print("Turning on top lights...")
        GPIO.output(GPIO_TOP_LAMPS, LAMP_ON)

    if args.lights_lr or args.lights:
        print("Turning on left-right lights...")
        GPIO.output(GPIO_LR_LAMPS, LAMP_ON)

    if args.lights_bottom or args.lights:
        print("Turning on bottom lights...")
        GPIO.output(GPIO_BOT_LAMPS, LAMP_ON)

    # Wait for user input
    input("Press any key to turn off lights...")
    GPIO.output(GPIO_TOP_LAMPS, LAMP_OFF)
    GPIO.output(GPIO_LR_LAMPS, LAMP_OFF)
    GPIO.output(GPIO_BOT_LAMPS, LAMP_OFF)


def play(number):
    spath = song_path(number)

    if not spath:
        print(f"No song found for number {number} in {JUKEBOX_SONGS_PATH}")
        return False

    GPIO.output(GPIO_TOP_LAMPS, LAMP_ON)
    GPIO.output(GPIO_LR_LAMPS, LAMP_ON)
    GPIO.output(GPIO_BOT_LAMPS, LAMP_ON)

    play_load_sample_thread = threading.Thread(
        target=play_song, args=(JUKEBOX_SONGS_PATH + "/Load.wav",)
    )
    play_load_sample_thread.start()

    bpm = bpm_tag(spath)
    play_load_sample_thread.join()

    play_thread = threading.Thread(target=play_song, args=(spath,))
    play_thread.start()

    while play_thread.is_alive():
        show_random_light_pattern(bpm)

    GPIO.output(GPIO_TOP_LAMPS, LAMP_OFF)
    GPIO.output(GPIO_LR_LAMPS, LAMP_OFF)
    GPIO.output(GPIO_BOT_LAMPS, LAMP_OFF)

    return True


def run():
    """
    Main event loop. Waits for song input, plays the song, and synchronizes lights.
    """
    while True:
        number = await_keypad_input()
        play(number)


def test_keypad():
    """
    Test the keypad GPIO pins by displaying their states.

    Updates the terminal only if the GPIO states change.
    """

    def signal_handler(sig, frame):
        """Handle interrupt signal (Ctrl+C) to exit gracefully."""
        print("\nKeypad test interrupted. Exiting...")
        GPIO.cleanup()
        exit(0)

    # Register signal handler for graceful interruption
    signal.signal(signal.SIGINT, signal_handler)

    print("Testing keypad GPIO states. Press Ctrl+C to exit.")

    # Initialize previous state to None
    previous_states = None

    try:
        while True:
            # Read current states of GPIO pins
            current_states = [GPIO.input(pin) for pin in KEYPAD_GPIO_PINS]

            # Update the terminal only if states differ from the previous ones
            if current_states != previous_states:
                clear_terminal()
                print("Keypad GPIO States")
                print("===================")
                print("GPIO | State")
                print("-----|-------")
                for pin, state in zip(KEYPAD_GPIO_PINS, current_states):
                    print(f"{pin:>4} | {state}")

                # Update previous states
                previous_states = current_states

            # Small delay to avoid excessive CPU usage
            time.sleep(0.1)
    except Exception as e:
        print(f"Error: {e}")
        GPIO.cleanup()
        exit(1)


################################################################
# Main
################################################################

if __name__ == "__main__":
    """
    Entry point. Parses arguments and runs the appropriate mode.
    """
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")

    # Main mode (renamed to run)
    run_parser = subparsers.add_parser("run", help="Run the Jukebox service.")
    run_parser.add_argument(
        "-p",
        "--path",
        type=str,
        help="Path to the directory containing the songs (default: JUKEBOX_SONGS_PATH)",
        default=os.getenv("JUKEBOX_SONGS_PATH"),
    )

    # Test mode
    test_parser = subparsers.add_parser(
        "test", help="Test individual lights, keypad, or all lights."
    )
    test_parser.add_argument(
        "--lights-top", action="store_true", help="Turn on top lights."
    )
    test_parser.add_argument(
        "--lights-lr", action="store_true", help="Turn on left-right lights."
    )
    test_parser.add_argument(
        "--lights-bottom", action="store_true", help="Turn on bottom lights."
    )
    test_parser.add_argument(
        "--lights", action="store_true", help="Turn on all lights."
    )
    test_parser.add_argument(
        "--keypad", action="store_true", help="Test the keypad input."
    )

    play_parser = subparsers.add_parser("play", help="Play a specific song and quit.")
    play_parser.add_argument("number", type=int, help="The song number to play.")
    play_parser.add_argument(
        "-p",
        "--path",
        type=str,
        help="Path to the directory containing the songs (default: JUKEBOX_SONGS_PATH)",
        default=os.getenv("JUKEBOX_SONGS_PATH"),
    )

    args = parser.parse_args()

    JUKEBOX_SONGS_PATH = args.path

    # Run the appropriate mode

    if args.command == "test":

        init_gpios()

        if args.keypad:
            test_keypad()
        else:
            try:
                test_lights(args)
            except KeyboardInterrupt:
                print("\nTest mode interrupted. Cleaning up GPIO...")
            finally:
                GPIO.output(GPIO_TOP_LAMPS, LAMP_OFF)
                GPIO.output(GPIO_LR_LAMPS, LAMP_OFF)
                GPIO.output(GPIO_BOT_LAMPS, LAMP_OFF)
                GPIO.cleanup()

    elif args.command == "run":
        if not JUKEBOX_SONGS_PATH or not Path(JUKEBOX_SONGS_PATH).is_dir():
            print("Error: Invalid path to songs directory.")
            print(
                "Please set the JUKEBOX_SONGS_PATH environment variable or provide a valid path with the -p flag."
            )
            exit(1)

        init_gpios()

        try:
            run()
        except KeyboardInterrupt:
            print("\nScript interrupted. Turning off lights and cleaning up GPIO...")
        finally:
            GPIO.output(GPIO_TOP_LAMPS, LAMP_OFF)
            GPIO.output(GPIO_LR_LAMPS, LAMP_OFF)
            GPIO.output(GPIO_BOT_LAMPS, LAMP_OFF)
            GPIO.cleanup()

    elif args.command == "play":
        if not JUKEBOX_SONGS_PATH or not Path(JUKEBOX_SONGS_PATH).is_dir():
            print("Error: Invalid path to songs directory.")
            print(
                "Please set the JUKEBOX_SONGS_PATH environment variable or provide a valid path with the -p flag."
            )
            exit(1)

        init_gpios()

        try:
            play(args.number)
        except KeyboardInterrupt:
            print("\nScript interrupted. Turning off lights and cleaning up GPIO...")
        finally:
            GPIO.output(GPIO_TOP_LAMPS, LAMP_OFF)
            GPIO.output(GPIO_LR_LAMPS, LAMP_OFF)
            GPIO.output(GPIO_BOT_LAMPS, LAMP_OFF)
            GPIO.cleanup()

    else:
        parser.print_help()
