import os
import cv2
import time

import args
import utils
import global_constants as gc


class UsbCamera:
    def __init__(self, **kwargs):
        print(f'this path: {os.path.abspath(__file__)}')
        print(f'this file: {os.path.basename(os.path.abspath(__file__))}')
        print(f'full path: {gc.CONFIG_FOLDER_PATH + os.path.basename(os.path.abspath(__file__))}')
        parameters = args.import_args(
            # yaml_path=gc.CONFIG_FOLDER_PATH + 'microphone_listener.yaml',
            yaml_path=gc.CONFIG_FOLDER_PATH + os.path.basename(os.path.abspath(__file__)),
            **kwargs,
        )
        self.video = None
        self.video_id = parameters['video_id']
        self.width = parameters['width']
        self.height = parameters['height']
        self.frame_rate = parameters['frame_rate']
        self.verbose = parameters['verbose']
        self.max_reading_errors = parameters['max_reading_errors']
        self.image_format = parameters['image_format']

        self.latest_image = None

        # this should be "1 / self.frame_rate", but it is better if the sampling frequency is higher than the signal
        self.sleep_time = 0.5 / self.frame_rate

    def open_camera(self) -> None:
        self.video = cv2.VideoCapture(self.video_id)
        self.video.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('M', 'J', 'P', 'G'))
        self.video.set(cv2.CAP_PROP_BRIGHTNESS, 30)
        self.video.set(cv2.CAP_PROP_CONTRAST, 50)
        self.video.set(cv2.CAP_PROP_EXPOSURE, 156)
        self.video.set(3, self.width)
        self.video.set(4, self.height)
        self.video.set(5, self.frame_rate)

    def __del__(self):
        self.video.release()

    def get_raw_frame(self) -> bytes:
        success, image = self.video.read()
        if not success:
            if self.verbose >= 2:
                print('Camera "get_raw_frame" error!')
            return bytes({1})

        return image

    def get_jpeg_frame(self) -> bytes:
        success, image = self.video.read()
        if not success:
            if self.verbose >= 2:
                print('Camera "get_jpeg_frame" error!')
            return bytes({1})

        ret, jpeg = cv2.imencode('.jpg', image)
        return jpeg.tobytes()

    def ready_latest_image(self) -> None:
        self.open_camera()
        streak_error_count = 0
        while streak_error_count < self.max_reading_errors:
            try:

                success, image = self.video.read()
                if not success:
                    streak_error_count += 1
                    if self.verbose >= 2:
                        print('Error: could not read current frame.')
                else:
                    streak_error_count = 0
                    if self.image_format is not None:
                        ret, image = cv2.imencode(self.image_format, image)
                    self.latest_image = image
            except Exception as e:
                streak_error_count += 1
                if self.verbose >= 2:
                    utils.print_exception(exception=e, message='Error in USB camera')
            time.sleep(self.sleep_time)
