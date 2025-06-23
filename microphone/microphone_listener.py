import time
import threading

import pyaudio

import args
import utils
from microphone import tuning
import global_constants as gc


class MicrophoneListener:
    def __init__(self, shared_variable_manager, **kwargs):
        """
        Initializes the MicrophoneListener with the specified product and vendor IDs.
        :param product_id: value needed to identify the microphone device.
        :param vendor_id: value needed to identify the microphone device.
        :param max_silence_duration: maximum duration in seconds after which a recording is stopped if no voice is
         detected.
        :param verbose: verbosity level for logging.
        """
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'microphone_listener.yaml', **kwargs)
        self.verbose = parameters['verbose']
        self.shared_variable_manager = shared_variable_manager
        self.device_index = parameters['device_index']
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
        self.silence_timestamp = None
        # duration in seconds after which a recording is stopped if no voice is detected
        self.max_silence_duration = parameters['max_silence_duration']
        self.pa = pyaudio.PyAudio()
        self.audio_stream = None
        self.stream_params = parameters['stream_params']
        self.save_file = parameters['save_file']

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

        self.audio_stream = self.pa.open(
            format=self.pa.get_format_from_width(self.stream_params['width']),
            channels=self.stream_params['channels'],
            rate=self.stream_params['sample_rate'],
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.stream_params['chunk_size'],
            start=False,
        )

        while True:
            if self.microphone.is_voice():
                self.silence_timestamp = None
                if self.audio_stream.is_stopped():
                    self.start_recording()
                else:
                    self.current_recording.append(self.audio_stream.read(
                        num_frames=self.stream_params['chunk_size'],
                        exception_on_overflow=False
                    ))
            else:
                if self.audio_stream.is_active():
                    if self.silence_timestamp is None:
                        self.silence_timestamp = time.time()
                    if (time.time() - self.silence_timestamp) >= self.max_silence_duration:
                        self.stop_recording(save_file=self.save_file)
                else:
                    time.sleep(0.05)

    def start_recording(self):
        """
        Starts recording audio from the microphone.
        """
        self.current_recording = []
        self.audio_stream.start_stream()
        if self.verbose >= 2:
            print('Voice detected, starting recording...')

    def stop_recording(self, save_file: bool = False):
        """
        Stops the current recording and saves the audio data.
        """
        self.audio_stream.stop_stream()

        if save_file:
            utils.save_wave_file(
                file_path=f'{gc.OUTPUT_FOLDER_PATH}recording_{int(time.time())}.wav',
                byte_data=b''.join(self.current_recording),
                channels=self.stream_params['channels'],
                rate=self.stream_params['sample_rate'],
                sample_width=self.stream_params['width'],
            )
        self.shared_variable_manager.add_reasoning_request({'audio_bytes': b''.join(self.current_recording)})
        self.current_recording = []

        if self.verbose >= 2:
            print('No voice detected for a while, stopping recording...')

    # this method invokes the listen method in a separate thread
    def start_listening(self):
        """
        Starts the microphone listener in a separate thread.
        """
        listener_thread = threading.Thread(target=self.listen, name='microphone_listener')
        listener_thread.start()
        if self.verbose >= 1:
            print('Microphone listener started.')

    def __del__(self):
        """
        Closes the microphone interface and releases resources.
        """
        if self.audio_stream is not None:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        self.pa.terminate()
        if self.microphone:
            self.microphone.close()
        if self.verbose >= 1:
            print('Microphone listener closed.')
