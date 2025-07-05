import os
import cv2

import args
import global_constants as gc


class UsbCamera:
    def __init__(self, **kwargs):
        parameters = args.import_args(
            # yaml_path=gc.CONFIG_FOLDER_PATH + 'microphone_listener.yaml',
            yaml_path=gc.CONFIG_FOLDER_PATH + os.path.basename(os.path.abspath(__file__)),
            **kwargs,
        )
        self.video = cv2.VideoCapture(parameters['video_id'])
        self.video.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('M', 'J', 'P', 'G'))
        self.video.set(cv2.CAP_PROP_BRIGHTNESS, 30)
        self.video.set(cv2.CAP_PROP_CONTRAST, 50)
        self.video.set(cv2.CAP_PROP_EXPOSURE, 156)
        self.video.set(3, parameters['width'])
        self.video.set(4, parameters['height'])
        self.video.set(5, parameters['frame_rate'])
        self.verbose = parameters['verbose']

    def __del__(self):
        self.video.release()

    def get_raw_frame(self):
        success, image = self.video.read()
        if not success:
            if self.verbose >= 2:
                print('Camera "get_raw_frame" error!')
            return bytes({1})

        return image

    def get_jpeg_frame(self):
        success, image = self.video.read()
        if not success:
            if self.verbose >= 2:
                print('Camera "get_jpeg_frame" error!')
            return bytes({1})

        ret, jpeg = cv2.imencode('.jpg', image)
        return jpeg.tobytes()
