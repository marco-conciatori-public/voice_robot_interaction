import os
import time
from pathlib import Path

import args
import utils
import global_constants as gc
from google_ai_studio import service_interface
from thread_shared_variables import SharedVariableManager
from microphone.microphone_listener import MicrophoneListener


def main_thread(**kwargs):
    """
    Main thread function that initializes the Google AI Studio service interface and the microphone listener.
    It continuously checks for function calls and audio responses, processing them as they come in.
    """
    parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'main_thread.yaml', **kwargs)
    verbose = parameters['verbose']

    print('-----------------------------------------------------------')
    print(os.system('whoami'))  # Print the current user for debugging purposes
    print('-----------------------------------------------------------')

    # Initialize the shared variable manager
    shared_variable_manager = SharedVariableManager(verbose=verbose)

    # Initialize the Google AI Studio service interface
    google_ai_studio_service = service_interface.GoogleAIStudioService(
        shared_variable_manager=shared_variable_manager,
        verbose=verbose,
    )
    google_ai_studio_service.start_services()

    # Initialize the microphone listener
    microphone_listener = MicrophoneListener(
        shared_variable_manager=shared_variable_manager,
        verbose=verbose,
    )
    microphone_listener.start_listening()

    # # add all mp3 files in the data folder
    # for file in Path(gc.DATA_FOLDER_PATH).glob('*.mp3'):
    #     with open(file, 'rb') as audio_file:
    #         shared_variable_manager.add_reasoning_request({'audio_bytes': audio_file.read()})

    while True:
        function_call = shared_variable_manager.pop_function_call_response()
        if function_call is not None:
            print(f'function_call: {function_call}')
            if verbose >= 2:
                print(f'Function call detected:\n\t{function_call.name}{function_call.args}')
            # TODO: Implement the function execution logic
        audio_response = shared_variable_manager.pop_audio_response()
        if audio_response is not None:
            if verbose >= 2:
                print(f'Audio response received.')
            utils.play_audio(
                audio_bytes=audio_response,
                sample_rate=24000,
                channels=1,
                dtype='int16',
            )
            # TODO: send to robot speaker

        if function_call is None and audio_response is None:
            time.sleep(0.2)
        time.sleep(0.05)


if __name__ == '__main__':
    main_thread()
