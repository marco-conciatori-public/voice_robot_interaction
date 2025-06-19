import time
from pathlib import Path

import pyaudio

import args
import utils
from microphone import tuning
import global_constants as gc


class MicrophoneListener:
    RATE = 16000
    CHUNK_SIZE = 1024
    CHANNELS = 1
    WIDTH = 2

    def __init__(self, **kwargs):
        """
        Initializes the MicrophoneListener with the specified product and vendor IDs.
        :param product_id: value needed to identify the microphone device.
        :param vendor_id: value needed to identify the microphone device.
        :param max_silence_duration: maximum duration in seconds after which a recording is
         stopped if no voice is detected.
        :param verbose: verbosity level for logging.
        """
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'microphone_listener.yaml', **kwargs)
        self.verbose = parameters['verbose']
        self.index = parameters['index']
        self.vendor_id = parameters['vendor_id']
        self.product_id = parameters['product_id']
        self.microphone = None
        self.microphone = tuning.find(vid=self.vendor_id, pid=self.product_id)
        if self.microphone:
            if self.verbose >= 1:
                print('Microphone initialized successfully.')
        else:
            raise RuntimeError(f'Failed to initialize microphone with VID: {self.vendor_id}, PID: {self.product_id}')
        self.current_recording = None
        self.completed_recordings = []
        self.silence_timestamp = None
        # duration in seconds after which a recording is stopped if no voice is detected
        self.max_silence_duration = parameters['max_silence_duration']
        self.current_timestamp = None
        self.pa = pyaudio.PyAudio()
        self.is_recording = False
        self.audio_stream = None

    def listen(self):
        """
        Listening to the microphone
        If a voice is detected using self.microphone.is_voice():
            - start recording using the pyaudio library
        If no voice is detected for self.max_silence_duration seconds:
            - stop recording
            - save the audio data
            - resume listening
        """
        if self.verbose >= 1:
            print('Starting to listen to the microphone...')

        while True:
            if self.microphone.is_voice():
                self.silence_timestamp = None
                if not self.is_recording:
                    self.start_recording()
                else:
                    self.current_recording.append(self.audio_stream.read(MicrophoneListener.CHUNK_SIZE))
            else:
                if self.is_recording:
                    if self.silence_timestamp is None:
                        self.silence_timestamp = time.time()
                    if (time.time() - self.silence_timestamp) >= self.max_silence_duration:
                        self.stop_recording()
                else:
                    time.sleep(0.05)

    def start_recording(self):
        """
        Starts recording audio from the microphone.
        """
        self.is_recording = True

        self.current_recording = []
        self.audio_stream = self.pa.open(
            format=self.pa.get_format_from_width(MicrophoneListener.WIDTH),
            channels=MicrophoneListener.CHANNELS,
            rate=MicrophoneListener.RATE,
            input=True,
            input_device_index=self.index,
            frames_per_buffer=MicrophoneListener.CHUNK_SIZE,
        )
        if self.verbose >= 2:
            print('Voice detected, starting recording...')

    def stop_recording(self):
        """
        Stops the current recording and saves the audio data.
        """
        self.audio_stream.stop_stream()
        self.audio_stream.close()
        self.audio_stream = None

        audio_data = b''.join(self.current_recording)
        Path(gc.OUTPUT_FOLDER_PATH).parent.mkdir(parents=True, exist_ok=True)
        utils.save_wave_file(
            file_path=f'{gc.OUTPUT_FOLDER_PATH}recording_{int(time.time())}.wav',
            byte_data=audio_data,
            channels=MicrophoneListener.CHANNELS,
            rate=MicrophoneListener.RATE,
            sample_width=MicrophoneListener.WIDTH,
        )
        self.completed_recordings.append(audio_data)

        self.current_recording = []
        self.is_recording = False

        if self.verbose >= 2:
            print('No voice detected for a while, stopping recording...')


if __name__ == '__main__':

    mic_listener = MicrophoneListener(verbose=3)
    mic_listener.listen()
