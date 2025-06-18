import time
import copy

import tuning


class MicrophoneListener:
    def __init__(self, product_id, vendor_id, verbose: int, max_silence_duration: float = 2):
        self.verbose = verbose
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.microphone = None
        self.microphone = tuning.find(vid=vendor_id, pid=product_id)
        if self.microphone:
            if self.verbose >= 1:
                print('Microphone initialized successfully.')
        else:
            raise RuntimeError(f'Failed to initialize microphone with VID: {vendor_id}, PID: {product_id}')
        self.current_recording = None
        self.completed_recordings = []
        self.silence_duration = 0
        # duration in seconds after which a recording is stopped if no voice is detected
        self.max_silence_duration = max_silence_duration
        self.current_timestamp = None

    def listen(self):
        if self.current_timestamp is None:
            self.current_timestamp = time.time()
        if not self.microphone.is_voice():
            if self.current_recording is None:
                time.sleep(0.1)  # Sleep to avoid busy waiting
            else:
                new_timestamp = time.time()
                self.silence_duration += (new_timestamp - self.current_timestamp)
                self.current_timestamp = new_timestamp
                if self.silence_duration >= self.max_silence_duration:
                    if self.verbose >= 2:
                        print('Stopping recording due to silence.')
                    self.completed_recordings.append(copy.deepcopy(self.current_recording))
                    self.current_recording = None
                    self.silence_duration = 0
        else:
            if self.current_recording is None:
                if self.verbose >= 2:
                    print('Starting new recording.')
                self.current_recording = []
                self.silence_duration = 0
            self.current_recording.append(self.microphone.read())
            self.current_timestamp = time.time()

