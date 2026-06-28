import time
import socket

import args
import utils
import global_constants as gc
from robot_link import protocol


class MicStreamClient:
    """
    Receives the microphone stream served by the RDK X3 (see audio_bridge_server.py on the RDK X3, the
    mic_stream_port server). The microphone physically lives on the RDK X3 now, so we read the already
    processed audio (AEC + beamforming + noise suppression) plus the hardware VAD flag over the wired link
    instead of opening a local device.

    Frame layout: [1 byte VAD flag][4-byte big-endian PCM length][mono int16 PCM bytes].

    read_frame() is self-healing: it connects lazily and reconnects automatically if the link drops, blocking
    until a frame is available, so callers get a simple "always works" audio source.
    """

    def __init__(self, **kwargs):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'mic_stream_client.yaml', **kwargs)
        self.host = parameters['host']
        self.port = parameters['port']
        self.retry_interval = parameters['retry_interval']
        self.verbose = parameters['verbose']
        self.socket = None

    def _connect(self) -> None:
        while self.socket is None:
            try:
                new_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                new_socket.connect((self.host, self.port))
                self.socket = new_socket
                if self.verbose >= 1:
                    print(f'Mic stream client connected to {self.host}:{self.port}')
            except socket.error as e:
                utils.print_exception(exception=e, message='Mic stream client connection error')
                if self.verbose >= 1:
                    print(f'\tRetrying in {self.retry_interval}s...')
                time.sleep(self.retry_interval)

    def read_frame(self):
        """
        Returns (is_voice: bool, pcm_bytes: bytes). Blocks until a frame is available, reconnecting if needed.
        """
        while True:
            if self.socket is None:
                self._connect()
            try:
                frame = protocol.recv_audio_frame(self.socket)
                if frame is None:
                    self.close()
                    continue
                return frame  # (is_voice: bool, pcm_bytes: bytes)
            except socket.error as e:
                utils.print_exception(exception=e, message='Mic stream client read error')
                self.close()
                time.sleep(self.retry_interval)

    def close(self) -> None:
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
            if self.verbose >= 1:
                print(f'Mic stream client connection to {self.host}:{self.port} closed.')
