import warnings

from google import genai
from google.genai import types

import utils


class ReasoningService:
    """
    Talks to the Google AI Studio LLM for one conversation.

    This object only handles the model I/O: it keeps a running transcript (a list of types.Content
    alternating user / model / tool turns) and exposes low-level primitives so a caller can drive a
    multi-step "observe, act, observe again" loop. Executing the function calls (dispatching robot
    commands, capturing camera frames) is the caller's job, because that needs hardware / network
    access this class deliberately knows nothing about.
    """
    def __init__(self,
                 client: genai.Client,
                 model_name: str,
                 tools: types.Tool = None,
                 prompt_template: str = None,
                 remember_history: bool = False,
                 audio_mime_type: str = 'audio/wav',
                 image_mime_type: str = 'image/jpeg',
                 ):
        """
        Initializes the ReasoningService with the Google AI Studio client, model name, and optional configuration.
        :param client: genai.Client: The Google AI Studio client to use for generating responses.
        :param model_name: str: The model to use for generating the response.
        :param tools: types.Tool: Optional tools to use for the reasoning process, default is None.
        :param prompt_template: str: System instruction sent once to the model (not repeated each turn).
        :param remember_history: bool: Whether to keep the transcript across separate user requests, default is False.
        :param audio_mime_type: str: The MIME type of the audio data, default is 'audio/wav'.
        :param image_mime_type: str: The MIME type of the image data, default is 'image/jpeg'.
        """

        self.client = client
        self.model_name = model_name
        self.tools = tools if tools is not None else types.Tool(function_declarations=[])
        self.prompt_template = prompt_template
        self.remember_history = remember_history
        self.audio_mime_type = audio_mime_type
        self.image_mime_type = image_mime_type

        # The system prompt is delivered once as system_instruction rather than being prepended to
        # every user turn (which is what the old single-shot code did).
        self.config = types.GenerateContentConfig(
            tools=[self.tools],
            system_instruction=self.prompt_template if self.prompt_template else None,
        )
        # Running transcript of the current exchange. When remember_history is True it also carries
        # over between user requests; otherwise the caller resets it (reset_history) each time.
        self.contents = []

    def reset_history(self) -> None:
        """Drop the transcript so the next request starts a fresh conversation."""
        self.contents = []

    def build_user_content(self, audio_bytes: bytes = None, image_bytes: bytes = None) -> types.Content:
        """
        Wrap a raw audio or image prompt into a user-role Content ready to send.

        Exactly one of audio_bytes / image_bytes must be supplied.
        """
        assert (audio_bytes is None) != (image_bytes is None), \
            'Exactly one of audio_bytes or image_bytes must be supplied'
        if audio_bytes is not None:
            part = types.Part.from_bytes(data=audio_bytes, mime_type=self.audio_mime_type)
        else:
            part = types.Part.from_bytes(data=image_bytes, mime_type=self.image_mime_type)
        return types.Content(role='user', parts=[part])

    def send(self, new_contents: list) -> tuple:
        """
        Append new_contents to the transcript, query the model once, and return its reply.

        Args:
            new_contents: a list of types.Content to add before querying (the user input on the first
                step, or the tool responses to the model's previous function call on later steps).

        Returns:
            tuple (text, function_call):
                - text (str | None): the model's textual reply, or None if it only made a function call.
                - function_call: the function call the model requested, or None if it replied with text.
            The model's reply is appended to the transcript so the next send() continues the exchange.
            On error, returns (None, None) after logging the exception (the failed turn is rolled back
            so the transcript stays consistent).
        """
        turn_start = len(self.contents)
        try:
            self.contents.extend(new_contents)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=self.contents,
                config=self.config,
            )
            candidate = response.candidates[0]
            # Keep the model's turn (which may carry a function call) in the transcript.
            self.contents.append(candidate.content)

            text = None
            function_call = None
            for part in candidate.content.parts:
                if part.text:
                    text = part.text
                elif part.function_call:
                    function_call = part.function_call
                else:
                    warnings.warn(f'Unexpected part type in response:\n\t{part}')

            return text, function_call

        except Exception as e:
            # Roll back the half-finished turn so a later request does not inherit a dangling input.
            del self.contents[turn_start:]
            utils.print_exception(exception=e, message='Error during reasoning')
            return None, None
