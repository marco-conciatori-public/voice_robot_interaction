import io
import wave
import time
import threading

import pyaudio

import args
import utils
import global_constants as gc
from sensors.microphone import tuning


class MicrophoneListener:
    def __init__(self, shared_variable_manager, hardware_interaction, **kwargs):
        """
        Initializes the MicrophoneListener with the specified product and vendor IDs.
        :param shared_variable_manager: instance of SharedVariableManager to manage shared variables.
        :param product_id: value needed to identify the microphone device.
        :param vendor_id: value needed to identify the microphone device.
        :param max_silence_duration: maximum duration in seconds after which a recording is stopped if no voice is
         detected.
        :param min_sentence_duration: minimum duration in seconds for a valid recording.
        :param verbose: verbosity level for logging.
        """
        self.shared_variable_manager = shared_variable_manager
        self.hardware_interaction = hardware_interaction
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'microphone_listener.yaml', **kwargs)
        self.device_index = parameters['device_index']
        self.vendor_id = parameters['vendor_id']
        self.product_id = parameters['product_id']
        self.verbose = parameters['verbose']
        self.microphone = None
        self.microphone = tuning.find(vid=self.vendor_id, pid=self.product_id)
        if self.microphone:
            if self.verbose >= 1:
                print('Microphone opened.')
        else:
            raise RuntimeError(f'Failed to initialize microphone with VID: {self.vendor_id}, PID: {self.product_id}')
        self.current_recording = None
        self.silence_timestamp = None
        self.start_recording_timestamp = None
        # duration in seconds after which a recording is stopped if no voice is detected
        self.max_silence_duration = parameters['max_silence_duration']
        self.min_sentence_duration = parameters['min_sentence_duration']
        self.pa = pyaudio.PyAudio()
        self.audio_stream = None
        self.stream_params = parameters['stream_params']
        self.save_file = parameters['save_file']
        self.led_intensity = parameters['led_intensity']

    def listen(self):
        """
        Listening to the microphone
        If a voice is detected using self.microphone.is_voice():
            - start/keep recording using the pyaudio library
        If no voice is detected for self.max_silence_duration seconds:
            - stop recording
            - save the audio data
            - resume listening
        """

        self.audio_stream = self.pa.open(
            format=self.pa.get_format_from_width(self.stream_params['width']),
            channels=self.stream_params['channels'],
            rate=self.stream_params['sample_rate'],
            frames_per_buffer=self.stream_params['chunk_size'],
            input_device_index=self.device_index,
            input=True,
            start=False,
        )
        if self.verbose >= 2:
            print('Starting to listen to the microphone...')

        while True:
            if self.microphone.is_voice():
                self.silence_timestamp = None
                if self.audio_stream.is_stopped():
                    self.start_recording()
                else:
                    # Set RGB LED to green
                    self.hardware_interaction.rgb_led(red=0, green=self.led_intensity, blue=0)
                    self.current_recording.append(self.audio_stream.read(
                        num_frames=self.stream_params['chunk_size'],
                        exception_on_overflow=False
                    ))
            else:  # no voice detected
                if self.audio_stream.is_active():
                    # Set RGB LED to orange
                    self.hardware_interaction.rgb_led(red=self.led_intensity, green=self.led_intensity, blue=0)
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
        # Set RGB LED to green
        self.hardware_interaction.rgb_led(red=0, green=self.led_intensity, blue=0)
        self.current_recording = []
        self.start_recording_timestamp = time.time()
        self.audio_stream.start_stream()
        if self.verbose >= 3:
            print('Voice detected, starting recording...')

    def stop_recording(self, save_file: bool = False):
        """
        Stops the current recording and saves the audio data.
        """
        # Set RGB LED to red
        self.hardware_interaction.rgb_led(red=self.led_intensity, green=0, blue=0)
        self.audio_stream.stop_stream()
        if self.verbose >= 3:
            print('No voice detected for a while, stop recording...')

        if (time.time() - self.start_recording_timestamp) >= self.min_sentence_duration + self.max_silence_duration:
            if save_file:
                utils.save_wave_file(
                    file_path=f'{gc.OUTPUT_FOLDER_PATH}recording_{int(time.time())}.wav',
                    byte_data=b''.join(self.current_recording),
                    channels=self.stream_params['channels'],
                    rate=self.stream_params['sample_rate'],
                    sample_width=self.stream_params['width'],
                    verbose=self.verbose,
                )

            # format the audio data into a WAV file in memory
            output_buffer = io.BytesIO()
            with wave.open(f=output_buffer, mode='wb') as wf:
                wf.setnchannels(self.stream_params['channels'])
                wf.setsampwidth(self.stream_params['width'])  # 2 bytes for 16-bit audio
                wf.setframerate(self.stream_params['sample_rate'])
                wf.writeframes(b''.join(self.current_recording))
            # Get the bytes from the buffer
            wav_bytes_in_memory = output_buffer.getvalue()
            self.shared_variable_manager.add_to(
                queue_name='reasoning_requests',
                value={'audio_bytes': wav_bytes_in_memory},
            )
            if self.verbose >= 3:
                print('Recording accepted.')
        else:
            if self.verbose >= 3:
                print('Recording too short, not accepted.')

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
