import time
import socket

import args
import utils
import global_constants as gc


class SpeakerClient:
    """
    Sends TTS audio to the RDK X3 to be played through the ReSpeaker speakers (see audio_bridge_server.py on
    the RDK X3, the speaker_playback_port server). The speakers physically live on the RDK X3 now, so instead
    of playing locally we stream the PCM over the wired link.

    Message layout: [4-byte big-endian PCM length][PCM bytes]. The PCM format must match the RDK X3 playback
    config (audio_bridge_server.yaml: speaker_sample_rate / speaker_format), i.e. 24 kHz mono int16.

    Self-healing but non-blocking for the caller: send_audio() connects lazily and reconnects if the link
    dropped, and simply drops the chunk (with a log line) if the RDK X3 is unreachable, so the main loop is
    never stuck waiting on playback.
    """

    def __init__(self, **kwargs):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'speaker_client.yaml', **kwargs)
        self.host = parameters['host']
        self.port = parameters['port']
        self.retry_interval = parameters['retry_interval']
        self.verbose = parameters['verbose']
        self.socket = None
        self._last_failed_connect = 0.0

    def _connect(self) -> bool:
        # Avoid hammering the network with a blocking connect on every chunk while the RDK X3 is down.
        if time.time() - self._last_failed_connect < self.retry_interval:
            return False
        try:
            new_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            new_socket.settimeout(self.retry_interval)
            new_socket.connect((self.host, self.port))
            new_socket.settimeout(None)
            self.socket = new_socket
            if self.verbose >= 1:
                print(f'Speaker client connected to {self.host}:{self.port}')
            return True
        except socket.error as e:
            self._last_failed_connect = time.time()
            utils.print_exception(exception=e, message='Speaker client connection error')
            return False

    def send_audio(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        if self.socket is None:
            if not self._connect():
                if self.verbose >= 2:
                    print('Speaker client not connected, dropping audio chunk.')
                return
        try:
            length_prefix = len(pcm_bytes).to_bytes(length=4, byteorder='big')
            self.socket.sendall(length_prefix + pcm_bytes)
            if self.verbose >= 3:
                print(f'Speaker client sent {len(pcm_bytes)} bytes')
        except socket.error as e:
            utils.print_exception(exception=e, message='Speaker client send error')
            self.close()

    def close(self) -> None:
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
            if self.verbose >= 1:
                print(f'Speaker client connection to {self.host}:{self.port} closed.')
