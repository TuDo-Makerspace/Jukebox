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

Description: Webserver to manage the Jukebox tracks.

Dependencies:
    System:
    - flask
    - yt-dlp
    - spotdl

Contributors:
- Patrick Pedersen <ctx.xda@gmail.com>
"""

import os
import shlex
import shutil
import subprocess
import re
import sys
import logging
import concurrent.futures
import tempfile

from flask import Flask, render_template, request, redirect, url_for, jsonify
from yt_dlp import YoutubeDL


################################################################
# Globals
################################################################

# Maximum characters displayed for track names
MAX_TRACK_NAME_LEN = 100

# Max track number
MAX_TRACK_NUMBER = 999

# Max bank number
MAX_BANK_NUMBER = 9

# Flask app
app = Flask(__name__)

# Logging
logging.basicConfig(
    level=logging.DEBUG if "-d" in sys.argv else logging.INFO,
    format="[%(levelname)-8s] %(name)s.%(funcName)s (line %(lineno)d): %(message)s",
)
logger = logging.getLogger(__name__)

# Path to store songs
try:
    JUKEBOX_SONGS_PATH = os.getenv("JUKEBOX_SONGS_PATH")
    os.makedirs(JUKEBOX_SONGS_PATH, exist_ok=True)
except:
    print("ERROR: JUKEBOX_SONGS_PATH not set.")
    exit(1)

# Path to store soundboard samples
try:
    JUKEBOX_SAMPLES_PATH = os.getenv("JUKEBOX_SOUNDBOARD_PATH")
    os.makedirs(JUKEBOX_SAMPLES_PATH, exist_ok=True)
except:
    print("ERROR: JUKEBOX_SOUNDBOARD_PATH not set.")
    exit(1)

# Temporary directory for Downloads
# Uploads/Downloads are stored in unique directories under this path
# This is to:
# - Prevent conflicts between multiple downloads
# - Ensure incomplete downloads are not used
# - Figure out track names after the download has completed
TMP_DIR = "/tmp/jukebox"

# Delete if already exists
if os.path.exists(TMP_DIR):
    shutil.rmtree(TMP_DIR)

os.makedirs(TMP_DIR, exist_ok=True)

# Maximum duration of remote commands
REMOTE_TIMEOUT = 60  # seconds

# Maximum duration of local downloads
LOCAL_DL_TIMEOUT = 60  # seconds

# Maximum Soundboard Sample Size
MAX_SAMPLE_SIZE = 30 * 1024 * 1024  # 30 MB

# Server (Ensure ssh keys are setup for passwordless login)
try:
    DL_SERVER_IP = os.getenv("JUKEBOX_DL_SERVER_IP")
    DL_SERVER_SSH_PORT = os.getenv("JUKEBOX_DL_SERVER_SSH_PORT")
    DL_SERVER_USER = os.getenv("JUKEBOX_DL_SERVER_USER")

    if not DL_SERVER_IP or not DL_SERVER_SSH_PORT or not DL_SERVER_USER:
        raise Exception("DL_SERVER_IP, DL_SERVER_SSH_PORT, or DL_SERVER_USER not set.")

    remote = True
except Exception as e:
    print("WARNING: Remote server not configured.")
    remote = False

################################################################
# Helper Functions
################################################################


def escape_path(path):
    """
    Escapes special characters in a file path using backslashes.
    """
    special_chars = " !\"#$&'()*,:;<=>?@[\\]^`{|}~"
    return "".join(f"\\{char}" if char in special_chars else char for char in path)


def create_temp_dir(base_dir=TMP_DIR):
    """
    Create a unique temporary directory under the base directory.
    """
    os.makedirs(base_dir, exist_ok=True)
    ret = tempfile.mkdtemp(dir=base_dir)
    logger.info(f"Created temporary directory: {ret}")
    return ret


def cleanup_temp_dir(temp_dir):
    """
    Safely remove a temporary directory.
    """
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
        logger.info(f"Removed temporary directory: {temp_dir}")
    else:
        logger.warning(f"Ignoring cleanup for non-existent directory: {temp_dir}")


def bpm_tag(file_path):
    """
    Run bpm-tag on the given file.
    """
    logger.info("Analyzing BPM for {file_path}...")

    result = subprocess.run(
        ["bpm-tag", file_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return result


def wav_to_mp3(file_path):
    """
    Convert a WAV file to MP3 using ffmpeg.
    """
    mp3_file = os.path.splitext(file_path)[0] + ".mp3"
    result = subprocess.run(
        ["ffmpeg", "-i", file_path, "-q:a", "0", mp3_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return result


def mp3_to_wav(file_path):
    """
    Convert a MP3 file to WAV using ffmpeg.
    """
    wav_file = os.path.splitext(file_path)[0] + ".wav"
    result = subprocess.run(
        ["ffmpeg", "-i", file_path, wav_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return result


def is_yt_link(link):
    return re.match(r"^(http(s)?:\/\/)?((w){3}.)?youtu(be|.be)?(\.com)?\/.+", link)


def is_yt_video(link):
    return re.match(
        r"(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[^\s]+", link
    )


def yt_dlp(link, out_dir, format="mp3"):
    """
    Download an audio file from a YouTube link using yt-dlp.
    """

    if is_yt_link(link) and not is_yt_video(link):
        raise ValueError("Youtube link is not a video link.")

    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": format,
                "preferredquality": "192",
            }
        ],
    }

    # Get current directory
    cwd = os.getcwd()

    # Change to the output directory
    os.chdir(out_dir)

    logger.info(f"YoutubeDL: Downloading audio from {link}")

    def download():
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])

    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(download)
            future.result(timeout=LOCAL_DL_TIMEOUT)  # Enforce the timeout
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"Download timed out. Please validate the link.")
    except Exception as e:
        raise RuntimeError(f"An error occurred: {str(e)}")

    # Go back to the original directory
    os.chdir(cwd)

    # Return downloaded file path
    logger.info(f"YoutubeDL: Downloaded file: {os.listdir(out_dir)[0]}")
    return os.listdir(out_dir)[0]


def spotdl(link, out_dir, format="mp3"):
    """
    Download an audio file from a Spotify link using spotdl.
    """
    if "playlist" in link.lower():
        raise ValueError(
            "Playlists are not allowed. Please provide a single track URL."
        )

    # Get current directory
    cwd = os.getcwd()

    # Change to the output directory
    os.chdir(out_dir)

    logger.info(f"SpotDL: Downloading audio from {link}")
    command = ["spotdl", "--format", format, link]

    logger.debug(f"Running command: {command}")

    result = subprocess.run(command, capture_output=True, text=True)

    # Go back to the original directory
    os.chdir(cwd)

    if result.returncode != 0:
        logger.error(f"SpotDL: Failed to download audio: {result.stderr}")
        raise Exception(f"Failed to download audio: {result.stderr}")

    # Return downloaded file path
    logger.info(f"SpotDL: Downloaded file: {os.listdir(out_dir)[0]}")
    return os.listdir(out_dir)[0]


def remote_mkdir(path):
    """
    Create a directory on a remote server.
    """
    logger.info(f"REMOTE: Creating directory: {path}")

    escaped_path = escape_path(path)
    command = f"mkdir -p {escaped_path}"

    logger.debug(f"Running command: {command}")

    ssh_command = f'ssh -o StrictHostKeyChecking=no -p {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP} "{command}"'
    result = subprocess.run(
        ssh_command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        logger.error(f"Failed to create directory: {result.stderr}")
        raise Exception(f"Failed to create directory: {result.stderr}")

    logger.info(f"REMOTE: Directory created: {path}")


def remote_rmdir(path):
    """
    Remove a directory on a remote server.
    """
    logger.info(f"REMOTE: Removing directory: {path}")

    escaped_path = escape_path(path)
    command = f"rm -rf {escaped_path}"

    logger.debug(f"Running command: {command}")

    ssh_command = f'ssh -o StrictHostKeyChecking=no -p {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP} "{command}"'
    result = subprocess.run(
        ssh_command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        logger.error(f"Failed to remove directory: {result.stderr}")
        raise Exception(f"Failed to remove directory: {result.stderr}")

    logger.info(f"REMOTE: Directory removed: {path}")


def cp_from_remote(src, dest):
    """
    Copy a file from a remote server to the local machine.
    """
    logger.info(f"REMOTE: Copying file remote ({src}) to local ({dest})")

    escaped_src = escape_path(src)
    escaped_dest = escape_path(dest)

    command = f"scp -P {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP}:{escaped_src} {escaped_dest}"

    logger.debug(f"Running command: {command}")

    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        logger.error(f"Failed to copy file: {result.stderr}")
        raise Exception(f"Failed to copy file: {result.stderr}")

    logger.info(f"REMOTE: File copied remote ({src}) to local ({dest})")


def mv_from_remote(src, dest):
    """
    Move a file from a remote server to the local machine.
    """
    logger.info(f"REMOTE: Moving file remote ({src}) to local ({dest})")

    escaped_src = escape_path(src)
    escaped_dest = escape_path(dest)

    command = f"scp -P {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP}:{escaped_src} {escaped_dest}"

    logger.debug(f"Running command: {command}")

    result = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        logger.error(f"Failed to move file: {result.stderr}")
        raise Exception(f"Failed to move file: {result.stderr}")

    # Remove the file on the remote server
    rm_remote_file(src)

    logger.info(f"REMOTE: File moved remote ({src}) to local ({dest})")


def rm_remote_file(file):
    """
    Remove a file on a remote server.
    """
    logger.info(f"REMOTE: Removing file: {file}")

    escaped_file = escape_path(file)
    command = f"rm {escaped_file}"

    logger.debug(f"Running command: {command}")

    ssh_command = f'ssh -o StrictHostKeyChecking=no -p {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP} "{command}"'
    result = subprocess.run(
        ssh_command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        raise Exception(f"Failed to remove file: {result.stderr}")

    logger.info(f"REMOTE: File removed: {file}")


def rm_remote_dir(dir):
    """
    Remove a directory on a remote server.
    """
    logger.info(f"REMOTE: Removing directory: {dir}")

    escaped_dir = escape_path(dir)
    command = f"rm -rf {escaped_dir}"

    logger.debug(f"Running command: {command}")

    ssh_command = f'ssh -o StrictHostKeyChecking=no -p {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP} "{command}"'
    result = subprocess.run(
        ssh_command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        raise Exception(f"Failed to remove directory: {result.stderr}")

    logger.info(f"REMOTE: Directory removed: {dir}")


def remote_yt_dlp_mp3(link, out_dir, format="mp3"):
    """
    Download an audio file from a YouTube link using yt-dlp on a remote server.
    """
    if is_yt_link(link) and not is_yt_video(link):
        raise ValueError("Youtube link is not a video link.")

    logger.info(f"REMOTE: YoutubeDL: Downloading audio from {link}")

    escaped_link = escape_path(link)
    escaped_out_dir = escape_path(out_dir)

    command = f"source ~/venv/bin/activate && cd {escaped_out_dir} && yt-dlp --no-playlist -x --audio-format {format} {escaped_link} && ls {escaped_out_dir}"
    ssh_command = f'ssh -o StrictHostKeyChecking=no -p {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP} "{command}"'

    logger.debug(f"Running command: {ssh_command}")

    result = subprocess.run(
        ssh_command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        raise Exception(f"Failed to download audio: {result.stderr}")

    file = result.stdout.split("\n")[-2]
    logger.info(f"REMOTE: Downloaded file: {file}")

    # Return downloaded file path
    return out_dir + "/" + file


def remote_spotdl(link, out_dir, format="mp3"):
    """
    Download an audio file from a Spotify link using spotdl on a remote server.
    """
    if "playlist" in link.lower():
        raise ValueError(
            "Playlists are not allowed. Please provide a single track URL."
        )

    logger.info(f"REMOTE: SpotDL: Downloading audio from {link}")

    escaped_link = escape_path(link)
    escaped_out_dir = escape_path(out_dir)

    command = f"source ~/venv/bin/activate && cd {escaped_out_dir} && spotdl --format {format} {escaped_link} && ls {escaped_out_dir}"
    ssh_command = f'ssh -o StrictHostKeyChecking=no -p {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP} "{command}"'

    logger.debug(f"Running command: {ssh_command}")

    result = subprocess.run(
        ssh_command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    if result.returncode != 0:
        raise Exception(f"Failed to download audio: {result.stderr}")

    file = result.stdout.split("\n")[-2]
    logger.info(f"REMOTE: Downloaded file: {file}")

    # Return downloaded file path
    return out_dir + "/" + file


def remote_bpm_tag(file):
    """
    Run bpm-tag on a file on a remote server.
    """
    escaped_file = escape_path(file)
    command = f"bpm-tag {escaped_file}"

    logger.debug(f"Running command: {command}")

    ssh_command = f'ssh -o StrictHostKeyChecking=no -p {DL_SERVER_SSH_PORT} {DL_SERVER_USER}@{DL_SERVER_IP} "{command}"'
    result = subprocess.run(
        ssh_command, shell=True, capture_output=True, text=True, timeout=REMOTE_TIMEOUT
    )

    logger.info(f"REMOTE: Analyzed BPM for {file}")

    if result.returncode != 0:
        logger.warning(f"Failed to analyze BPM for {file}")

    logger.info(f"REMOTE: BPM analyzed for {file}")


################################################################
# Routes
################################################################


@app.route("/")
def index():
    """
    Serve the main page with the list of tracks.
    """
    tracks = {}
    for filename in os.listdir(JUKEBOX_SONGS_PATH):
        if filename.lower().endswith((".mp3", ".wav")):
            track_number = filename.split("_")[0]
            track_name = filename.split("_", 1)[1]
            track_name = os.path.splitext(track_name)[0]

            # If trackname exceeds the maximum length, truncate it
            if len(track_name) > MAX_TRACK_NAME_LEN:
                track_name = track_name[:MAX_TRACK_NAME_LEN] + "..."

            tracks[int(track_number)] = track_name

    slots = []
    for i in range(0, MAX_TRACK_NUMBER + 1):
        slots.append(
            {
                "number": i,
                "name": tracks.get(i, ""),  # Empty string if no track uploaded
                "is_empty": i not in tracks,
            }
        )

    return render_template("index.html", slots=slots)


@app.route("/samples")
def samples_redirect():
    """
    Redirect to the samples page to bank 0.
    """
    return redirect(url_for("samples_for_bank", bank=0))


@app.route("/samples/<int:bank>")
def samples_for_bank(bank):
    # 1) Validate bank
    if bank < 0 or bank > MAX_BANK_NUMBER:
        # Redirect to bank MAX_BANK_NUMBER
        return redirect(url_for("samples_for_bank", bank=MAX_BANK_NUMBER))

    bank_dir = os.path.join(JUKEBOX_SAMPLES_PATH, str(bank))

    # 2) Make sure bank folder exists. If you want it automatically created, do:
    if not os.path.isdir(bank_dir):
        os.makedirs(bank_dir, exist_ok=True)

    # 3) Gather existing .wav files
    samples = {}
    for filename in os.listdir(bank_dir):
        if filename.lower().endswith(".wav"):
            # Example naming: "3_mySample.wav"
            sample_key = filename.split("_")[0].upper()
            sample_name = filename.split("_", 1)[1] if "_" in filename else filename
            sample_name = os.path.splitext(sample_name)[0]

            samples[sample_key] = sample_name

    # Define the valid keys
    valid_keys = [str(i) for i in range(10)] + ["R", "G"]

    slots = []
    for key in valid_keys:
        slots.append(
            {"key": key, "name": samples.get(key, ""), "is_empty": key not in samples}
        )

    # 4) Render your existing soundboard HTML template,
    #    but pass along the bank number and slots
    return render_template(
        "samples.html", slots=slots, bank=bank, max_bank=MAX_BANK_NUMBER
    )


@app.route("/upload/<int:track_number>", methods=["POST"])
def upload(track_number):
    """
    Handle file upload or YouTube link for a specific track.
    """
    logger.info(f"Received upload request for track {track_number}")

    if track_number < 0 or track_number > 999:
        logger.error("Track number out of range.")
        return jsonify({"error": " Track number out of range."}), 400

    # Get the optional name field
    custom_name = request.form.get("name", "").strip()

    # Strip name to max 100 characters
    custom_name = custom_name[:MAX_TRACK_NAME_LEN]

    # Create a temporary directory for the download
    temp_dir = create_temp_dir()

    ################################################################
    # File Uploads
    ################################################################

    if "file" in request.files and request.files["file"].filename != "":
        file = request.files["file"]

        logger.info(f"Received file: {file.filename}")

        if not file.filename.lower().endswith((".mp3", ".wav")):
            cleanup_temp_dir(temp_dir)
            logger.error("Invalid file type. Only MP3 and WAV are allowed.")
            return (
                jsonify({"error": "Invalid file type. Only MP3 and WAV are allowed."}),
                400,
            )

        # Save to tmp directory
        tmp_file_path = os.path.join(temp_dir, file.filename)
        file.save(tmp_file_path)
        logger.info(f"File temporarily saved to {tmp_file_path}")

        # If the file is a WAV, convert it to MP3
        if tmp_file_path.lower().endswith(".wav"):
            logger.info("Converting WAV to MP3")
            if wav_to_mp3(tmp_file_path).returncode != 0:
                os.remove(tmp_file_path)
                cleanup_temp_dir(temp_dir)
                logger.error("Failed to convert WAV to MP3.")
                return jsonify({"error": "Failed to convert WAV to MP3."}), 500

            # Update the file path to the MP3 file
            tmp_file_path = os.path.splitext(tmp_file_path)[0] + ".mp3"

            # Remove the WAV file
            os.remove(os.path.splitext(tmp_file_path)[0] + ".wav")

        # Add track number and (if provided) custom name to the filename
        if custom_name:
            new_filename = f"{track_number}_{custom_name}.mp3"
        else:
            # Use the original filename as the track name
            new_filename = f"{track_number}_{os.path.basename(tmp_file_path)}"

        new_file_path = os.path.join(JUKEBOX_SONGS_PATH, new_filename)

        # Remove old file for the same track number
        for existing_file in os.listdir(JUKEBOX_SONGS_PATH):
            if existing_file.startswith(f"{track_number}_"):
                os.remove(os.path.join(JUKEBOX_SONGS_PATH, existing_file))
                logger.info(f"Removed existing track: {existing_file}")

        # Move the file to the JUKEBOX_SONGS_PATH
        shutil.move(tmp_file_path, new_file_path)
        logger.info(f"File moved to {new_file_path}")

        # Run bpm-tag to analyze the BPM of the song
        # Fail silently since this is not a critical operation
        if bpm_tag(new_file_path).returncode != 0:
            logger.warning(f"Failed to analyze BPM for {new_file_path}")
        else:
            logger.info(f"BPM analyzed for {new_file_path}")

        cleanup_temp_dir(temp_dir)
        logger.info("File uploaded successfully!")
        return jsonify({"success": "File uploaded successfully!"}), 200

    ################################################################
    # Links
    ################################################################

    ytdlp_link = request.form.get("ytdlp_link")
    spotify_link = request.form.get("spotify_link")

    if ytdlp_link or spotify_link:

        bpm_analyzed = False

        # YT-DLP link
        if ytdlp_link:
            logger.info(f"Received YouTube link: {ytdlp_link}")

            errmsg = None

            # Try remote download first
            try:
                logger.info("Trying remote download...")

                if not remote:
                    raise Exception("Remote server not configured.")

                remote_rmdir(temp_dir)
                remote_mkdir(temp_dir)
                out = remote_yt_dlp_mp3(ytdlp_link, temp_dir)
                remote_bpm_tag(out)
                cp_from_remote(f"{out}", temp_dir)
                rm_remote_dir(temp_dir)
                bpm_analyzed = True
                logger.info("Remote download successful.")

            # If remote download fails, try local download
            except Exception as e:
                logger.warning(f"Remote download failed: {str(e)}")
                logger.info("Trying local download...")
                try:
                    out = yt_dlp(ytdlp_link, temp_dir)
                    logger.info("Local download successful.")
                except Exception as e:
                    errmsg = str(e)

            if errmsg:
                cleanup_temp_dir(temp_dir)
                logger.error(f"Failed to download audio: {errmsg}")
                return (
                    jsonify({"error": f"Failed to download audio: {errmsg}"}),
                    400,
                )

        # Spotify link
        else:

            errmsg = None

            # Try remote download first
            try:
                logger.info(f"Received Spotify link: {spotify_link}")
                if not remote:
                    logger.info("Remote server not configured.")
                    raise Exception("Remote server not configured.")

                remote_rmdir(temp_dir)
                remote_mkdir(temp_dir)
                out = remote_spotdl(spotify_link, temp_dir)
                remote_bpm_tag(out)
                mv_from_remote(f"{out}", temp_dir)
                bpm_analyzed = True
                logger.info("Remote download successful.")

            # If remote download fails, try local download
            except Exception as e:
                try:
                    logger.warning(f"Remote download failed: {str(e)}")
                    logger.info("Trying local download...")
                    out = spotdl(spotify_link, temp_dir)
                    logger.info("Local download successful.")
                except Exception as e:
                    errmsg = str(e)

            if errmsg:
                cleanup_temp_dir(temp_dir)
                logger.error(f"Failed to download audio: {errmsg}")
                return (
                    jsonify({"error": f"Failed to download audio: {errmsg}"}),
                    400,
                )

        tmp_out = os.path.join(temp_dir, out)
        logger.info(f"Download temporarily saved to {tmp_out}")

        # Move the file to the JUKEBOX_SONGS_PATH and run bpm-tag
        try:
            # Remove old file for the same track number
            for existing_file in os.listdir(JUKEBOX_SONGS_PATH):
                if existing_file.startswith(f"{track_number}_"):
                    os.remove(os.path.join(JUKEBOX_SONGS_PATH, existing_file))
                    logger.info(f"Removed existing track: {existing_file}")

            # Add track number and (if provided) custom name to the filename
            if custom_name:
                final_out = os.path.join(
                    JUKEBOX_SONGS_PATH, f"{track_number}_{custom_name}.mp3"
                )

            # Use the original filename as the track name
            else:
                final_out = os.path.join(
                    JUKEBOX_SONGS_PATH, f"{track_number}_{os.path.basename(out)}"
                )

            # Move the file to the JUKEBOX_SONGS_PATH
            shutil.move(
                tmp_out,
                final_out,
            )

            logger.info(f"File moved to {final_out}")

            # Run bpm-tag to analyze the BPM of the song
            # Fail silently since this is not a critical operation
            if not bpm_analyzed and bpm_tag(final_out).returncode != 0:
                logger.warning(f"Failed to analyze BPM for {final_out}")

            cleanup_temp_dir(temp_dir)
            logger.info("Audio downloaded successfully!")

            return (
                jsonify({"success": "Audio downloaded successfully!"}),
                200,
            )

        except Exception as e:
            cleanup_temp_dir(temp_dir)
            logger.error(f"Download failed: {str(e)}")
            return (
                jsonify({"error": f"Download failed: {str(e)}"}),
                400,
            )

    cleanup_temp_dir(temp_dir)
    logger.error("No file or link provided.")
    return jsonify({"error": "No file or link provided."}), 400


@app.route("/upload_sample/<int:bank>/<sample_key>", methods=["POST"])
def upload_sample(bank, sample_key):
    """
    Handle file upload for a specific sample.
    """
    logger.info(f"Received upload request for sample {sample_key}")

    if bank < 0 or bank > MAX_BANK_NUMBER:
        logger.error("Bank out of range.")
        return jsonify({"error": "Bank out of range."}), 400

    bank_dir = os.path.join(JUKEBOX_SAMPLES_PATH, str(bank))
    os.makedirs(bank_dir, exist_ok=True)

    # Valid keys include "0-9", "R", "G"
    valid_keys = [str(i) for i in range(10)] + ["R", "G"]
    if sample_key.upper() not in valid_keys:
        logger.error(f"Invalid sample key: {sample_key}")
        return jsonify({"error": "Invalid sample key."}), 400

    # Get the optional name field
    custom_name = request.form.get("name", "").strip()

    # Strip name to max 100 characters
    custom_name = custom_name[:MAX_TRACK_NAME_LEN]

    # Create a temporary directory for the download
    temp_dir = create_temp_dir()

    ################################################################
    # File Uploads
    ################################################################

    if "file" in request.files and request.files["file"].filename != "":
        file = request.files["file"]

        logger.info(f"Received file: {file.filename}")

        if not file.filename.lower().endswith((".mp3", ".wav")):
            cleanup_temp_dir(temp_dir)
            logger.error("Invalid file type. Only MP3 and WAV are allowed.")
            return (
                jsonify({"error": "Invalid file type. Only MP3 and WAV are allowed."}),
                400,
            )

        # Save to tmp directory
        tmp_file_path = os.path.join(temp_dir, file.filename)
        file.save(tmp_file_path)
        logger.info(f"File temporarily saved to {tmp_file_path}")

        # If the file is a MP3, convert it to WAV
        if tmp_file_path.lower().endswith(".mp3"):
            logger.info("Converting MP3 to WAV")
            if mp3_to_wav(tmp_file_path).returncode != 0:
                os.remove(tmp_file_path)
                cleanup_temp_dir(temp_dir)
                logger.error("Failed to convert MP3 to WAV.")
                return jsonify({"error": "Failed to convert MP3 to WAV."}), 500

            # Update the file path to the WAV file
            tmp_file_path = os.path.splitext(tmp_file_path)[0] + ".wav"

            # Remove the MP3 file
            os.remove(os.path.splitext(tmp_file_path)[0] + ".mp3")

        # If the file is a WAV, convert it to 44100 Hz if necessary
        else:
            try:
                # Get sampling rate of the WAV file
                result = subprocess.run(
                    [
                        "ffprobe",
                        "-i",
                        tmp_file_path,
                        "-show_entries",
                        "stream=sample_rate",
                        "-v",
                        "quiet",
                        "-of",
                        "csv=p=0",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                if result.returncode != 0:
                    raise Exception(f"Failed to get sampling rate: {result.stderr}")

                sampling_rate = int(result.stdout.strip())

                # If the sampling rate is not 44100 or 48000, convert the file to 44100 Hz
                if sampling_rate not in [44100, 48000]:
                    logger.info(
                        f"Converting WAV file with sampling rate {sampling_rate} to 44100 Hz"
                    )

                    converted_file = os.path.splitext(tmp_file_path)[0] + "_44100.wav"

                    convert_result = subprocess.run(
                        ["ffmpeg", "-i", tmp_file_path, "-ar", "44100", converted_file],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )

                    if convert_result.returncode != 0:
                        raise Exception(
                            f"Failed to convert WAV file: {convert_result.stderr}"
                        )

                    # Replace the original file with the converted one
                    os.remove(tmp_file_path)
                    os.rename(converted_file, tmp_file_path)

            except Exception as e:
                os.remove(tmp_file_path)
                cleanup_temp_dir(temp_dir)
                logger.error(f"Failed to convert WAV file: {str(e)}")
                return jsonify({"error": f"Failed to convert WAV file: {str(e)}"}), 500

        logger.info("Trimming silence from the beginning with sox (file upload).")
        trimmed_file = os.path.splitext(tmp_file_path)[0] + "_trimmed.wav"
        trim_proc = subprocess.run(
            ["sox", tmp_file_path, trimmed_file, "silence", "1", "0.1", "1%"],
            capture_output=True,
            text=True,
        )
        if trim_proc.returncode != 0:
            logger.warning(f"sox failed to remove silence: {trim_proc.stderr}")
            # We won't fail the request if sox fails; proceed with original
        else:
            os.remove(tmp_file_path)
            os.rename(trimmed_file, tmp_file_path)
            logger.info("Silence from the beginning successfully removed!")

        # Check if file size exceeds MAX_SAMPLE_SIZE
        if os.path.getsize(tmp_file_path) > MAX_SAMPLE_SIZE:
            os.remove(tmp_file_path)
            cleanup_temp_dir(temp_dir)
            logger.error(
                f"File size exceeds limit of {MAX_SAMPLE_SIZE / (1024*1024)}MB"
            )
            return (
                jsonify(
                    {
                        "error": f"File size exceeds the limit of {MAX_SAMPLE_SIZE / (1024 * 1024):.2f} MB. Please note that MP3 files are converted to WAV, which may increase their size."
                    }
                ),
                400,
            )

        # Add sample number and (if provided) custom name to the filename
        if custom_name:
            new_filename = f"{sample_key}_{custom_name}.wav"
        else:
            # Use the original filename as the sample name
            new_filename = f"{sample_key}_{os.path.basename(tmp_file_path)}"

        new_file_path = os.path.join(bank_dir, new_filename)

        # Remove old file for the same sample number
        for existing_file in os.listdir(bank_dir):
            if existing_file.startswith(f"{sample_key}_"):
                os.remove(os.path.join(bank_dir, existing_file))
                logger.info(f"Removed existing sample: {existing_file}")

        # Move the file to the bank directory
        shutil.move(tmp_file_path, new_file_path)
        logger.info(f"File moved to {new_file_path}")

        cleanup_temp_dir(temp_dir)
        logger.info("File uploaded successfully!")
        return jsonify({"success": "File uploaded successfully!"}), 200

    ################################################################
    # Links
    ################################################################

    ytdlp_link = request.form.get("ytdlp_link")
    spotify_link = request.form.get("spotify_link")

    if ytdlp_link or spotify_link:

        # YT-DLP link
        if ytdlp_link:
            logger.info(f"Received YouTube link: {ytdlp_link}")

            errmsg = None

            # Try remote download first
            try:
                logger.info("Trying remote download...")
                if not remote:
                    raise Exception("Remote server not configured.")

                remote_rmdir(temp_dir)
                remote_mkdir(temp_dir)
                out = remote_yt_dlp_mp3(ytdlp_link, temp_dir, format="wav")
                remote_bpm_tag(out)
                cp_from_remote(f"{out}", temp_dir)
                rm_remote_dir(temp_dir)
                logger.info("Remote download successful.")

            except Exception as e:
                logger.warning(f"Remote download failed: {str(e)}")
                logger.info("Trying local download...")
                try:
                    out = yt_dlp(ytdlp_link, temp_dir, format="wav")
                    logger.info("Local download successful.")
                except Exception as e:
                    errmsg = str(e)

            if errmsg:
                cleanup_temp_dir(temp_dir)
                logger.error(f"Failed to download audio: {errmsg}")
                return (
                    jsonify({"error": f"Failed to download audio: {errmsg}"}),
                    400,
                )

        # Spotify link
        else:
            logger.info(f"Received Spotify link: {spotify_link}")

            errmsg = None

            # Try remote download first
            try:
                logger.info(f"Received Spotify link: {spotify_link}")
                if not remote:
                    logger.info("Remote server not configured.")
                    raise Exception("Remote server not configured.")

                remote_rmdir(temp_dir)
                remote_mkdir(temp_dir)
                out = remote_spotdl(spotify_link, temp_dir, format="wav")
                remote_bpm_tag(out)
                mv_from_remote(f"{out}", temp_dir)
                logger.info("Remote download successful.")

            except Exception as e:
                try:
                    logger.warning(f"Remote download failed: {str(e)}")
                    logger.info("Trying local download...")
                    out = spotdl(spotify_link, temp_dir, format="wav")
                    logger.info("Local download successful.")
                except Exception as e:
                    errmsg = str(e)

            if errmsg:
                cleanup_temp_dir(temp_dir)
                logger.error(f"Failed to download audio: {errmsg}")
                return (
                    jsonify({"error": f"Failed to download audio: {errmsg}"}),
                    400,
                )

        tmp_out = os.path.join(temp_dir, out)
        logger.info(f"Download temporarily saved to {tmp_out}")

        logger.info("Trimming silence from the beginning with sox (link).")
        trimmed_file = os.path.splitext(tmp_out)[0] + "_trimmed.wav"
        trim_proc = subprocess.run(
            ["sox", tmp_out, trimmed_file, "silence", "1", "0.1", "1%"],
            capture_output=True,
            text=True,
        )
        if trim_proc.returncode != 0:
            logger.warning(f"sox failed to remove silence: {trim_proc.stderr}")
            # We'll proceed with the untrimmed file if sox fails
        else:
            os.remove(tmp_out)
            os.rename(trimmed_file, tmp_out)
            logger.info("Silence from the beginning successfully removed!")

        # Check if file size exceeds MAX_SAMPLE_SIZE
        if os.path.getsize(tmp_out) > MAX_SAMPLE_SIZE:
            os.remove(tmp_out)
            cleanup_temp_dir(temp_dir)
            logger.error(
                f"File size exceeds limit of {MAX_SAMPLE_SIZE / (1024*1024)}MB"
            )
            return (
                jsonify(
                    {
                        "error": f"File size exceeds the limit of {MAX_SAMPLE_SIZE / (1024 * 1024):.2f} MB. Please choose a link for a shorter audio clip."
                    }
                ),
                400,
            )

        # Move the file to the bank directory
        try:
            # Remove old file for the same sample number
            for existing_file in os.listdir(bank_dir):
                if existing_file.startswith(f"{sample_key}_"):
                    os.remove(os.path.join(bank_dir, existing_file))
                    logger.info(f"Removed existing sample: {existing_file}")

            # Add sample number and (if provided) custom name to the filename
            if custom_name:
                final_out = os.path.join(bank_dir, f"{sample_key}_{custom_name}.wav")
            else:
                # Use the original filename as the sample name
                final_out = os.path.join(
                    bank_dir, f"{sample_key}_{os.path.basename(out)}"
                )

            # Move the file to the bank_dir
            shutil.move(
                tmp_out,
                final_out,
            )

            logger.info(f"File moved to {final_out}")

            cleanup_temp_dir(temp_dir)
            logger.info("Audio downloaded successfully!")
            return (
                jsonify({"success": "Audio downloaded successfully!"}),
                200,
            )
        except Exception as e:
            cleanup_temp_dir(temp_dir)
            logger.error(f"Download failed: {str(e)}")
            return (
                jsonify({"error": f"Download failed: {str(e)}"}),
                400,
            )

    cleanup_temp_dir(temp_dir)
    logger.error("No file provided.")
    return jsonify({"error": "No file provided."}), 400


@app.route("/delete/<int:track_number>", methods=["POST"])
def delete(track_number):
    """
    Delete a track from the Jukebox.
    """
    logger.info(f"Deleting track {track_number}")

    for filename in os.listdir(JUKEBOX_SONGS_PATH):
        if filename.startswith(f"{track_number}_"):
            os.remove(os.path.join(JUKEBOX_SONGS_PATH, filename))
            logger.info(f"Track {track_number} deleted successfully.")
            return jsonify({"success": "Track deleted successfully!"}), 200

    logger.error(f"Track {track_number} not found.")
    return jsonify({"error": "Track not found."}), 404


@app.route("/delete_sample/<int:bank>/<sample_key>", methods=["POST"])
def delete_sample(bank, sample_key):
    """
    Delete a sample from the Jukebox.
    """
    if bank < 0 or bank > MAX_BANK_NUMBER:
        logger.error("Bank out of range.")
        return jsonify({"error": "Bank out of range."}), 400

    logger.info(f"Deleting sample {sample_key} from bank {bank}")

    bank_dir = os.path.join(JUKEBOX_SAMPLES_PATH, str(bank))

    if not os.path.isdir(bank_dir):
        logger.error(f"Bank {bank} does not exist.")
        return jsonify({"error": "Bank does not exist."}), 404

    for filename in os.listdir(bank_dir):
        if filename.startswith(f"{sample_key}_"):
            os.remove(os.path.join(bank_dir, filename))
            logger.info(f"Sample {sample_key} deleted successfully.")
            return jsonify({"success": "Sample deleted successfully!"}), 200

    logger.error(f"Sample {sample_key} not found.")
    return jsonify({"error": "Sample not found."}), 404


if __name__ == "__main__":
    if "-d" in sys.argv:
        port = 5000
        debug = True
        logging.basicConfig(level=logging.DEBUG)
    else:
        port = 80
        debug = False
        logging.basicConfig(level=logging.INFO)

    app.run(host="0.0.0.0", port=port, debug=debug)
