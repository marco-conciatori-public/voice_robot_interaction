import warnings

from google import genai
from google.genai import types


def reasoning(model_name: str,
              audio_bytes,
              prompt_template: str,
              client: genai.Client,
              config=None,
              mime_type='audio/wav') -> tuple:
    """
    Sends a text prompt to the Google AI Studio LLM and returns the response.

    Args:
        model_name: str: The model to use for generating the response.
        audio_bytes: The prompt to send to the LLM (audio).
        prompt_template: str: The template for the prompt, which can include instructions or context.
        client: genai.Client: The Google AI Studio client to use for generating the response.
        config (types.GenerateContentConfig): Configuration for the content generation, including tools.
        mime_type (str): The MIME type of the audio data, default is 'audio/wav'.

    Returns:
        tuple: A tuple containing:
            - is_function_call (bool): Indicates if the response is a function call.
            - response: The response from the LLM, which can be either text or a function call with parameters, or an
             error message if an exception occurs.
    """
    try:
        audio_input = [
            prompt_template,
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        ]
        if config is None:
            response = client.models.generate_content(
                model=model_name,
                contents=audio_input,
            )
        else:
            response = client.models.generate_content(
                model=model_name,
                contents=audio_input,
                config=config,
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
        # TODO: can the response contain multiple function calls?

        return text, function_call

    except Exception as e:
        return False, f'An error occurred:\n{e}'
