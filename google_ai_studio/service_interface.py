import time
import threading

from google import genai
from google.genai import types

import args
import utils
import global_constants as gc
from google_ai_studio import tts_service
from google_ai_studio import reasoning_service
from google_ai_studio import function_declarations


class GoogleAIStudioService:
    """
    This class serves as an interface to the Google AI Studio services, including reasoning and text-to-speech (TTS).
    It manages the communication with the Google AI Studio API and handles requests and responses.
    """

    def __init__(self, shared_variable_manager, **kwargs):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'service_interface.yaml', **kwargs)
        self.verbose = parameters['verbose']
        self.shared_variable_manager = shared_variable_manager
        self.client = genai.Client(api_key=utils.get_api_key(file_path=parameters['api_key_file_path']))
        self.tools = types.Tool(function_declarations=function_declarations.function_list)
        self.config = types.GenerateContentConfig(tools=[self.tools])
        self.reasoning_parameters = parameters['reasoning_parameters']
        self.tts_parameters = parameters['tts_parameters']

    def run_reasoning_service(self):
        """
        Continuously processes reasoning requests from the shared variable manager.
        It sends audio prompts to the Google AI Studio LLM and handles the responses.
        """
        while True:
            request = self.shared_variable_manager.pop_reasoning_request()
            if request is not None:
                textual_response, function_call_response = reasoning_service.reasoning(
                    client=self.client,
                    config=self.config,
                    **request,
                    **self.reasoning_parameters,
                )
                if function_call_response is not None:
                    self.shared_variable_manager.add_function_call_response(function_call_response)
                if textual_response is not None:
                    self.shared_variable_manager.add_tts_request(textual_response)
            else:
                time.sleep(0.2)
            time.sleep(0.02)

    def run_tts_service(self):
        """
        Continuously processes TTS requests from the shared variable manager.
        It converts text prompts to audio using the Google AI Studio TTS service and handles the responses.
        """
        while True:
            request = self.shared_variable_manager.pop_tts_request()
            if request is not None:
                audio_response = tts_service.text_to_speech(
                    text_input=request,
                    client=self.client,
                    **self.tts_parameters,
                    verbose=self.verbose,
                )
                self.shared_variable_manager.add_audio_response(audio_response)
            else:
                time.sleep(0.2)
            time.sleep(0.02)

    def start_services(self):
        """
        Starts the reasoning and TTS services in separate threads.
        """
        try:
            if self.verbose >= 2:
                print('Starting reasoning service thread...')
            reasoning_thread = threading.Thread(target=self.run_reasoning_service, name='reasoning_service')
            reasoning_thread.start()
            if self.verbose >= 1:
                print('Reasoning service thread started.')

        except Exception as e:
            print(f'Error starting reasoning service thread:')
            print(e)
            print(e.__traceback__)
            raise

        try:
            if self.verbose >= 2:
                print('Starting TTS service thread...')
            tts_thread = threading.Thread(target=self.run_tts_service, name='tts_service')
            tts_thread.start()
            if self.verbose >= 1:
                print('TTS service thread started.')
        except Exception as e:
            print(f'Error starting TTS service thread:')
            print(e)
            print(e.__traceback__)
            raise

        return reasoning_thread, tts_thread
