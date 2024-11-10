from flask import Flask, render_template, request, redirect, url_for, jsonify
import os
import shutil
from yt_dlp import YoutubeDL

app = Flask(__name__)

# Environment variable for the songs directory
JUKEBOX_SONGS_PATH = os.getenv("JUKEBOX_SONGS_PATH", "./songs")
os.makedirs(JUKEBOX_SONGS_PATH, exist_ok=True)


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

        if file.filename.lower().endswith((".mp3", ".wav")):
            # Create the filename with the track number prefix
            extension = os.path.splitext(file.filename)[1]
            new_filename = f"{track_number}_{file.filename}"
            new_file_path = os.path.join(JUKEBOX_SONGS_PATH, new_filename)

            # Remove old file for the same track number
            for existing_file in os.listdir(JUKEBOX_SONGS_PATH):
                if existing_file.startswith(f"{track_number}_"):
                    os.remove(os.path.join(JUKEBOX_SONGS_PATH, existing_file))

            # Save the new file
            file.save(new_file_path)
            return jsonify({"success": "File uploaded successfully!"}), 200
        else:
            return (
                jsonify({"error": "Invalid file type. Only MP3 and WAV are allowed."}),
                400,
            )

    # Handle YouTube link uploads
    youtube_link = request.form.get("youtube_link")
    if youtube_link:
        try:
            tmp_dir = "/tmp"
            tmp_file_template = os.path.join(
                tmp_dir, f"{track_number}_%(title)s.%(ext)s"
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
                info_dict = ydl.extract_info(youtube_link, download=True)
                title = info_dict.get("title", None)

            # Find the downloaded file in /tmp
            downloaded_file = None
            for file in os.listdir(tmp_dir):
                if file.startswith(f"{track_number}_") and file.endswith(".mp3"):
                    downloaded_file = os.path.join(tmp_dir, file)
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

                return (
                    jsonify({"success": "YouTube audio downloaded successfully!"}),
                    200,
                )

            return jsonify({"error": "Failed to locate downloaded file."}), 500
        except Exception as e:
            return (
                jsonify({"error": f"Failed to download YouTube audio: {str(e)}"}),
                400,
            )

    return jsonify({"error": "No file or YouTube link provided."}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
