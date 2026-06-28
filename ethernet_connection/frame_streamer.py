import time
import socket

import args
import utils
import global_constants as gc
from robot_link import protocol


# Formats (as stored in 'latest_camera_image'["format"]) that we can forward to the RDK X3 as-is.
_JPEG_FORMATS = ('.jpg', '.jpeg', 'jpg', 'jpeg')


class FrameStreamerClient:
    """
    Streams the arm camera (the USB camera attached to the Jetson, mounted at the end of the robot arm) to
    the RDK X3 over the wired link, so the RDK X3 can republish it as a ROS2 topic for the VR/mobile apps
    (Option B).

    It does NOT open the camera itself: it reuses the JPEG frames already captured by UsbCamera and stored
    in the shared variable manager ('latest_camera_image'), so the single /dev/video device is never opened
    twice.

    Protocol (pull): the RDK X3 is the TCP server. It sends a 1-byte request for each frame it wants, but
    only while an app is subscribed to the topic. This client replies with a 4-byte big-endian length prefix
    followed by the JPEG bytes (a length of 0 means "no frame available yet"). So nothing is sent unless the
    RDK X3 asks, and when no app is watching this thread simply blocks idle on recv().

    This is a separate socket/port from the JSON command channel (EthernetClient), so the two never mix.
    """

    def __init__(self, shared_variable_manager, **kwargs):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'frame_streamer.yaml', **kwargs)
        self.shared_variable_manager = shared_variable_manager
        self.host = parameters['host']
        self.port = parameters['port']
        self.retry_interval = parameters['retry_interval']
        self.verbose = parameters['verbose']
        self.socket = None

    def connect(self) -> None:
        connection_established = False
        if self.verbose >= 2:
            print('Starting frame streamer client...')
        while not connection_established:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.connect((self.host, self.port))
                if self.verbose >= 1:
                    print(f'\tFrame streamer connected to {self.host}:{self.port}')
                connection_established = True
            except socket.error as e:
                utils.print_exception(exception=e, message='Error connecting frame streamer')
                if self.verbose >= 1:
                    print(f'\tConnection failed. Retrying in {self.retry_interval} seconds...')
                connection_established = False
                time.sleep(self.retry_interval)

    def _get_latest_jpeg(self) -> bytes:
        frame_dict = self.shared_variable_manager.get_variable(variable_name='latest_camera_image')
        if frame_dict is None:
            return b''
        image_format = frame_dict.get('format')
        if image_format not in _JPEG_FORMATS:
            if self.verbose >= 1:
                print(f'Frame streamer: camera format "{image_format}" is not JPEG, skipping frame. '
                      f'Set image_format to ".jpg" in usb_camera.yaml.')
            return b''
        return frame_dict.get('image', b'')

    def _serve(self) -> None:
        """Respond to frame requests until the connection drops."""
        while self.socket:
            try:
                request = self.socket.recv(1)
                if not request:
                    # the RDK X3 closed the connection
                    self.close()
                    return
                jpeg_bytes = self._get_latest_jpeg()
                protocol.send_message(self.socket, jpeg_bytes)
                if self.verbose >= 3:
                    print(f'Frame streamer sent {len(jpeg_bytes)} bytes')
            except Exception as e:
                utils.print_exception(exception=e, message='Error in frame streamer "_serve"')
                self.close()
                return

    def close(self) -> None:
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            if self.verbose >= 1:
                print(f'Frame streamer connection to {self.host}:{self.port} closed.')
            self.socket = None

    def run_forever(self) -> None:
        """Connect, serve frames until the link drops, then reconnect. Self-healing."""
        while True:
            self.connect()
            self.shared_variable_manager.add_to(queue_name='running_components', value='frame_streamer')
            try:
                self._serve()
            finally:
                self.shared_variable_manager.remove_from(queue_name='running_components', value='frame_streamer')
                self.close()
            time.sleep(self.retry_interval)
