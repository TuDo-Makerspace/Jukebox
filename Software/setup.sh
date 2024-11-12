#!/bin/bash

# Bash installer for Jukebox

# Warning message
echo "******************************************************************"
echo "NOTE: This installer is intended to be executed on a Raspberry Pi."
echo "It is not recommended or practical to install this program on"
echo "another device. The program uses the RPi.GPIO library, which is"
echo "specific to Raspberry Pi hardware."
echo "******************************************************************"

# Prompt for acknowledgment
read -p "Do you wish to continue? (y/N): " CONTINUE_INSTALL

if [[ "$CONTINUE_INSTALL" != "y" && "$CONTINUE_INSTALL" != "Y" ]]; then
    echo "Installation aborted."
    exit 1
fi

# Function to check if the script is run as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo "This script must be run as root. Please use sudo."
        exit 1
    fi
}

# Check if running as root
check_root

# Prompt for the songs path
read -p "Enter the absolute path for the songs directory: " SONGS_PATH

# Validate the provided path
if [[ ! -d "$SONGS_PATH" ]]; then
    echo "Error: The provided path is not a valid directory."
    exit 1
fi

# Permanently set the JUKEBOX_SONGS_PATH environment variable
echo "Setting JUKEBOX_SONGS_PATH environment variable..."
echo "export JUKEBOX_SONGS_PATH=$SONGS_PATH" >> /etc/environment

# Reload environment variables
source /etc/environment

# Obtain the path of jukebox.py and webserver directory
INSTALLER_PATH="$(dirname "$(realpath "$0")")"
JUKEBOX_SCRIPT="$INSTALLER_PATH/jukebox.py"
WEBSERVER_SCRIPT="$INSTALLER_PATH/webserver/jukebox_webserver.py"
TEMPLATES_DIR="$INSTALLER_PATH/webserver/templates"

if [[ ! -f "$JUKEBOX_SCRIPT" ]]; then
    echo "Error: jukebox.py not found in the installer's directory ($INSTALLER_PATH)."
    exit 1
fi

if [[ ! -f "$WEBSERVER_SCRIPT" ]]; then
    echo "Error: jukebox_webserver.py not found in the webserver directory ($INSTALLER_PATH/webserver)."
    exit 1
fi

if [[ ! -d "$TEMPLATES_DIR" ]]; then
    echo "Error: templates directory not found in the webserver directory ($INSTALLER_PATH/webserver)."
    exit 1
fi

echo "Jukebox script found at $JUKEBOX_SCRIPT"
echo "Web server script found at $WEBSERVER_SCRIPT"

# Install required system dependencies
echo "Installing system dependencies with apt..."
apt-get update
apt-get install -y ffmpeg bpm-tools libsox-fmt-mp3

if [[ $? -ne 0 ]]; then
    echo "Error: Failed to install system dependencies."
    exit 1
fi

# Install required Python dependencies with pip
echo "Installing Python dependencies with pip..."
pip install --break-system-packages flask yt-dlp spotdl RPi.GPIO

if [[ $? -ne 0 ]]; then
    echo "Error: Failed to install Python dependencies."
    exit 1
fi

# Create a systemd service file for the Jukebox
JUKEBOX_SERVICE_FILE="/etc/systemd/system/jukebox.service"

echo "Creating systemd service file at $JUKEBOX_SERVICE_FILE..."
cat <<EOL > "$JUKEBOX_SERVICE_FILE"
[Unit]
Description=Jukebox Service
After=network.target

[Service]
Type=simple
EnvironmentFile=/etc/environment
ExecStart=/usr/bin/python3 $JUKEBOX_SCRIPT run -p \$JUKEBOX_SONGS_PATH
Restart=always
RestartSec=5
KillMode=control-group

[Install]
WantedBy=multi-user.target
EOL

# Reload systemd and enable the Jukebox service
echo "Enabling and starting the Jukebox service..."
systemctl daemon-reload
systemctl enable jukebox.service
systemctl start jukebox.service

# Create a systemd service file for the Jukebox Web Server
WEBSERVER_SERVICE_FILE="/etc/systemd/system/jukebox-webserver.service"

echo "Creating systemd service file at $WEBSERVER_SERVICE_FILE..."
cat <<EOL > "$WEBSERVER_SERVICE_FILE"
[Unit]
Description=Jukebox Web Server
After=network.target

[Service]
Type=simple
EnvironmentFile=/etc/environment
ExecStart=/usr/bin/python3 $WEBSERVER_SCRIPT
WorkingDirectory=$INSTALLER_PATH/webserver
Restart=always
RestartSec=5
KillMode=control-group

[Install]
WantedBy=multi-user.target
EOL

# Reload systemd and enable the Jukebox Web Server service
echo "Enabling and starting the Jukebox Web Server service..."
systemctl daemon-reload
systemctl enable jukebox-webserver.service
systemctl start jukebox-webserver.service

# Check the status of the services
if systemctl is-active --quiet jukebox.service && systemctl is-active --quiet jukebox-webserver.service; then
    echo "Jukebox and Web Server services installed and running successfully!"
else
    echo "Error: Failed to start one or both services."
    exit 1
fi
