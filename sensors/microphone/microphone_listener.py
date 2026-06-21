import io
import wave
import time
import threading

import args
import utils
import global_constants as gc
from ethernet_connection.mic_stream_client import MicStreamClient


class MicrophoneListener:
    def __init__(self, shared_variable_manager, hardware_interaction, **kwargs):
        """
        Listens to the microphone, which now physically lives on the RDK X3 main board. Instead of opening a
        local audio device, it receives the already processed audio (AEC + beamforming + noise suppression)
        plus the hardware VAD flag from the RDK X3 over the wired link (see MicStreamClient and, on the RDK X3,
        audio_bridge_server.py). The recording state machine (start on voice, stop after a silence gap, discard
        too-short clips) is unchanged; only the audio source changed.

        :param shared_variable_manager: instance of SharedVariableManager to manage shared variables.
        :param hardware_interaction: used to drive the status RGB LED.
        """
        self.shared_variable_manager = shared_variable_manager
        self.hardware_interaction = hardware_interaction
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'microphone_listener.yaml', **kwargs)
        self.verbose = parameters['verbose']

        # Audio source: the microphone stream served by the RDK X3 over the wired link.
        self.mic_client = MicStreamClient(verbose=self.verbose)

        self.current_recording = None
        self.recording = False
        self.silence_timestamp = None
        self.start_recording_timestamp = None
        # duration in seconds after which a recording is stopped if no voice is detected
        self.max_silence_duration = parameters['max_silence_duration']
        self.min_sentence_duration = parameters['min_sentence_duration']
        # describes the received PCM (must match the RDK X3 mic stream), used to package the in-memory WAV
        self.stream_params = parameters['stream_params']
        self.save_file = parameters['save_file']
        self.led_intensity = parameters['led_intensity']

    def listen(self):
        """
        Reads frames (audio chunk + VAD flag) from the RDK X3 microphone stream.
        While voice is detected:
            - start/keep recording, accumulating the received audio.
        When no voice is detected for self.max_silence_duration seconds:
            - stop recording, package the audio, and hand it to the reasoning service.
        """
        if self.verbose >= 2:
            print('Starting to listen to the microphone stream from the RDK X3...')

        while True:
            is_voice, pcm_bytes = self.mic_client.read_frame()
            if is_voice:
                self.silence_timestamp = None
                if not self.recording:
                    self.start_recording()
                # Set RGB LED to green
                self.hardware_interaction.rgb_led(red=0, green=self.led_intensity, blue=0)
                if pcm_bytes:
                    self.current_recording.append(pcm_bytes)
            else:  # no voice detected
                if self.recording:
                    # Set RGB LED to orange
                    self.hardware_interaction.rgb_led(red=self.led_intensity, green=self.led_intensity, blue=0)
                    if self.silence_timestamp is None:
                        self.silence_timestamp = time.time()
                    if (time.time() - self.silence_timestamp) >= self.max_silence_duration:
                        self.stop_recording(save_file=self.save_file)

    def start_recording(self):
        """
        Starts a new recording.
        """
        # Set RGB LED to green
        self.hardware_interaction.rgb_led(red=0, green=self.led_intensity, blue=0)
        self.current_recording = []
        self.recording = True
        self.start_recording_timestamp = time.time()
        if self.verbose >= 3:
            print('Voice detected, starting recording...')

    def stop_recording(self, save_file: bool = False):
        """
        Stops the current recording and, if it is long enough, hands the audio to the reasoning service.
        """
        # Set RGB LED to red
        self.hardware_interaction.rgb_led(red=self.led_intensity, green=0, blue=0)
        self.recording = False
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
        try:
            listener_thread = threading.Thread(target=self.listen, name='microphone_listener')
            listener_thread.start()
            self.shared_variable_manager.add_to(queue_name='running_components', value='microphone_listener')
            if self.verbose >= 1:
                print('Microphone listener started.')
        except Exception as e:
            self.shared_variable_manager.remove_from(queue_name='running_components', value='microphone_listener')
            utils.print_exception(exception=e, message='Error starting microphone listener thread')
            raise

    def __del__(self):
        """
        Closes the microphone stream and releases resources.
        """
        self.shared_variable_manager.remove_from(queue_name='running_components', value='microphone_listener')
        if self.mic_client is not None:
            self.mic_client.close()
        if self.verbose >= 1:
            print('Microphone listener closed.')
