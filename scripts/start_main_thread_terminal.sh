#! /bin/bash

# This script activates the virtual environment and runs the main_thread.py script

gnome-terminal -- bash -c "source /home/jetson/GIT/voice_robot_interaction/.venv/bin/activate;python /home/jetson/GIT/voice_robot_interaction/main_thread.py;exec bash"

wait
exit 0