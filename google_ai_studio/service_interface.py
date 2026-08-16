import time
import warnings
import threading

from google import genai
from google.genai import types

import args
import utils
import global_constants as gc
from robot_link import endpoints
from google_ai_studio import tts_service
from google_ai_studio import rate_limit_guard
from google_ai_studio import function_declarations
from google_ai_studio.rate_limit_guard import RateLimitGuard
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

        # One cooldown per service: they call different models, so exhausting one quota says nothing
        # about the other, and the robot can perfectly well keep thinking while it cannot speak.
        # 'use_tts_service' stays the configured intent and is deliberately left out of this, so "TTS is
        # off because it was switched off" stays distinguishable from "TTS is quiet because the quota
        # ran out".
        rate_limit_parameters = parameters['rate_limit']
        self.reasoning_guard = RateLimitGuard(name='reasoning', **rate_limit_parameters)
        self.tts_guard = RateLimitGuard(name='tts', **rate_limit_parameters)
        self.notice_audio = self._load_notice_audio(file_names=parameters['audio_notices'])

        self.reasoning_service = ReasoningService(client=self.client, tools=self.tools, **self.reasoning_parameters)

    def _load_notice_audio(self, file_names: dict) -> dict:
        """
        Read the pre-recorded notice clips into memory once, as bare PCM frames keyed by situation.

        These are what the robot says when it cannot say anything for itself, so none of them can be
        produced on demand: the answer to "the TTS quota ran out" cannot be another TTS call. Loading
        them at startup rather than at playback time means a missing or wrongly encoded file is reported
        while someone is still watching the console, instead of at the one moment it was needed. It also
        keeps a synchronous SD-card read off the speech path, and they are a couple of MB in total.

        Only the frames are kept, never the file bytes: the RDK X3 writes whatever arrives straight to
        ALSA without parsing it (audio_bridge_server._serve_speaker_playback), so a WAV header would be
        played as a burst of noise and a clip in the wrong format would come out at the wrong pitch
        rather than raising. Anything unusable is reported and stored as None, which _play_notice then
        skips: a robot that cannot announce its rate limit is much better than one that will not start.
        """
        expected_format = (1, 2, endpoints.SPEAKER_SAMPLE_RATE)
        notice_audio = {}
        for notice_key, file_name in file_names.items():
            notice_audio[notice_key] = None
            if not file_name:
                continue
            file_path = gc.ASSETS_FOLDER_PATH + file_name
            try:
                pcm_bytes, channels, sample_width, frame_rate = utils.read_wave_file(file_path=file_path)
            except Exception as e:
                utils.print_exception(exception=e, message=f'Could not read the "{notice_key}" notice "{file_path}"')
                continue
            if (channels, sample_width, frame_rate) != expected_format:
                warnings.warn(f'"{file_path}" is {frame_rate} Hz, {channels} channel(s), {sample_width * 8} bit, '
                              f'but the speakers expect {endpoints.SPEAKER_SAMPLE_RATE} Hz mono 16 bit. '
                              f'The "{notice_key}" notice will not be played. Re-record it with '
                              f'scripts/create_message_audio.py.')
                continue
            notice_audio[notice_key] = pcm_bytes

        missing = [notice_key for notice_key in notice_audio if notice_audio[notice_key] is None]
        if missing:
            warnings.warn(f'No usable audio for these notices: {", ".join(missing)}. '
                          f'The robot will stay silent in those situations.')
        elif self.verbose >= 2:
            print(f'Loaded {len(notice_audio)} pre-recorded audio notices.')
        return notice_audio

    def _play_notice(self, notice_key: str) -> None:
        """
        Queue one pre-recorded clip for playback on the RDK X3 speakers.

        Accepts None so callers can hand over whatever a RateLimitGuard returned without checking it
        first: the guard answers None when this situation does not deserve a notice, which is most of
        the time, and that has to stay as cheap to handle as the cases that do.
        """
        if notice_key is None:
            return
        pcm_bytes = self.notice_audio.get(notice_key)
        if pcm_bytes is None:
            if self.verbose >= 1:
                print(f'No usable audio notice for "{notice_key}", staying silent.')
            return
        self.shared_variable_manager.add_to(queue_name='audio_to_play', value=pcm_bytes)

    def run_reasoning_service(self) -> None:
        """
        Continuously processes reasoning requests from the shared variable manager.
        Each request (a captured audio prompt) is handled with a multi-step observe-act loop.

        One failed request must never take the service down with it. This loop is the whole body of the
        reasoning thread, so any exception escaping it ends that thread for the rest of the run: voice
        interaction would stop working with nothing logged, and main_thread would still list
        'reasoning_service' in running_components because nothing tells it otherwise. Any unexpected error
        is therefore logged and the loop moves on to the next request. The failed request has already been
        popped, so it is dropped rather than retried forever.
        Exception (not a bare except) so KeyboardInterrupt and SystemExit still propagate and can stop the
        process normally.
        """
        while True:
            try:
                request = self.shared_variable_manager.pop_from(queue_name='reasoning_requests')
                if request is not None:
                    self._handle_reasoning_request(request)
                else:
                    # Idle passes are what makes the recovery announcement possible: a cooldown running
                    # out is not an event anything else would notice, and waiting for the next request
                    # to discover it would mean the user has to guess when to try again.
                    self._play_notice(self.reasoning_guard.poll_recovery())
                    time.sleep(0.2)
            except Exception as e:
                utils.print_exception(exception=e, message='Error handling reasoning request. The request was '
                                                           'dropped, the reasoning service is still running')
                self._play_notice('reasoning_error')
            time.sleep(0.02)

    def _handle_reasoning_request(self, request: dict) -> None:
        """
        Drive one user request to completion through the observe-act loop.

        The model can call functions (arm/wheel moves dispatched to the RDK X3, or get_camera_image
        served locally). After each call its result is fed back so the model can look again and act
        again, until it produces a plain-text answer or the step budget runs out. Only the final
        textual answer is spoken; intermediate narration is printed when verbose.

        Every way this can end badly (rate limit, API error, step budget exhausted) has a pre-recorded
        clip, because the user is standing in front of the robot waiting for an answer and silence is
        the one response they cannot interpret.
        """
        if not self.reasoning_guard.available():
            # Nothing can be done with this request: the model would refuse the call. Holding it would
            # only mean answering a question minutes after it was asked, so it is dropped, but not in
            # silence, since the user has just spoken and deserves to know why nothing happens.
            self._play_notice(self.reasoning_guard.notice_while_blocked())
            return

        # When history is not persisted across requests, start each one from a clean transcript.
        if not self.reasoning_service.remember_history:
            self.reasoning_service.reset_history()

        try:
            next_contents = [self.reasoning_service.build_user_content(**request)]
        except Exception as e:
            utils.print_exception(exception=e, message='Invalid reasoning request')
            self._play_notice('reasoning_error')
            return

        final_text = None
        reached_final_answer = False
        for step in range(self.max_reasoning_steps):
            try:
                text, function_call = self.reasoning_service.send(next_contents)
            except Exception as e:
                self._handle_reasoning_failure(exception=e)
                return
            # The call went through, so a cooldown this request had been waiting out is over for good.
            self._play_notice(self.reasoning_guard.register_success())
            if function_call is None:
                # No further action requested: this is the model's final answer.
                final_text = text
                reached_final_answer = True
                break
            if self.verbose >= 1 and text:
                print(f'(reasoning step {step}) {text}')
            next_contents = self._execute_function_call(function_call)

        if not reached_final_answer:
            if self.verbose >= 1:
                print(f'Reasoning stopped after reaching max_reasoning_steps ({self.max_reasoning_steps}).')
            # The robot has been moving for several steps and then stops with nothing to say, which
            # looks exactly like a crash from outside. Say that the attempt was given up on instead.
            self._play_notice('task_incomplete')

        if final_text is not None:
            if self._tts_available():
                self.shared_variable_manager.add_to(queue_name='tts_requests', value=final_text)
            else:
                if self.verbose >= 1:
                    print(final_text)
                if self.use_tts_service:
                    # There is an answer and it cannot be spoken. Repeating why (subject to the guard's
                    # own interval) is the only feedback the user gets, since with TTS in a cooldown
                    # every question from here on is met with silence.
                    self._play_notice(self.tts_guard.notice_while_blocked())

    def _handle_reasoning_failure(self, exception) -> None:
        """
        Report a failed reasoning call, and put the service to sleep when the API refused it on quota.

        A 429 is not a broken robot, it is a robot that has been asked too many questions too quickly,
        so the request is the only casualty: the service pauses for a cooldown and comes back by itself
        (see RateLimitGuard). Any other error is a one-off, and pausing over it would take the robot out
        of service for a problem that may not happen again.
        """
        utils.print_exception(exception=exception,
                              message='Error during reasoning. The request was dropped')
        if not rate_limit_guard.is_rate_limit(exception):
            self._play_notice('reasoning_error')
            return

        notice_key = self.reasoning_guard.register_failure(exception=exception)
        print(f'Reasoning rate limit reached (429). Requests will be refused for the next '
              f'{self.reasoning_guard.remaining_cooldown():.0f} s.')
        self._play_notice(notice_key)

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

    def _tts_available(self) -> bool:
        """
        Whether an answer should be sent to the TTS model right now.

        False either because TTS is switched off (in the config, or because its thread failed to start),
        or because the API returned 429 and the cooldown that followed is still running.
        """
        return self.use_tts_service and self.tts_guard.available()

    def run_tts_service(self) -> None:
        """
        Continuously processes TTS requests from the shared variable manager.
        It converts text prompts to audio using the Google AI Studio TTS service and handles the responses.

        A 429 does not disable TTS for the rest of the run: on the free tier it is usually the per-minute
        rate limit, which clears by itself, so the service only goes quiet for a cooldown (see
        RateLimitGuard) and resumes afterwards. Requests popped while a cooldown is running are dropped
        rather than held: the reasoning loop has long moved on, and speaking an answer minutes after the
        question is worse than staying silent. Their text is still printed.
        """
        while True:
            request = self.shared_variable_manager.pop_from(queue_name='tts_requests')
            if request is not None:
                if not self._tts_available():
                    # Enqueued before the cooldown started. The reasoning thread stops adding requests as
                    # soon as it sees the block (and is the one that announces it, since it knows a user
                    # is waiting), but whatever was already queued still arrives here.
                    if self.verbose >= 1:
                        print(request)
                    time.sleep(0.02)
                    continue
                try:
                    audio_response = tts_service.text_to_speech(
                        text_input=request,
                        client=self.client,
                        **self.tts_parameters,
                        verbose=self.verbose,
                    )
                except Exception as e:
                    utils.print_exception(exception=e, message='Error in TTS service')
                    audio_response = None
                    # A rate limit or an exhausted quota is temporary, so pause TTS for a while instead
                    # of calling the API again for every following request only to fail the same way.
                    if rate_limit_guard.is_rate_limit(e):
                        notice_key = self.tts_guard.register_failure(exception=e)
                        print(f'TTS rate limit reached (429). Responses will be printed in the console '
                              f'for the next {self.tts_guard.remaining_cooldown():.0f} s.')
                        self._play_notice(notice_key)
                    if self.verbose >= 1:
                        print(request)
                else:
                    # The quota is flowing again, so forget how bad it was before. Queued before the
                    # answer itself, so "available again" is not heard after the proof of it.
                    self._play_notice(self.tts_guard.register_success())
                if audio_response is not None:
                    self.shared_variable_manager.add_to(queue_name='audio_to_play', value=audio_response)
            else:
                # See run_reasoning_service: the idle pass is where a cooldown running out is noticed.
                self._play_notice(self.tts_guard.poll_recovery())
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
                # Unlike a 429 (which only pauses TTS), this one is permanent: there is no thread to
                # consume the queue, so nothing would ever be spoken. Clearing the configured intent is
                # the correct move here, and _tts_available() keeps returning False for the whole run.
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
