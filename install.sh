#!/bin/bash

# Color codes
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

# Function to echo colored text
function color_echo {
    local message="$1"
    echo -e "${BLUE}${message}${NC}"
}

color_echo "Initiating installation of moonraker-mattaos..."

# Debug:
echo -e "User is: $USER"

# Install required packages
color_echo "Installing required packages..."
sudo apt-get update
# # This is only necessary for virtual-klipper-printer 
# sudo apt-get install -y python3-virtualenv systemctl nano
color_echo "Required packages installed successfully"

# Set up virtual environment
color_echo "Setting up virtual environment..."
virtualenv ~/moonraker-mattaos-env
source ~/moonraker-mattaos-env/bin/activate
pip install -e .
color_echo "Virtual environment set up successfully"

# Create and start the service file
SERVICE_FILE="/etc/systemd/system/moonraker-mattaos.service"
SERVICE_CONTENT="[Unit]
Description=Moonraker mattaos
After=network-online.target moonraker.service

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=/home/${USER}/moonraker-mattaos 
ExecStart=/home/${USER}/moonraker-mattaos-env/bin/python3 /home/${USER}/moonraker-mattaos/moonraker_mattaos/main.py 
Restart=always
RestartSec=5"

color_echo "Creating and starting the service file..."
echo "$SERVICE_CONTENT" | sudo tee "$SERVICE_FILE" > /dev/null
sudo systemctl enable moonraker-mattaos
sudo systemctl daemon-reload
sudo systemctl start moonraker-mattaos
color_echo "Service file created and started successfully"

# Create the config.cfg file
CONFIG_FILE="/home/${USER}/printer_data/config/moonraker-mattaos.cfg"
CONFIG_CONTENT="[moonraker_control]
enabled = true
printer_ip = localhost
printer_port = 7125
[mattaos_settings]
webrtc_stream_url = http://localhost/webcam/webrtc
camera_snapshot_url = http://localhost/webcam/snapshot
auth_token = <paste your auth token here>
nozzle_tip_coords_x = 10
nozzle_tip_coords_y = 10
flip_webcam_horizontally = false
flip_webcam_vertically = false
rotate_webcam_90CC = false
cherry_pick_cmds = []"



color_echo "Creating the moonraker-mattaos.cfg file..."
echo "$CONFIG_CONTENT" > "$CONFIG_FILE"
color_echo "Config file created successfully"

# Create the crowsnest.conf file
CROWSNEST_FILE="/home/${USER}/printer_data/config/crowsnest.conf"
CROWSNEST_CONTENT="[crowsnest]
log_path: /home/${USER}/printer_data/logs/crowsnest.log
log_level: verbose                      # Valid Options are quiet/verbose/debug
delete_log: false                       # Deletes log on every restart, if set to true
no_proxy: false

[cam 1]
mode: camera-streamer                         # ustreamer - Provides mjpg and snapshots. (All devices)
                                        # camera-streamer - Provides webrtc, mjpg and snapshots. (rpi + Raspi OS based only)
enable_rtsp: false                      # If camera-streamer is used, this enables also usage of an rtsp server
rtsp_port: 8554                         # Set different ports for each device!
port: 8080                              # HTTP/MJPG Stream/Snapshot Port
device: /dev/video0                     # See Log for available ...
resolution: 1920x1080 #640x480 #2592x1944                   # widthxheight format (Originally 640x480)
max_fps: 15 #30                             # If Hardware Supports this it will be forced, otherwise ignored/coerced. (originally 15)
#custom_flags:                          # You can run the Stream Services with custom flags.
#v4l2ctl:                               # Add v4l2-ctl parameters to setup your camera, see Log what your cam is capable of.
# focus_automatic_continuous: false   # Turn off focus_automatic_continuous
# focus_absolute: 500                 # Set focus_absolute to 550
v4l2ctl: 
focus_automatic_continuous: 0
focus_absolute: 500
"

color_echo "Creating the crowsnest.conf file..."
echo "$CROWSNEST_CONTENT" > "$CROWSNEST_FILE"
color_echo "Config file created successfully"

color_echo "Installation completed!"
