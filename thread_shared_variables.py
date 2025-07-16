import threading


class SharedVariableManager:
    def __init__(self, verbose: int = 0):
        # internal parameters
        self.verbose = verbose

        # Shared queues
        self.reasoning_requests = []
        self.tts_requests = []
        self.functions_to_call = []
        self.audio_to_play = []
        self.received_ethernet_data = []

        # Shared variables
        # this is a dict containing the raw bytes in 'image' and the acquisition time in 'timestamp'
        self.latest_camera_image = None

        # Locks for thread safety
        self.reasoning_requests_lock = threading.Lock()
        self.tts_requests_lock = threading.Lock()
        self.functions_to_call_lock = threading.Lock()
        self.audio_to_play_lock = threading.Lock()
        self.received_ethernet_data_lock = threading.Lock()
        self.latest_camera_image_lock = threading.Lock()

        # variables and locks for components logic
        self.running_components = []
        # "expected_component_number" will count the number of components/services the system is expected to have based
        # on the "add_to" calls on "running_components"
        self.expected_component_number = 0
        self.already_counted_components = []
        self.running_components_lock = threading.Lock()
        self.expected_component_number_lock = threading.Lock()
        self.already_counted_components_lock = threading.Lock()

    # QUEUE METHODS
    def add_to(self, queue_name: str, value) -> None:
        """
        Adds a value to a shared variable list.
        :param queue_name: The name of the shared variable list.
        :param value: The value to add to the list.
        """
        # if we are adding values to the running_components list, we need to increase the expected_component_number,
        # but only if the component is not already counted. Es. ethernet client could be added many times.
        increase_component_number = False
        if queue_name == 'running_components':
            with self.already_counted_components_lock:
                if value not in self.already_counted_components:
                    self.already_counted_components.append(value)
                    increase_component_number = True
            if increase_component_number:
                with self.expected_component_number_lock:
                    self.expected_component_number += 1

        lock = getattr(self, f'{queue_name}_lock')
        with lock:
            getattr(self, queue_name).append(value)

    def pop_from(self, queue_name: str):
        """
        Pops a value from a shared variable list.
        :param queue_name: The name of the shared variable list.
        :return: The popped value or None if the list is empty.
        """
        lock = getattr(self, f'{queue_name}_lock')
        with lock:
            variable_list = getattr(self, queue_name)
            if len(variable_list) > 0:
                return variable_list.pop(0)
            return None

    def remove_from(self, queue_name: str, value) -> bool:
        lock = getattr(self, f'{queue_name}_lock')
        with lock:
            variable_list = getattr(self, queue_name)
            if value in variable_list:
                variable_list.remove(value)
                return True
            return False

    def has_value(self, queue_name: str, value) -> bool:
        lock = getattr(self, f'{queue_name}_lock')
        with lock:
            variable_list = getattr(self, queue_name)
            return value in variable_list

    def length(self, queue_name: str) -> int:
        lock = getattr(self, f'{queue_name}_lock')
        with lock:
            return len(getattr(self, queue_name))

    def get_copy(self, queue_name: str) -> list:
        lock = getattr(self, f'{queue_name}_lock')
        with lock:
            return getattr(self, queue_name).copy()

    # VARIABLE METHODS
    def set_variable(self, variable_name: str, value) -> None:
        lock = getattr(self, f'{variable_name}_lock')
        with lock:
            setattr(self, variable_name, value)

    def get_variable(self, variable_name: str):
        lock = getattr(self, f'{variable_name}_lock')
        with lock:
            return getattr(self, variable_name)
