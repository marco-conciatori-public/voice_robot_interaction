import re
import time
import wave
import warnings
import threading

from google import genai
from google.genai import types

import args
import utils
import global_constants as gc
from robot_link import endpoints
from google_ai_studio import tts_service
from google_ai_studio import function_declarations
from google_ai_studio.reasoning_service import ReasoningService

# Matches the wait the API asks for in the string form of a 429, e.g. "'retryDelay': '27s'".
_RETRY_DELAY_PATTERN = re.compile(r'retry[_-]?delay["\']?\s*[:=]\s*["\']?(\d+(?:\.\d+)?)s', re.IGNORECASE)


def _find_error_values(payload, wanted_key: str) -> list:
    """Every value stored under `wanted_key` at any depth of a nested dict/list error payload."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == wanted_key:
                found.append(value)
            else:
                found.extend(_find_error_values(value, wanted_key))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found.extend(_find_error_values(item, wanted_key))
    return found


def _parse_retry_delay(exception) -> float:
    """
    The wait the API asked for after a 429, in seconds, or 0.0 when the error does not carry one.

    A Gemini 429 body normally includes a google.rpc.RetryInfo entry ('retryDelay': '27s'), and the
    server knows better than any value hardcoded here. Where exactly that entry sits inside
    APIError.details has moved between google-genai versions, so the payload is searched by key at any
    depth, with the string form of the exception as a last resort, rather than depending on one layout.
    """
    for value in _find_error_values(getattr(exception, 'details', None), 'retryDelay'):
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.fullmatch(r'(\d+(?:\.\d+)?)s?', value.strip())
            if match:
                return float(match.group(1))
    match = _RETRY_DELAY_PATTERN.search(str(exception))
    if match:
        return float(match.group(1))
    return 0.0


def _is_per_day_quota(exception) -> bool:
    """
    Whether a 429 is the daily quota rather than the per-minute rate limit.

    Free-tier quota violations name themselves, e.g. 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'
    against '...PerMinutePerProjectPerModel-FreeTier'. A daily one will not clear within any sensible
    cooldown, so the caller waits the maximum instead of retrying every minute for the rest of the day.
    """
    quota_ids = _find_error_values(getattr(exception, 'details', None), 'quotaId')
    if any('perday' in str(quota_id).lower() for quota_id in quota_ids):
        return True
    return 'perday' in str(exception).lower()


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
        # How TTS behaves once the API starts answering 429 (see _enter_tts_cooldown).
        rate_limit_parameters = parameters['tts_rate_limit']
        self.tts_default_cooldown = rate_limit_parameters['default_cooldown']
        self.tts_max_cooldown = rate_limit_parameters['max_cooldown']
        self.tts_backoff_factor = rate_limit_parameters['backoff_factor']
        self.tts_min_notice_interval = rate_limit_parameters['min_notice_interval']
        self.tts_notice_audio_file_name = rate_limit_parameters['notice_audio_file_name']
        # Runtime rate-limit state. 'use_tts_service' stays the configured intent and is deliberately not
        # touched here, so "TTS is off because it was switched off" stays distinguishable from "TTS is
        # quiet because the quota ran out". These are written by the TTS thread and read by the reasoning
        # thread, but each is a single float assignment, so the GIL is enough and no lock is needed.
        self._tts_blocked_until = 0.0
        self._tts_failure_count = 0
        self._last_tts_notice = 0.0
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
                    time.sleep(0.2)
            except Exception as e:
                utils.print_exception(exception=e, message='Error handling reasoning request. The request was '
                                                           'dropped, the reasoning service is still running')
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
            if self._tts_available():
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

    def _tts_available(self) -> bool:
        """
        Whether an answer should be sent to the TTS model right now.

        False either because TTS is switched off (in the config, or because its thread failed to start),
        or because the API returned 429 and we are still inside the cooldown that followed.
        """
        return self.use_tts_service and time.time() >= self._tts_blocked_until

    def run_tts_service(self) -> None:
        """
        Continuously processes TTS requests from the shared variable manager.
        It converts text prompts to audio using the Google AI Studio TTS service and handles the responses.

        A 429 does not disable TTS for the rest of the run: on the free tier it is usually the per-minute
        rate limit, which clears by itself, so the service only goes quiet for a cooldown (see
        _enter_tts_cooldown) and resumes afterwards. Requests popped while a cooldown is running are
        dropped rather than held: the reasoning loop has long moved on, and speaking an answer minutes
        after the question is worse than staying silent. Their text is still printed.
        """
        while True:
            request = self.shared_variable_manager.pop_from(queue_name='tts_requests')
            if request is not None:
                if not self._tts_available():
                    # Enqueued before the cooldown started. The reasoning thread stops adding requests as
                    # soon as it sees the block, but whatever was already queued still arrives here.
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
                    if getattr(e, 'code', None) == 429:
                        self._enter_tts_cooldown(exception=e)
                    if self.verbose >= 1:
                        print(request)
                else:
                    # The quota is flowing again, so forget how bad it was before.
                    self._tts_failure_count = 0
                if audio_response is not None:
                    self.shared_variable_manager.add_to(queue_name='audio_to_play', value=audio_response)
            else:
                time.sleep(0.2)
            time.sleep(0.02)

    def _enter_tts_cooldown(self, exception) -> None:
        """
        Put the TTS service to sleep after a 429, and say so out loud once.

        The base wait is the retryDelay the server asked for, or the configured default when the error
        carries none. It is then doubled once per consecutive failure and capped at max_cooldown, so a
        limit that keeps being hit backs off instead of retrying at a fixed rate forever. A 429 that
        names a per-day quota waits the maximum straight away, since it will not clear before then.
        The failure count is reset by the first successful call (see run_tts_service).
        """
        self._tts_failure_count += 1
        if _is_per_day_quota(exception):
            cooldown = self.tts_max_cooldown
        else:
            base_cooldown = _parse_retry_delay(exception) or self.tts_default_cooldown
            cooldown = base_cooldown * (self.tts_backoff_factor ** (self._tts_failure_count - 1))
        cooldown = min(cooldown, self.tts_max_cooldown)
        self._tts_blocked_until = time.time() + cooldown

        print(f'TTS rate limit reached (429). Responses will be printed in the console for the next '
              f'{cooldown:.0f} s.')
        self._play_rate_limit_notice()

    def _play_rate_limit_notice(self) -> None:
        """
        Queue the pre-recorded "request limit reached" clip for playback on the RDK X3 speakers.

        Only the PCM frames are sent, not the raw file bytes: the RDK X3 writes whatever arrives straight
        to ALSA without parsing it (audio_bridge_server._serve_speaker_playback), so a WAV header would be
        played as a burst of noise. For the same reason the clip has to already be in the format the
        playback side is configured for; a mismatched file is reported instead of being played at the
        wrong pitch, and the console message above still tells the story.

        Announcing on every 429 would make the robot repeat itself once per cooldown, so the notice has
        its own minimum interval.
        """
        if not self.tts_notice_audio_file_name:
            return
        now = time.time()
        if now - self._last_tts_notice < self.tts_min_notice_interval:
            return

        file_path = gc.ASSETS_FOLDER_PATH + self.tts_notice_audio_file_name
        try:
            with wave.open(file_path, mode='rb') as notice_file:
                channels = notice_file.getnchannels()
                sample_width = notice_file.getsampwidth()
                frame_rate = notice_file.getframerate()
                pcm_bytes = notice_file.readframes(notice_file.getnframes())
        except Exception as file_error:
            utils.print_exception(exception=file_error,
                                  message=f'Could not read the TTS rate limit notice "{file_path}"')
            return

        if (channels, sample_width, frame_rate) != (1, 2, endpoints.SPEAKER_SAMPLE_RATE):
            warnings.warn(f'"{file_path}" is {frame_rate} Hz, {channels} channel(s), {sample_width * 8} bit, '
                          f'but the speakers expect {endpoints.SPEAKER_SAMPLE_RATE} Hz mono 16 bit. '
                          f'Not playing it.')
            return

        self._last_tts_notice = now
        self.shared_variable_manager.add_to(queue_name='audio_to_play', value=pcm_bytes)

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
