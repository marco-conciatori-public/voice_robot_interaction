import threading


class SharedVariableManager:
    def __init__(self, verbose: int = 0):
        self.verbose = verbose
        # Shared queues
        self.running_components = []
        self.reasoning_requests = []
        self.tts_requests = []
        self.functions_to_call = []
        self.audio_to_play = []
        self.received_ethernet_data = []

        # Shared variables
        # this is a dict containing the raw bytes in 'image' and the acquisition time in 'timestamp'
        self.latest_camera_image = None

        # Locks for thread safety
        self.running_components_lock = threading.Lock()
        self.reasoning_requests_lock = threading.Lock()
        self.tts_requests_lock = threading.Lock()
        self.functions_to_call_lock = threading.Lock()
        self.audio_to_play_lock = threading.Lock()
        self.received_ethernet_data_lock = threading.Lock()
        self.latest_camera_image_lock = threading.Lock()

    # QUEUE METHODS
    def add_to(self, queue_name: str, value) -> None:
        """
        Adds a value to a shared variable list.
        :param queue_name: The name of the shared variable list.
        :param value: The value to add to the list.
        """
        lock = getattr(self, f"{queue_name}_lock")
        with lock:
            getattr(self, queue_name).append(value)

    def pop_from(self, queue_name: str):
        """
        Pops a value from a shared variable list.
        :param queue_name: The name of the shared variable list.
        :return: The popped value or None if the list is empty.
        """
        lock = getattr(self, f"{queue_name}_lock")
        with lock:
            variable_list = getattr(self, queue_name)
            if len(variable_list) > 0:
                return variable_list.pop(0)
            return None

    def remove_from(self, queue_name: str, value) -> bool:
        lock = getattr(self, f"{queue_name}_lock")
        with lock:
            variable_list = getattr(self, queue_name)
            if value in variable_list:
                variable_list.remove(value)
                return True
            return False

    def has_value(self, queue_name: str, value) -> bool:
        lock = getattr(self, f"{queue_name}_lock")
        with lock:
            variable_list = getattr(self, queue_name)
            return value in variable_list

    # VARIABLE METHODS
    def set_variable(self, variable_name: str, value) -> None:
        lock = getattr(self, f'{variable_name}_lock')
        with lock:
            setattr(self, variable_name, value)

    def get_variable(self, variable_name: str):
        lock = getattr(self, f'{variable_name}_lock')
        with lock:
            return getattr(self, variable_name)
