#! /bin/bash

# This script activates the virtual environment and runs the main_thread.py script.
# The output is also written to output/main_thread.log (the previous run's log is kept as main_thread.log.1).

REPO=/home/jetson/GIT/voice_robot_interaction
LOG=$REPO/output/main_thread.log

source $REPO/.venv/bin/activate
mkdir -p $REPO/output
[ -f $LOG ] && mv -f $LOG $LOG.1
python -u $REPO/main_thread.py 2>&1 | tee $LOG

wait
exit 0
