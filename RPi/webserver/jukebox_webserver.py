from flask import Flask, render_template, request, redirect, url_for, jsonify
import os

app = Flask(__name__)

# Environment variable for the songs directory
JUKEBOX_SONGS_PATH = os.getenv("JUKEBOX_SONGS_PATH")

if JUKEBOX_SONGS_PATH is None:
    raise ValueError("JUKEBOX_SONGS_PATH environment variable is not set")

app.config["UPLOAD_FOLDER"] = JUKEBOX_SONGS_PATH
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
    Handle file upload for a specific track.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and file.filename.lower().endswith((".mp3", ".wav")):
        # Create the filename with the track number prefix
        extension = os.path.splitext(file.filename)[1]
        new_filename = f"{track_number}_{file.filename}"

        # Full path to save the file
        new_file_path = os.path.join(JUKEBOX_SONGS_PATH, new_filename)

        # Remove old file for the same track number
        for existing_file in os.listdir(JUKEBOX_SONGS_PATH):
            if existing_file.startswith(f"{track_number}_"):
                os.remove(os.path.join(JUKEBOX_SONGS_PATH, existing_file))

        # Save the new file
        file.save(new_file_path)
        return jsonify({"success": "File uploaded successfully!"}), 200

    return jsonify({"error": "Invalid file type. Only MP3 and WAV are allowed."}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
