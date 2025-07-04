# This python script retrieves and prints the names of all input audio devices available on the system using
# the PyAudio library.
# It is used to discover the microphone device index for the microphone listener in the main thread.

import pyaudio

p = pyaudio.PyAudio()
info = p.get_host_api_info_by_index(0)
num_devices = info.get('deviceCount')

for i in range(0, num_devices):
    if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
        print("Input Device id ", i, " - ", p.get_device_info_by_host_api_device_index(0, i).get('name'))
