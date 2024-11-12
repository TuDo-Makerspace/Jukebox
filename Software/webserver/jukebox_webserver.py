from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
import shutil
import subprocess
import re
from yt_dlp import YoutubeDL

app = Flask(__name__)

# Environment variable for the songs directory
JUKEBOX_SONGS_PATH = os.getenv("JUKEBOX_SONGS_PATH")
os.makedirs(JUKEBOX_SONGS_PATH, exist_ok=True)

# Temporary directory for Downloads
TMP_DIR = "/tmp/jukeboxdl"
os.makedirs(TMP_DIR, exist_ok=True)


def bpm_tag(file_path):
    """
    Run bpm-tag on the given file.
    """
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
            tracks[int(track_number)] = track_name

    slots = []
    for i in range(1, 401):
        slots.append(
            {
                "number": i,
                "name": tracks.get(i, ""),  # Empty string if no track uploaded
                "is_empty": i not in tracks,
            }
        )

    return render_template("index.html", slots=slots)


@app.route("/upload/<int:track_number>", methods=["POST"])
def upload(track_number):
    """
    Handle file upload or YouTube link for a specific track.
    """
    # Handle file uploads
    if "file" in request.files and request.files["file"].filename != "":
        file = request.files["file"]

        if not file.filename.lower().endswith((".mp3", ".wav")):
            return (
                jsonify({"error": "Invalid file type. Only MP3 and WAV are allowed."}),
                400,
            )

        # Save to tmp directory
        tmp_file_path = os.path.join(TMP_DIR, file.filename)
        file.save(tmp_file_path)

        # If the file is a WAV, convert it to MP3
        if tmp_file_path.lower().endswith(".wav"):
            if wav_to_mp3(tmp_file_path).returncode != 0:
                os.remove(tmp_file_path)
                return jsonify({"error": "Failed to convert WAV to MP3."}), 500

            # Update the file path to the MP3 file
            tmp_file_path = os.path.splitext(tmp_file_path)[0] + ".mp3"

            # Remove the WAV file
            os.remove(os.path.splitext(tmp_file_path)[0] + ".wav")

        # Add prefix to the filename
        new_filename = f"{track_number}_{os.path.basename(tmp_file_path)}"
        new_file_path = os.path.join(JUKEBOX_SONGS_PATH, new_filename)

        # Remove old file for the same track number
        for existing_file in os.listdir(JUKEBOX_SONGS_PATH):
            if existing_file.startswith(f"{track_number}_"):
                os.remove(os.path.join(JUKEBOX_SONGS_PATH, existing_file))

        # Move the file to the JUKEBOX_SONGS_PATH
        shutil.move(tmp_file_path, new_file_path)

        # Run bpm-tag to analyze the BPM of the song
        # Fail silently since this is not a critical operation
        if bpm_tag(new_file_path).returncode != 0:
            print(f"Failed to analyze BPM for {new_file_path}")

        return jsonify({"success": "File uploaded successfully!"}), 200

    # Handle YouTube link uploads
    ytdlp_link = request.form.get("ytdlp_link")
    if ytdlp_link:
        try:
            os.makedirs(TMP_DIR, exist_ok=True)
            tmp_file_template = os.path.join(
                TMP_DIR, f"{track_number}_%(title)s.%(ext)s"
            )

            # Download YouTube audio to /tmp
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": tmp_file_template,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }

            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(ytdlp_link, download=True)
                title = info_dict.get("title", None)

            # Find the downloaded file in /tmp
            downloaded_file = None
            for file in os.listdir(TMP_DIR):
                if file.startswith(f"{track_number}_") and file.endswith(".mp3"):
                    downloaded_file = os.path.join(TMP_DIR, file)
                    break

            if downloaded_file:
                # Move the downloaded file to the final destination
                final_filename = os.path.join(
                    JUKEBOX_SONGS_PATH, os.path.basename(downloaded_file)
                )

                # Remove old file for the same track number
                for existing_file in os.listdir(JUKEBOX_SONGS_PATH):
                    if existing_file.startswith(f"{track_number}_"):
                        os.remove(os.path.join(JUKEBOX_SONGS_PATH, existing_file))

                shutil.move(downloaded_file, final_filename)

                # Run bpm-tag to analyze the BPM of the song
                # Fail silently since this is not a critical operation
                if bpm_tag(final_filename).returncode != 0:
                    print(f"Failed to analyze BPM for {final_filename}")

                return (
                    jsonify({"success": "Audio downloaded successfully!"}),
                    200,
                )

            return jsonify({"error": "Failed to locate downloaded file."}), 500
        except Exception as e:
            return (
                jsonify({"error": f"Failed to download audio: {str(e)}"}),
                400,
            )

    spotify_link = request.form.get("spotify_link")
    if spotify_link:
        try:
            os.makedirs(TMP_DIR, exist_ok=True)

            # Store the current working directory
            cwd = os.getcwd()

            # cd to /tmp (spotdl doesn't have a --output option)
            os.chdir(TMP_DIR)

            command = ["spotdl", spotify_link]
            process = subprocess.run(command, capture_output=True, text=True)

            if process.returncode != 0:
                return {"error": process.stderr}, 400

            # Return to the original directory
            os.chdir(cwd)

            # Locate the downloaded file
            downloaded_file = None
            for file in os.listdir(TMP_DIR):
                if file.endswith(".mp3"):
                    downloaded_file = os.path.join(TMP_DIR, file)
                    break

            if not downloaded_file:
                return {"error": "Failed to locate the downloaded file."}, 500

            # Move the file to the JUKEBOX_SONGS_PATH with the track number prefix
            final_filename = os.path.join(
                JUKEBOX_SONGS_PATH,
                f"{track_number}_{os.path.basename(downloaded_file)}",
            )

            # Remove old file for the same track number
            for existing_file in os.listdir(JUKEBOX_SONGS_PATH):
                if existing_file.startswith(f"{track_number}_"):
                    os.remove(os.path.join(JUKEBOX_SONGS_PATH, existing_file))

            shutil.move(downloaded_file, final_filename)

            # Run bpm-tag to analyze the BPM of the song
            # Fail silently since this is not a critical operation
            if bpm_tag(final_filename).returncode != 0:
                print(f"Failed to analyze BPM for {final_filename}")

            return {"success": f"Track downloaded and saved to {final_filename}"}, 200

        except Exception as e:
            return {"error": f"An error occurred: {str(e)}"}, 500

    return jsonify({"error": "No file or link provided."}), 400


@app.route("/delete/<int:track_number>", methods=["POST"])
def delete(track_number):
    """
    Delete a track from the Jukebox.
    """
    for filename in os.listdir(JUKEBOX_SONGS_PATH):
        if filename.startswith(f"{track_number}_"):
            os.remove(os.path.join(JUKEBOX_SONGS_PATH, filename))
            return jsonify({"success": "Track deleted successfully!"}), 200

    return jsonify({"error": "Track not found."}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=True)
