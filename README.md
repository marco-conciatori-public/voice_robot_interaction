Voice interaction for my robot (RDK X3 Robot, http://www.yahboom.net/study/RDK-X3-Robot)
- hear user voice through a microphone
- send voice to a Google Cloud reasoning API (it can directly take in sounds)
- get a (textual) response from the reasoning API
- if the response is a function call (i.e. move_arm(x_axis: 1, y_axis: 0, z_axis: 0)), execute it
- if the response is a textual response, send it to a text-to-speech API
- play the response using the robot's speakers

It is part of a bigger project, where I changed most of the software and hardware of the robot: https://github.com/marco-conciatori-public/yahboom_rdk_x3_robot/

Everything is explained in detail in the project website: https://marco-conciatori-public.github.io/

There you will also find all the robot capabilities with videos and explanations.
Finally, there is a step-by-step guide on how to recreate the robot from scratch.
