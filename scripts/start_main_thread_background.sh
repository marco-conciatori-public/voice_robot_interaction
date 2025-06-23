#! /bin/bash

# This script activates the virtual environment and runs the main_thread.py script

source home/jetson/GIT/voice_robot_interaction/.venv/bin/activate
python home/jetson/GIT/voice_robot_interaction/main_thread.py

wait
exit 0