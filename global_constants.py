"""
Absolute folder paths used across the app, anchored to this file.

This module sits at the repository root, so resolving from __file__ gives the checkout it belongs to
whatever the working directory is. That matters twice over: a script launched from the IDE may start
with the working directory at the project root or at its own folder, and the same code has to be
importable on the robot and on a development machine.

On the Jetson this resolves to '/home/jetson/GIT/voice_robot_interaction/', which is exactly the value
that used to be hardcoded here, so nothing changes there.

Paths are kept as strings ending in '/' because the call sites build on them by concatenation
(gc.CONFIG_FOLDER_PATH + 'main_thread.yaml'). Forward slashes are used on every platform, which
open() and pathlib accept on Windows as well.
"""

from pathlib import Path

PROJECT_FOLDER_PATH = Path(__file__).resolve().parent.as_posix() + '/'
DATA_FOLDER_PATH = PROJECT_FOLDER_PATH + 'data/'
ASSETS_FOLDER_PATH = PROJECT_FOLDER_PATH + 'assets/'
OUTPUT_FOLDER_PATH = PROJECT_FOLDER_PATH + 'output/'
CONFIG_FOLDER_PATH = PROJECT_FOLDER_PATH + 'configs/'
