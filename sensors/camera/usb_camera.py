import cv2
import time

import args
import utils


class UsbCamera:
    def __init__(self, shared_variable_manager=None, **kwargs):
        parameters = args.import_args(
            # yaml_path=gc.CONFIG_FOLDER_PATH + 'usb_camera.yaml',
            caller_name=__file__,
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
        self.shared_variable_manager = shared_variable_manager

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
        if self.verbose >= 1:
            if self.video.isOpened():
                print('Opened camera successfully')
            else:
                print('Error: could not open camera')

    def __del__(self):
        try:
            self.video.release()
        except:
            pass
        if self.shared_variable_manager is not None:
            self.shared_variable_manager.remove_from(queue_name='running_components', value='usb_camera')

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
        assert self.shared_variable_manager is not None, ('shared_variable_manager must be provided to use '
                                                          '"ready_latest_image".')
        try:
            self.open_camera()
            streak_error_count = 0
            self.shared_variable_manager.add_to(queue_name='running_components', value='usb_camera')
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

                        # The .tobytes() method converts the numpy array to a bytes object
                        image_bytes = image.tobytes()
                        image_dict = {
                            'image': image_bytes,
                            'timestamp': time.time(),
                            'format': self.image_format,
                        }
                        self.shared_variable_manager.set_variable(variable_name='latest_camera_image', value=image_dict)
                except Exception as e:
                    streak_error_count += 1
                    if self.verbose >= 2:
                        utils.print_exception(exception=e, message='Error in USB camera')
                time.sleep(self.sleep_time)

            self.shared_variable_manager.remove_from(queue_name='running_components', value='usb_camera')
            print('Too many errors in reading usb camera frames, closing camera')
        except Exception as e:
            self.shared_variable_manager.remove_from(queue_name='running_components', value='usb_camera')
            utils.print_exception(exception=e, message='Error in USB camera')
