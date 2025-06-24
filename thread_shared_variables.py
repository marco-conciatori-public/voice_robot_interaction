import threading


class SharedVariableManager:
    def __init__(self, verbose: int = 0):
        # Shared variables
        self.reasoning_requests = []
        self.tts_requests = []
        self.functions_to_call = []
        self.audio_to_play = []
        self.received_ethernet_data = []

        # Locks for thread safety
        self.reasoning_requests_lock = threading.Lock()
        self.tts_requests_lock = threading.Lock()
        self.function_call_responses_lock = threading.Lock()
        self.audio_responses_lock = threading.Lock()
        self.received_ethernet_data_lock = threading.Lock()

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

