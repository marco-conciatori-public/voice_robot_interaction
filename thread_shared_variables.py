import threading


class SharedVariableManager:
    def __init__(self, verbose: int = 0):
        # Shared variables
        self.reasoning_requests = []
        self.tts_requests = []
        self.function_call_responses = []
        self.audio_responses = []

        # Locks for thread safety
        self.reasoning_requests_lock = threading.Lock()
        self.tts_requests_lock = threading.Lock()
        self.function_call_responses_lock = threading.Lock()
        self.audio_responses_lock = threading.Lock()

    def add_reasoning_request(self, request) -> None:
        with self.reasoning_requests_lock:
            self.reasoning_requests.append(request)

    def pop_reasoning_request(self):
        with self.reasoning_requests_lock:
            if len(self.reasoning_requests) > 0:
                return self.reasoning_requests.pop(0)
            return None

    def add_tts_request(self, request) -> None:
        with self.tts_requests_lock:
            self.tts_requests.append(request)

    def pop_tts_request(self):
        with self.tts_requests_lock:
            if len(self.tts_requests) > 0:
                return self.tts_requests.pop(0)
            return None

    def add_function_call_response(self, response) -> None:
        with self.function_call_responses_lock:
            self.function_call_responses.append(response)

    def pop_function_call_response(self):
        with self.function_call_responses_lock:
            if len(self.function_call_responses) > 0:
                return self.function_call_responses.pop(0)
            return None

    def add_audio_response(self, response) -> None:
        with self.audio_responses_lock:
            self.audio_responses.append(response)

    def pop_audio_response(self):
        with self.audio_responses_lock:
            if len(self.audio_responses) > 0:
                return self.audio_responses.pop(0)
            return None
