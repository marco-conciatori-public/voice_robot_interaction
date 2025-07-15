import warnings

from google import genai
from google.genai import types


class ReasoningService:
    """
    This class provides a service for reasoning with the Google AI Studio LLM.
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
        :param prompt_template: str: The template for the prompt, which can include instructions or context.
        :param remember_history: bool: Whether to remember the history of interactions, default is False.
        :param audio_mime_type: str: The MIME type of the audio data, default is 'audio/wav'.
        :param image_mime_type: str: The MIME type of the image data, default is 'image/jpeg'.
        """

        self.client = client
        self.model_name = model_name
        self.tools = tools if tools is not None else types.Tool(function_declarations=[])
        self.config = types.GenerateContentConfig(tools=[self.tools])
        self.prompt_template = prompt_template
        self.remember_history = remember_history
        self.audio_mime_type = audio_mime_type
        self.image_mime_type = image_mime_type

        if self.remember_history:
            self.chat = client.chats.create(model=self.model_name, config=self.config)

    def reasoning(self, audio_bytes: bytes = None, image_bytes: bytes = None, **kwargs) -> tuple:
        """
        Sends an audio message or image to the Google AI Studio LLM and returns the response.

        Args:
            audio_bytes: the audio message to send to the LLM.
            image_bytes: the image message to send to the LLM.

        Returns:
            tuple: A tuple containing:
                - is_function_call (bool): Indicates if the response is a function call.
                - response: The response from the LLM, which can be either text or a function call with parameters, or
                 an error message if an exception occurs.
        """
        assert audio_bytes is not None or image_bytes is not None, 'Either audio_bytes or image_bytes must be supplied'
        assert audio_bytes is None or image_bytes is None, 'Only one of audio_bytes or image_bytes can be supplied'
        try:
            chosen_input = None
            if audio_bytes is not None:
                if self.prompt_template is None:
                    chosen_input = [types.Part.from_bytes(data=audio_bytes, mime_type=self.audio_mime_type)]
                else:
                    chosen_input = [self.prompt_template, types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type=self.audio_mime_type,
                    )]
            elif image_bytes is not None:
                if self.prompt_template is None:
                    chosen_input = [types.Part.from_bytes(data=image_bytes, mime_type=self.image_mime_type)]
                else:
                    chosen_input = [self.prompt_template, types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=self.image_mime_type,
                    )]

            if self.remember_history:
                if self.chat is None:
                    raise ValueError("Chat history is enabled but chat object is not initialized.")
                response = self.chat.send_message(chosen_input)
            else:  # without history
                if self.config is None:  # without config
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=chosen_input,
                    )
                else:  # with config
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=chosen_input,
                        config=self.config,
                    )

            text = None
            function_call = None
            for part in response.candidates[0].content.parts:
                if part.text:
                    text = part.text
                elif part.function_call:
                    function_call = part.function_call
                else:
                    warnings.warn(f'Unexpected part type in response:\n\t{part}')

            return text, function_call

        except Exception as e:
            return False, f'An error occurred:\n{e}'
