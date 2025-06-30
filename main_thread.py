import time
import threading

import args
import utils
import global_constants as gc
from google_ai_studio import service_interface
from hardware_interaction import HardwareInteraction
from thread_shared_variables import SharedVariableManager
from microphone.microphone_listener import MicrophoneListener
from ethernet_connection.ethernet_client import EthernetClient


def main_thread(**kwargs):
    """
    Main thread function that initializes the Google AI Studio service interface and the microphone listener.
    It continuously checks for function calls and audio responses, processing them as they come in.
    """
    parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'main_thread.yaml', **kwargs)
    verbose = parameters['verbose']

    # Initialize the hardware interaction interface
    hardware_interaction = HardwareInteraction(verbose=verbose)

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
        hardware_interaction=hardware_interaction,
        verbose=verbose,
    )
    microphone_listener.start_listening()

    # Initialize and start Ethernet client
    ethernet_client_thread = threading.Thread(target=keep_restarting_ethernet_client, name='ethernet_client')
    ethernet_client_thread.start()

    # beep to indicate the system is ready
    hardware_interaction.set_beep(duration=1)

    while True:
        function_call = shared_variable_manager.pop_from(queue_name='functions_to_call')
        if function_call is not None:
            print(f'type(function_call): {type(function_call)}')
            print(f'function_call:\n{function_call}')
            if verbose >= 2:
                print(f'Function call detected:\n\t{function_call.name}{function_call.args}')
            # TODO: Implement the function execution logic
        audio_to_play = shared_variable_manager.pop_from(queue_name='audio_to_play')
        if audio_to_play is not None:
            if verbose >= 2:
                print(f'Audio response received.')
            utils.play_audio(
                audio_bytes=audio_to_play,
                sample_rate=24000,
                channels=1,
                dtype='int16',
            )
        if function_call is None and audio_to_play is None:
            time.sleep(0.2)
        time.sleep(0.05)


def keep_restarting_ethernet_client(shared_variable_manager: SharedVariableManager, verbose: int = 0):
    """
    Continuously attempts to restart the Ethernet client if it is not running.
    """
    ethernet_client = None
    while ethernet_client is None:
        try:
            ethernet_client = EthernetClient(
                shared_variable_manager=shared_variable_manager,
                verbose=verbose,
            )
            ethernet_client.start()
        except Exception as e:
            utils.print_exception(exception=e, message='Ethernet client failed to start')
        time.sleep(10)


if __name__ == '__main__':
    main_thread()
