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
    System:
    - bpm-tag: For analyzing song BPM.
    - ffplay: For playing audio files.
    - libsox-fmt-mp3: For MP3 format support.
    Pip:
    - RPi.GPIO: For GPIO control.

Contributors:
- Patrick Pedersen <ctx.xda@gmail.com>
"""

import enum
import re
import os
import glob
import time
import wave
import signal
import random
import logging
import argparse
import threading
import subprocess
import RPi.GPIO as GPIO
import numpy as np
from pathlib import Path
import sounddevice as sd

################################################################
# Globals
################################################################

# Songs directory
JUKEBOX_SONGS_PATH = os.getenv("JUKEBOX_SONGS_PATH")

# Soundboard directory
JUKEBOX_SOUNDBOARD_PATH = os.getenv("JUKEBOX_SOUNDBOARD_PATH")

# Assets directory
JUKEBOX_ASSETS_PATH = os.getenv("JUKEBOX_ASSETS_PATH")

# Asset files and their corresponding keys (S<ee samples dict below)
ASSET_FILES = {
    "TRACK_NOT_FOUND": "TrackMissing.wav",
    "LOAD": "Load.wav",
    "MISSING": "SampleMissing.wav",
    "BANK_OUT_OF_RANGE": "BankOutOfRange.wav",
    "PRESS": "Press.wav",
}

# Interval at which the idle animation is triggered
IDLE_ANIMATION_INTERVAL = 30  # seconds

# Soundboard mode timeout
SOUNDBOARD_TIMEOUT = 60  # seconds

# Maximum Bank Number
MAX_BANK_NUMBER = 9

# Logger
logger = logging.getLogger(__name__)

# Dictionary for permanent asset samples
asset_samples = {}

# Dictionary for the current bank's soundboard samples
soundboard_samples = {}

################################################################
# Lamps
################################################################

LAMP_ON = GPIO.HIGH
LAMP_OFF = GPIO.LOW

GPIO_TOP_LAMPS = 5
GPIO_LR_LAMPS = 6
GPIO_BOT_LAMPS = 26

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

LIGHT_PATTERN_UP_DOWN = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
]

LIGHT_PATTERN_DOWN_UP = [
    [0, 0, 1],
    [0, 1, 0],
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
    [1, 0, 0],
    [0, 1, 0],
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

LIGHT_PATTERN_UP_DOWN_UP = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 0],
]

TETRIS = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 1, 1],
    [1, 1, 1],
    [0, 0, 0],
    [1, 1, 1],
    [0, 0, 0],
]

ALL_LIGHT_PATTERNS = [
    LIGHT_PATTERN_BLINK_ALL,
    LIGHT_PATTERN_DOWN_UP,
    LIGHT_PATTERN_UP_DOWN,
    LIGHT_PATTERN_UP_DOWN_UP,
    LIGHT_PATTERN_TB_LR,
    TETRIS,
]

################################################################
# Keypad
################################################################

GPIO_KEYPAD_PINS = [14, 15, 23, 24]

KEYPAD_RELEASED = (0, 0, 0, 0)

KEYPAD_LOOKUP = {
    (0, 1, 0, 1): "0",
    (1, 0, 1, 1): "1",
    (1, 0, 0, 1): "2",
    (1, 0, 1, 0): "3",
    (0, 0, 1, 1): "4",
    (0, 0, 0, 1): "5",
    (0, 0, 1, 0): "6",
    (1, 1, 1, 1): "7",
    (1, 1, 0, 1): "8",
    (1, 1, 1, 0): "9",
    (0, 1, 1, 1): "R",  # Reset button
    (0, 1, 1, 0): "G",  # Confirm button
    (1, 0, 0, 0): "YELLOW",  # Yellow button
    (0, 1, 0, 0): "BLUE",  # Blue button
    (1, 1, 0, 0): "RED",  # Red button
}

KEYPAD_DEBOUNCE_DELAY = 0.15  # seconds

KEYPAD_TIMEOUT = 5  # seconds

KEYPAD_TAKE_SAMPLES = 10  # Number of samples to take in case for reading the keypad

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
    logger.info("Initializing GPIO pins...")

    GPIO.setmode(GPIO.BCM)

    # Set the GPIO pins for the keypad as inputs with pull-down resistors
    for pin in GPIO_KEYPAD_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    # Set the GPIO pins for the lights as outputs
    GPIO.setup(GPIO_TOP_LAMPS, GPIO.OUT)
    GPIO.setup(GPIO_LR_LAMPS, GPIO.OUT)
    GPIO.setup(GPIO_BOT_LAMPS, GPIO.OUT)

    logger.info("GPIO pins initialized.")


def song_path(number):
    """
    Get the file path of the song based on the input number.

    Args:
        number (int): The song number.

    Returns:
        str: Path to the song file, or None if no match is found.
    """
    songs_path = Path(JUKEBOX_SONGS_PATH)
    song_pattern = f"{number}_*.mp3"
    song_files = []

    for pattern in song_pattern.split():
        song_files.extend(glob.glob(str(songs_path / pattern)))

    if len(song_files) > 1:
        logger.warning(
            f"Warning: Found multiple files for number {number}, using the first one."
        )

    return song_files[0] if song_files else None


def reserved_track_numbers():
    """
    Get a list of reserved track numbers based on the song files.

    Returns:
        list: A list of reserved track numbers.
    """
    songs_path = Path(JUKEBOX_SONGS_PATH)
    reserved_numbers = []

    for file in songs_path.glob("*.mp3"):
        match = re.match(r"(\d+)_", file.stem)
        if match:
            reserved_numbers.append(int(match.group(1)))

    return reserved_numbers


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

    if match:
        logger.info(f"Detected BPM for {file_path}: {bpm}")
    else:
        logger.error(
            f"Failed to detect BPM for {file_path}! Using 120 BPM as fallback."
        )

    return bpm


def preload_assets():
    """
    Preload all *asset* audio files (TRACK_NOT_FOUND, LOAD, MISSING, etc.)
    into memory for faster access during playback.
    """
    global asset_samples

    logger.info("Preloading asset samples...")

    for key, filename in ASSET_FILES.items():
        asset_path = Path(JUKEBOX_ASSETS_PATH) / filename

        if asset_path.exists():
            try:
                with wave.open(str(asset_path), "rb") as wf:
                    params = {
                        "channels": wf.getnchannels(),
                        "framerate": wf.getframerate(),
                        "sampwidth": wf.getsampwidth(),
                    }

                    if params["framerate"] != 44100 and params["framerate"] != 48000:
                        logger.error(
                            f"Unsupported sample rate for asset {key}: {params['framerate']}."
                        )
                        continue

                    frames = wf.readframes(wf.getnframes())
                    audio_data = np.frombuffer(frames, dtype=np.int16)
                    if params["channels"] > 1:
                        audio_data = np.reshape(audio_data, (-1, params["channels"]))

                    asset_samples[key] = (params, audio_data)
                    logger.info(f"Preloaded asset sample {key} from {asset_path}.")
            except Exception as e:
                logger.error(
                    f"Failed to preload asset sample {key} from {asset_path}: {e}"
                )
        else:
            logger.warning(f"Asset file not found: {asset_path}")

    logger.info("All asset samples preloaded.")


def preload_soundboard_samples(bank):
    """
    Preloads all *soundboard* samples (0-9, R, G, etc.) for a specific bank.
    """
    global soundboard_samples

    logger.info(f"Preloading samples for bank {bank}...")

    set_all_lamps(LAMP_ON)

    bank_path = Path(JUKEBOX_SOUNDBOARD_PATH) / str(bank)
    if not bank_path.is_dir():
        logger.warning(f"Bank {bank} directory missing. No samples preloaded.")
        set_all_lamps(LAMP_OFF)
        return

    # Clear only the old *soundboard* samples, leave asset_samples alone
    soundboard_samples.clear()

    # Load .wav files in bank folder
    for sample_file in bank_path.glob("*.wav"):
        try:
            key_match = sample_file.stem.split("_")[0].upper()
            # We only treat digits or R/G as valid keys here
            if key_match.isdigit() or key_match in {"R", "G", "RED", "BLUE"}:
                key = key_match
            else:
                logger.warning(
                    f"Unsupported sample key in file {sample_file}. Skipping."
                )
                continue

            with wave.open(str(sample_file), "rb") as wf:
                params = {
                    "channels": wf.getnchannels(),
                    "framerate": wf.getframerate(),
                    "sampwidth": wf.getsampwidth(),
                }

                if params["framerate"] != 44100 and params["framerate"] != 48000:
                    logger.error(
                        f"Unsupported sample rate for asset {key}: {params['framerate']}."
                    )
                    continue

                frames = wf.readframes(wf.getnframes())
                audio_data = np.frombuffer(frames, dtype=np.int16)
                if params["channels"] > 1:
                    audio_data = np.reshape(audio_data, (-1, params["channels"]))

                soundboard_samples[key] = (params, audio_data)
                logger.info(f"Preloaded sample {key} from {sample_file}.")
        except Exception as e:
            logger.error(f"Failed to preload sample {sample_file}: {e}")

    set_all_lamps(LAMP_OFF)
    logger.info(f"Samples preloaded for bank {bank}.")


def play_song(song_path, blocking=True):
    """
    Play a song using ffplay in a subprocess.

    Args:
        song_path (str): Path to the song file.

    Returns:
        subprocess.Popen: The process object if successful, otherwise None.
    """
    logger.info(f"Playing: {song_path}")
    try:
        process = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", song_path])
        if blocking:
            process.wait()
        return process
    except FileNotFoundError:
        logger.error("Error: 'ffplay' not found. Please install it.")
    except Exception as e:
        logger.error(f"Failed to play {song_path}: {e}")
    return None


def play_sample(key, wait=True):
    """
    Play a sample. If the sample is not found in the current
    soundboard bank, play the "MISSING" sample from the assets.
    """
    # 1) Check if it's in the current soundboard bank
    if key in soundboard_samples:
        params, audio_data = soundboard_samples[key]
    else:
        if "MISSING" in asset_samples:
            params, audio_data = asset_samples["MISSING"]
            key = "MISSING"
        else:
            logger.warning("No 'MISSING' sample in assets, skipping playback.")
            return

    logger.info(f"Playing sample key: {key}")
    try:
        sd.play(audio_data, params["framerate"])
        if wait:
            sd.wait()
    except Exception as e:
        logger.error(f"Failed to play sample {key}: {e}")


def play_asset(key, wait=True):
    """
    Play an asset sample. If the asset is not found, log a warning.
    """
    if key in asset_samples:
        params, audio_data = asset_samples[key]
    else:
        logger.warning(f"Asset sample '{key}' not found.")
        return

    logger.info(f"Playing asset sample: {key}")
    try:
        sd.play(audio_data, params["framerate"])
        if wait:
            sd.wait()
    except Exception as e:
        logger.error(f"Failed to play asset sample {key}: {e}")


def set_all_lamps(state):
    """
    Set all lamps to the specified state.

    Args:
        state (int): The state to set the lamps to (LAMP_ON or LAMP_OFF).
    """
    GPIO.output(GPIO_TOP_LAMPS, state)
    GPIO.output(GPIO_LR_LAMPS, state)
    GPIO.output(GPIO_BOT_LAMPS, state)


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


def random_lights_thread(bpm, stop_event):
    """
    Runs the light pattern in a separate thread until the stop_event is set.

    Args:
        bpm (float): Beats per minute of the song.
        stop_event (threading.Event): An event to signal when to stop the thread.
    """
    logger.info("Starting random light patterns thread...")

    while not stop_event.is_set():
        pattern = random.choice(ALL_LIGHT_PATTERNS)
        bpm_multiplier = random.choice([1, 2])

        for _ in range(bpm_multiplier):
            # Avoid very long delays for low BPM
            delay = max(60 / (bpm * bpm_multiplier), 0.1)
            for frame in pattern:
                if stop_event.is_set():
                    break
                GPIO.output(GPIO_TOP_LAMPS, LAMP_ON if frame[0] else LAMP_OFF)
                GPIO.output(GPIO_LR_LAMPS, LAMP_ON if frame[1] else LAMP_OFF)
                GPIO.output(GPIO_BOT_LAMPS, LAMP_ON if frame[2] else LAMP_OFF)
                time.sleep(delay)

    logger.info("Stopped random light patterns thread...")


def read_keypad_input():
    """
    Read the current state of the keypad GPIO pins.

    Returns:
        str: The button pressed (e.g., "1", "R", "G").
    """

    if KEYPAD_TAKE_SAMPLES and KEYPAD_TAKE_SAMPLES > 1:
        samples = [
            tuple(GPIO.input(pin) for pin in GPIO_KEYPAD_PINS)
            for _ in range(KEYPAD_TAKE_SAMPLES)
        ]
        # Take the most frequent state as the current state
        read = max(set(samples), key=samples.count)
    else:
        read = tuple(GPIO.input(pin) for pin in GPIO_KEYPAD_PINS)

    if read in KEYPAD_LOOKUP:
        return KEYPAD_LOOKUP[read]

    return None


def debounce_and_await_release():
    """
    Debounce the keypad input and wait for the release of all keys.
    Also provides visual feedback by turning on all lights while waiting.
    """
    set_all_lamps(LAMP_ON)
    time.sleep(KEYPAD_DEBOUNCE_DELAY)
    while tuple(GPIO.input(pin) for pin in GPIO_KEYPAD_PINS) != KEYPAD_RELEASED:
        pass
    time.sleep(KEYPAD_DEBOUNCE_DELAY)
    set_all_lamps(LAMP_OFF)


def prompt_keypad_input():
    """
    Wait for a button press on the keypad. Once a button is pressed,
    a visual feedback is given by blinking all lights. The function
    waits for the button to be released before returning.

    Returns:
        str: The button pressed (e.g., "1", "R", "G").
    """
    timeout_in = time.time() + KEYPAD_TIMEOUT

    while True:
        # Check for timeout
        if time.time() > timeout_in:
            return None

        # Read current states of GPIO pins
        read = read_keypad_input()

        # Check if the state matches a button in the lookup table
        if read:
            logger.info(f"Keypad input: {read}")
            play_asset("PRESS", wait=False)
            debounce_and_await_release()
            return read

        # Small delay to avoid excessive CPU usage
        time.sleep(0.05)


class PlayReturn(enum.Enum):
    TRACK_NOT_FOUND = 1
    ABORTED = 2
    FINISHED = 3


def play(number):
    """
    Play a song based on the input number.

    Args:
        number (int): The song number.
    """
    logger.info(f"Searching for song with number {number}...")

    spath = song_path(number)

    if not spath:
        print(f"No song found for number {number} in {JUKEBOX_SONGS_PATH}")

        set_all_lamps(LAMP_ON)
        play_asset("TRACK_NOT_FOUND")
        set_all_lamps(LAMP_OFF)

        return PlayReturn.TRACK_NOT_FOUND

    logger.info(f"Found song: {spath}")

    set_all_lamps(LAMP_ON)

    logger.info(f"Playing load sample and analyzing BPM...")

    # Play the load sample and analyze the BPM at the same time
    load_sample_thread = threading.Thread(target=play_asset, args=("LOAD",))
    load_sample_thread.start()

    bpm = bpm_tag(spath)

    # Wait for the load sample to finish
    load_sample_thread.join()

    # Play the song
    proc = play_song(spath, blocking=False)

    # Thread to display random light patterns
    stop_event = threading.Event()
    lights_thread = threading.Thread(
        target=random_lights_thread, args=(bpm, stop_event)
    )
    lights_thread.start()

    # Do the lights and check for red button press (stop)
    aborted = False
    try:
        while proc.poll() is None:
            if read_keypad_input() == "RED":
                proc.terminate()
                logger.info("Song stopped by user.")
                aborted = True
                break
    finally:
        # Signal the light thread to stop and wait for it to finish
        stop_event.set()
        lights_thread.join()

        set_all_lamps(LAMP_OFF)

        # Debounce if abort key was pressed
        # This is a little excessive, but why not...
        if aborted:
            # User still holding the button
            if read_keypad_input() == "RED":
                debounce_and_await_release()

            # User likely released the button
            else:
                time.sleep(KEYPAD_DEBOUNCE_DELAY)

    logger.info("Done playing song.")

    if aborted:
        return PlayReturn.ABORTED
    else:
        return PlayReturn.FINISHED


def idle(start_with_animation=True):
    """
    Idle mode. Plays up-down light pattern at regular intervals.
    Exits when any key on the keypad is pressed.

    Returns:
        Pressed key to exit idle mode.
    """
    logger.info("Entering idle mode...")

    skip = not start_with_animation

    def key_pressed_check():
        """Checks if a key is pressed and handles lamp blinking for feedback."""
        key = read_keypad_input()
        if key:
            logger.info(f"Key pressed: {key}")
            play_asset("PRESS", wait=False)
            debounce_and_await_release()
        return key

    while True:
        if not skip:
            # Play light pattern animation
            for pattern in [TETRIS]:
                for frame in pattern:
                    GPIO.output(GPIO_TOP_LAMPS, LAMP_ON if frame[0] else LAMP_OFF)
                    GPIO.output(GPIO_LR_LAMPS, LAMP_ON if frame[1] else LAMP_OFF)
                    GPIO.output(GPIO_BOT_LAMPS, LAMP_ON if frame[2] else LAMP_OFF)

                    # Delay for the current frame while checking for key presses
                    frame_delay = time.time() + 0.25
                    while time.time() < frame_delay:
                        k = key_pressed_check()
                        if k:
                            logger.info("Exiting idle mode...")
                            return k

            set_all_lamps(LAMP_OFF)

        skip = False

        # Wait for the next animation trigger
        trigger_in = time.time() + IDLE_ANIMATION_INTERVAL

        # Check for key presses during idle interval
        while time.time() < trigger_in:
            k = key_pressed_check()
            if k:
                logger.info("Exiting idle mode...")
                return k


def soundboard():
    """
    Soundboard mode. Plays sound effects based on keypad input.
    Exits when the red button is pressed.
    """
    logger.info("Entering soundboard mode...")

    bank = 0

    preload_soundboard_samples(bank)

    timeout = time.time() + SOUNDBOARD_TIMEOUT

    while True:
        if time.time() > timeout:
            logger.info("Timeout: No input received.")
            logger.info("Exiting soundboard mode...")
            return

        key = read_keypad_input()

        if not key:
            time.sleep(0.1)  # Small delay to avoid excessive CPU usage
            continue

        logger.info(f"Key pressed: {key}")

        if key == "YELLOW":
            play_asset("PRESS", wait=False)
            logger.info("Exiting soundboard mode...")
            # Flash all lights to indicate exit
            BLINK_T = 0.15
            for _ in range(3):
                # Blink all lights to indicate reset
                set_all_lamps(LAMP_ON)
                time.sleep(BLINK_T)
                set_all_lamps(LAMP_OFF)
                time.sleep(BLINK_T)

            if KEYPAD_DEBOUNCE_DELAY > 3 * (2 * BLINK_T):
                time.sleep(KEYPAD_DEBOUNCE_DELAY - (3 * (2 * BLINK_T)))

            return

        elif key == "RED":
            play_asset("PRESS", wait=False)

            # Switch to the next bank
            if bank < MAX_BANK_NUMBER:
                bank += 1
                preload_soundboard_samples(bank)
            else:
                logger.info("Bank out of range")
                play_asset("BANK_OUT_OF_RANGE")
            timeout = time.time() + SOUNDBOARD_TIMEOUT

        elif key == "BLUE":
            play_asset("PRESS", wait=False)

            # Switch to the previous bank
            if bank > 0:
                bank -= 1
                preload_soundboard_samples(bank)
            else:
                logger.info("Bank out of range")
                play_asset("BANK_OUT_OF_RANGE")
            timeout = time.time() + SOUNDBOARD_TIMEOUT

        else:
            play_sample(key, wait=False)
            timeout = time.time() + SOUNDBOARD_TIMEOUT

        debounce_and_await_release()


def run():
    """
    Main event loop. Waits for song input, plays the song, and synchronizes lights.
    """

    preload_assets()

    def clear_animation():
        for _ in range(3):
            # Blink all lights to indicate reset
            set_all_lamps(LAMP_ON)
            time.sleep(0.15)
            set_all_lamps(LAMP_OFF)
            time.sleep(0.15)

    logger.info("Starting Jukebox service...")

    boot = True

    while True:
        key = idle(boot)
        boot = False

        logger.info("Evaluating keypad input...")

        input = ""

        while True:
            # Digit input
            if key in ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
                input += key
                logger.info(f"Input: {input}")

            # Reset input
            elif key == "R" and input:
                logger.info(f"Clearing input: {input}")
                input = ""
                clear_animation()

            # Confirm input
            elif key == "G" and input:
                logger.info(f"Input confirmed: {input}")
                play(int(input))
                break

            # Shuffle
            elif key == "BLUE":
                logger.info('"Shuffle" button pressed')
                while (
                    play(random.choice(reserved_track_numbers())) == PlayReturn.FINISHED
                ):
                    pass
                break

            # Soundboard Mode
            elif key == "YELLOW":
                logger.info('"Soundboard Mode" button pressed')
                soundboard()
                break

            # Timeout
            elif key is None:
                logger.info("Timeout: No input received.")
                if input:
                    clear_animation()
                break

            key = prompt_keypad_input()


def test_lights(args):
    """
    Test specific lights.

    Args:
        args (Namespace): Parsed command-line arguments.
    """
    if args.lights_top or args.lights:
        GPIO.output(GPIO_TOP_LAMPS, LAMP_ON)
        logger.info("Top lights on")

    if args.lights_lr or args.lights:
        GPIO.output(GPIO_LR_LAMPS, LAMP_ON)
        logger.info("Left-right lights on")

    if args.lights_bottom or args.lights:
        GPIO.output(GPIO_BOT_LAMPS, LAMP_ON)
        logger.info("Bottom lights on")

    # Wait for user input
    input("Press any key to turn off lights...")
    set_all_lamps(LAMP_OFF)


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

    # Initialize previous state to None
    previous_states = None

    try:
        while True:
            # Read current states of GPIO pins
            current_states = [GPIO.input(pin) for pin in GPIO_KEYPAD_PINS]

            # Update the terminal only if states differ from the previous ones
            if current_states != previous_states:
                clear_terminal()
                print("Keypad GPIO States")
                print("===================")
                print("GPIO | State")
                print("-----|-------")
                for pin, state in zip(GPIO_KEYPAD_PINS, current_states):
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
        "-l",
        "--log-level",
        type=str,
        default="info",
        help="Set the logging level (default: info)",
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
        "-l",
        "--log-level",
        type=str,
        default="info",
        help="Set the logging level (default: info)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        exit(0)

    if args.log_level:
        logging.basicConfig(level=args.log_level.upper())
    else:
        logging.basicConfig(level="DEBUG")  # Test mode should always be verbose

    # Run the appropriate mode

    if args.command == "test":

        init_gpios()

        if args.keypad:
            test_keypad()
        elif args.lights or args.lights_top or args.lights_lr or args.lights_bottom:
            try:
                test_lights(args)
            except KeyboardInterrupt:
                pass
            finally:
                set_all_lamps(LAMP_OFF)
                GPIO.cleanup()

    elif args.command == "run":
        if not JUKEBOX_SONGS_PATH:
            logger.error(
                "Please set the JUKEBOX_SONGS_PATH environment variable to the path of the songs directory."
            )
            exit(1)

        if not Path(JUKEBOX_SONGS_PATH).is_dir():
            logger.error(f"Invalid path to songs directory: {JUKEBOX_SONGS_PATH}")
            exit(1)

        init_gpios()

        try:
            run()
        except KeyboardInterrupt:
            pass
        finally:
            set_all_lamps(LAMP_OFF)
            GPIO.cleanup()

    elif args.command == "play":
        if not JUKEBOX_SONGS_PATH:
            logger.error(
                "Please set the JUKEBOX_SONGS_PATH environment variable to the path of the songs directory."
            )
            exit(1)

        if not Path(JUKEBOX_SONGS_PATH).is_dir():
            logger.error(f"Invalid path to songs directory: {JUKEBOX_SONGS_PATH}")
            exit(1)

        init_gpios()

        try:
            play(args.number)
        except KeyboardInterrupt:
            pass
        finally:
            set_all_lamps(LAMP_OFF)

    else:
        parser.print_help()
