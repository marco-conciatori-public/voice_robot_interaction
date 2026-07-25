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
        # Agentic loop bounds: how many observe-act steps one request may take, and how long to wait
        # after dispatching a motion before letting the model observe its result.
        self.max_reasoning_steps = parameters['max_reasoning_steps']
        self.action_settle_time = parameters['action_settle_time']
        self.verbose = parameters['verbose']

        self.reasoning_service = ReasoningService(client=self.client, tools=self.tools, **self.reasoning_parameters)

    def run_reasoning_service(self) -> None:
        """
        Continuously processes reasoning requests from the shared variable manager.
        Each request (a captured audio prompt) is handled with a multi-step observe-act loop.
        """
        while True:
            request = self.shared_variable_manager.pop_from(queue_name='reasoning_requests')
            if request is not None:
                self._handle_reasoning_request(request)
            else:
                time.sleep(0.2)
            time.sleep(0.02)

    def _handle_reasoning_request(self, request: dict) -> None:
        """
        Drive one user request to completion through the observe-act loop.

        The model can call functions (arm/wheel moves dispatched to the RDK X3, or get_camera_image
        served locally). After each call its result is fed back so the model can look again and act
        again, until it produces a plain-text answer or the step budget runs out. Only the final
        textual answer is spoken; intermediate narration is printed when verbose.
        """
        # When history is not persisted across requests, start each one from a clean transcript.
        if not self.reasoning_service.remember_history:
            self.reasoning_service.reset_history()

        try:
            next_contents = [self.reasoning_service.build_user_content(**request)]
        except Exception as e:
            utils.print_exception(exception=e, message='Invalid reasoning request')
            return

        final_text = None
        reached_final_answer = False
        for step in range(self.max_reasoning_steps):
            text, function_call = self.reasoning_service.send(next_contents)
            if function_call is None:
                # No further action requested: this is the model's final answer (or an error -> None).
                final_text = text
                reached_final_answer = True
                break
            if self.verbose >= 1 and text:
                print(f'(reasoning step {step}) {text}')
            next_contents = self._execute_function_call(function_call)

        if not reached_final_answer and self.verbose >= 1:
            print(f'Reasoning stopped after reaching max_reasoning_steps ({self.max_reasoning_steps}).')

        if final_text is not None:
            if self.use_tts_service:
                self.shared_variable_manager.add_to(queue_name='tts_requests', value=final_text)
            elif self.verbose >= 1:
                print(final_text)

    def _execute_function_call(self, function_call) -> list:
        """
        Execute one function call and build the tool-response Content(s) to feed back to the model.

        get_camera_image is served locally: the fresh arm-camera frame is returned to the model as an
        image. Every other function is a robot actuator command dispatched to the RDK X3 over the
        command channel (fire-and-forget, no result comes back), so the model is simply told it was
        dispatched and is expected to observe the effect with a follow-up get_camera_image.
        """
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}
        image_mime_type = self.reasoning_service.image_mime_type

        if name == 'get_camera_image':
            image = self.get_camera_image()
            if image is not None:
                return [
                    types.Content(role='tool', parts=[
                        types.Part.from_function_response(name=name, response={'status': 'ok'}),
                    ]),
                    types.Content(role='user', parts=[
                        types.Part.from_bytes(data=image, mime_type=image_mime_type),
                        types.Part.from_text(text='This is the current view from the arm camera.'),
                    ]),
                ]
            return [types.Content(role='tool', parts=[
                types.Part.from_function_response(
                    name=name,
                    response={'status': 'error', 'message': 'No fresh camera image available.'},
                ),
            ])]

        # Any other function is a robot actuator command handled on the RDK X3.
        self.shared_variable_manager.add_to(queue_name='functions_to_call', value=function_call)
        self._wait_for_action(args)
        return [types.Content(role='tool', parts=[
            types.Part.from_function_response(name=name, response={'status': 'dispatched'}),
        ])]

    def _wait_for_action(self, args: dict) -> None:
        """Give a dispatched motion time to complete before the model observes its result."""
        settle = self.action_settle_time
        duration = args.get('duration')
        if isinstance(duration, (int, float)):
            settle += duration
        if settle > 0:
            time.sleep(settle)

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
        """
        The latest arm camera frame, or None if there is no usable one.

        Both failure cases return None rather than raising, so _execute_function_call can report them back
        to the model as a tool result and let it retry:
          - No frame at all. 'latest_camera_image' stays None until the UsbCamera thread captures its first
            frame, and stays None for the whole run if the camera could not be opened. Without this check a
            request arriving in that window raised TypeError ('NoneType' is not subscriptable), which
            propagated out of the unguarded run_reasoning_service loop and silently killed the reasoning
            thread: voice interaction then stopped working until the process was restarted.
          - Stale frame. The camera thread has stopped refreshing it, so acting on it would mean acting on
            what the robot saw seconds ago.
        """
        image_dict = self.shared_variable_manager.get_variable(variable_name='latest_camera_image')
        if image_dict is None:
            warnings.warn('No camera image available yet: the USB camera has not produced a frame '
                          '(it may still be starting up, or it failed to open).')
            return None
        image_age = time.time() - image_dict['timestamp']
        if image_age >= self.image_spoilage_time:
            warnings.warn(f'Image is too old ({image_age} s). Please wait for a new image to be captured')
            return None
        return image_dict['image']
