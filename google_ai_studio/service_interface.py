import time
import warnings
import threading

from google import genai
from google.genai import types

import args
import utils
import global_constants as gc
from google_ai_studio import tts_service
from google_ai_studio import function_declarations
from google_ai_studio.reasoning_service import ReasoningService


class GoogleAIStudioService:
    """
    This class serves as an interface to the Google AI Studio services, including reasoning and text-to-speech (TTS).
    It manages the communication with the Google AI Studio API and handles requests and responses.
    """

    def __init__(self, shared_variable_manager, **kwargs):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'service_interface.yaml', **kwargs)
        self.shared_variable_manager = shared_variable_manager
        self.client = genai.Client(api_key=utils.get_api_key(file_path=parameters['api_key_file_path']))
        self.tools = types.Tool(function_declarations=function_declarations.function_list)
        self.reasoning_parameters = parameters['reasoning_parameters']
        self.use_tts_service = parameters['use_tts_service']
        self.tts_parameters = parameters['tts_parameters']
        self.image_spoilage_time = parameters['image_spoilage_time']
        self.verbose = parameters['verbose']

        self.reasoning_service = ReasoningService(client=self.client, tools=self.tools, **self.reasoning_parameters)

    def run_reasoning_service(self) -> None:
        """
        Continuously processes reasoning requests from the shared variable manager.
        It sends audio prompts to the Google AI Studio LLM and handles the responses.
        """
        while True:
            request = self.shared_variable_manager.pop_from(queue_name='reasoning_requests')
            if request is not None:
                textual_response, function_call_response = self.reasoning_service.reasoning(**request)
                if function_call_response is not None:
                    if function_call_response.name == "get_camera_image":
                        current_camera_image = self.get_camera_image()
                        if current_camera_image is not None:
                            # send a new reasoning request with the latest image (hoping that the model will remember
                            # the latest user request)
                            self.shared_variable_manager.add_to(
                                queue_name='reasoning_requests',
                                value={'image_bytes': current_camera_image},
                            )
                    else:
                        self.shared_variable_manager.add_to(
                            queue_name='functions_to_call',
                            value=function_call_response,
                        )
                if textual_response is not None:
                    if self.use_tts_service:
                        self.shared_variable_manager.add_to(queue_name='tts_requests', value=textual_response)
                    elif self.verbose >= 1:
                        print(textual_response)
            else:
                time.sleep(0.2)
            time.sleep(0.02)

    def run_tts_service(self) -> None:
        """
        Continuously processes TTS requests from the shared variable manager.
        It converts text prompts to audio using the Google AI Studio TTS service and handles the responses.
        """
        while True:
            request = self.shared_variable_manager.pop_from(queue_name='tts_requests')
            if request is not None:
                try:
                    audio_response = tts_service.text_to_speech(
                        text_input=request,
                        client=self.client,
                        **self.tts_parameters,
                        verbose=self.verbose,
                    )
                except Exception as e:
                    print('DEBUG: in TTS general exception')
                    utils.print_exception(exception=e, message='Error in TTS service')
                    audio_response = None
                    # check if the problem is due to reaching the request limit
                    if hasattr(e, 'code') and e.code == 429:
                        print("TTS rate limit reached, responses will be printed in the console from now on.")
                        self.use_tts_service = False
                        # use also the speaker to deliver error message
                        try:
                            error_audio_file_path = gc.ASSETS_FOLDER_PATH + 'TTS_request_limit.wav'
                            with open(error_audio_file_path, 'rb') as error_audio_file:
                                error_audio_message = error_audio_file.read()
                                self.shared_variable_manager.add_to(
                                    queue_name='audio_to_play',
                                    value=error_audio_message,
                                )
                        except Exception as e:
                            utils.print_exception(exception=e, message='Error opening/reading error audio file')

                    if self.verbose >= 1:
                        print(request)
                if audio_response is not None:
                    self.shared_variable_manager.add_to(queue_name='audio_to_play', value=audio_response)
            else:
                time.sleep(0.2)
            time.sleep(0.02)

    def start_services(self) -> None:
        """
        Starts the reasoning and TTS services in separate threads.
        """
        try:
            if self.verbose >= 2:
                print('Starting reasoning service thread...')
            # if there are no threads remaining with daemon=False, the main thread will exit
            reasoning_thread = threading.Thread(
                target=self.run_reasoning_service,
                name='reasoning_service',
                daemon=True,
            )
            reasoning_thread.start()
            self.shared_variable_manager.add_to(queue_name='running_components', value='reasoning_service')
            if self.verbose >= 1:
                print('Reasoning service thread started.')

        except Exception as e:
            utils.print_exception(exception=e, message='Error starting reasoning service thread')
            self.shared_variable_manager.remove_from(queue_name='running_components', value='reasoning_service')
            raise

        if self.use_tts_service:
            try:
                if self.verbose >= 2:
                    print('Starting TTS service thread...')
                # if there are no threads remaining with daemon=False, the main thread will exit
                tts_thread = threading.Thread(target=self.run_tts_service, name='tts_service', daemon=True)
                tts_thread.start()
                self.shared_variable_manager.add_to(queue_name='running_components', value='tts_service')
                if self.verbose >= 1:
                    print('TTS service thread started.')
            except Exception as e:
                utils.print_exception(exception=e, message='Error starting TTS service thread')
                self.use_tts_service = False
                self.shared_variable_manager.remove_from(queue_name='running_components', value='tts_service')
                if self.verbose >= 1:
                    print('TTS service disabled due to an error. From now on, the responses will be printed.')

    def get_camera_image(self):
        image_dict = self.shared_variable_manager.get_variable(variable_name='latest_camera_image')
        if time.time() - image_dict['timestamp'] < self.image_spoilage_time:
            return image_dict['image']
        else:
            warnings.warn(f'Image is too old ({time.time() - image_dict["timestamp"]} s). Please wait for a new image'
                          f' to be captured')
            return None
