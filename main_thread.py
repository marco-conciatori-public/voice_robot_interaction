import time
import threading

import args
import utils
import global_constants as gc
from google_ai_studio import service_interface
from sensors.camera.usb_camera import UsbCamera
from hardware_interaction import HardwareInteraction
from thread_shared_variables import SharedVariableManager
from ethernet_connection.ethernet_client import EthernetClient
from sensors.microphone.microphone_listener import MicrophoneListener


def main_thread(**kwargs):
    """
    Main thread function that initializes the Google AI Studio service interface and the microphone listener.
    It continuously checks for function calls and audio responses, processing them as they come in.
    """
    parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'main_thread.yaml', **kwargs)
    verbose = parameters['verbose']

    # Initialize the shared variable manager
    shared_variable_manager = SharedVariableManager(verbose=verbose)

    # Initialize the hardware interaction interface
    hardware_interaction = HardwareInteraction(shared_variable_manager=shared_variable_manager, verbose=verbose)

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

    ethernet_client_kwargs = {
        'shared_variable_manager': shared_variable_manager,
        'verbose': verbose,
    }
    # Initialize and start Ethernet client
    ethernet_client_thread = threading.Thread(
        target=keep_restarting_ethernet_client,
        name='ethernet_client',
        kwargs=ethernet_client_kwargs,
    )
    ethernet_client_thread.start()

    usb_camera = UsbCamera(shared_variable_manager=shared_variable_manager, verbose=verbose)
    usb_camera_thread = threading.Thread(
        target=usb_camera.ready_latest_image,
        name='usb_camera',
        daemon=True,
    )
    usb_camera_thread.start()

    counter = 0
    setup_complete = False
    while counter < 5:
        if (shared_variable_manager.length(queue_name='running_components') ==
                shared_variable_manager.get_variable(variable_name='expected_component_number')):
            setup_complete = True
            break
        time.sleep(2)
        counter += 1

    if setup_complete:
        print('System ready, all components running.')
        # beep to indicate the system is ready
        hardware_interaction.set_beep(duration=0.2)
    else:
        print('System setup failed.')
        hardware_interaction.set_beep(duration=0.2)
        time.sleep(0.05)
        hardware_interaction.set_beep(duration=0.2)
        time.sleep(0.05)
        hardware_interaction.set_beep(duration=0.2)
        print(f'Expected {shared_variable_manager.get_variable(variable_name="expected_component_number")} components,'
              f' but only found {shared_variable_manager.length(queue_name="running_components")}.')
        temp_running_components = shared_variable_manager.get_copy(queue_name='running_components')
        temp_already_counted_components = shared_variable_manager.get_copy(queue_name='already_counted_components')
        for component in temp_already_counted_components:
            if component not in temp_running_components:
                print(f'\tComponent {component} missing from running_components.')
        # exit()

    while True:
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
        else:
            time.sleep(0.2)
        time.sleep(0.05)


def keep_restarting_ethernet_client(shared_variable_manager: SharedVariableManager, verbose: int = 0):
    """
    Continuously attempts to restart the Ethernet client if it is not running.
    """
    while not shared_variable_manager.has_value(queue_name='running_components', value='ethernet_client'):
        if verbose >= 2:
            print('Ethernet client not running. Attempting to restart in 10 seconds...')
        try:
            ethernet_client = EthernetClient(
                shared_variable_manager=shared_variable_manager,
                verbose=verbose,
            )
            ethernet_client.start()
            shared_variable_manager.add_to(queue_name='running_components', value='ethernet_client')
        except Exception as e:
            utils.print_exception(exception=e, message='Ethernet client failed. Retrying in 5 seconds...')
            shared_variable_manager.remove_from(queue_name='running_components', value='ethernet_client')
        time.sleep(5)


if __name__ == '__main__':
    main_thread()
