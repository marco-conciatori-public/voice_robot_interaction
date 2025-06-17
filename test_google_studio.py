from google import genai
from google.genai import types

import utils
import function_declarations
import global_constants as gc


# get the API key from a file
api_key_file_path = 'gemini_api_key.txt'
api_key = utils.get_api_key(file_path=api_key_file_path)


def get_llm_response(model_name: str, input, config=None) -> tuple:
    """
    Sends a text prompt to the Google AI Studio LLM and returns the response.

    Args:
        model_name: str: The model to use for generating the response.
        input: The prompt to send to the LLM, can be text, audio or images.
        config (types.GenerateContentConfig): Configuration for the content generation, including tools.

    Returns:
        tuple: A tuple containing:
            - is_function_call (bool): Indicates if the response is a function call.
            - response: The response from the LLM, which can be either text or a function call with parameters, or an
             error message if an exception occurs.
    """
    try:
        # Send the prompt to the model and get the response.
        if isinstance(input, str):
            print(f'Sending prompt to LLM: "{input}"...')
        if config is None:
            response = client.models.generate_content(
                model=model_name,
                contents=input,
            )
        else:
            response = client.models.generate_content(
                model=model_name,
                contents=input,
                config=config,
            )

        # Check for a function call
        # returns a tuple (is_function_call, response)
        if response.candidates[0].content.parts[0].function_call:
            function_call = response.candidates[0].content.parts[0].function_call
            print('Function call detected in the response.')
            print(f'Function to call: {function_call.name}')
            print(f'Arguments: {function_call.args}')
            return True, function_call
        else:
            print('No function call detected in the response.')
            print(f'Response: {response.candidates[0].content.parts[0].text}')
            return False, response.text

    except Exception as e:
        return False, f'An error occurred:\n{e}'


if __name__ == '__main__':
    client = genai.Client(api_key=api_key)
    model_name = 'gemini-2.0-flash'
    # model_name = 'gemini-2.0-flash-live-001'
    tools = types.Tool(function_declarations=function_declarations.function_list)
    config = types.GenerateContentConfig(tools=[tools])

    # # Define your text prompt
    # text_input = 'What is the capital of France?'
    # response = get_llm_response(model_name=model_name, input=text_input)
    #
    # text_input = 'Move the robot forward with medium speed.'
    # response = get_llm_response(model_name=model_name, input=text_input, config=config)

    # Send the audio input to the model and get the response
    # audio_file_path = gc.DATA_FOLDER_PATH + 'hello.mp3'
    # audio_file_path = gc.DATA_FOLDER_PATH + 'backward.mp3'
    audio_file_path = gc.DATA_FOLDER_PATH + 'turn_italian.mp3'
    with open(audio_file_path, 'rb') as f:
        audio_bytes = f.read()
    audio_input = [
        'respond with text of call a function as appropriate',
        types.Part.from_bytes(data=audio_bytes, mime_type='audio/mp3')
    ]
    response = get_llm_response(model_name=model_name, input=audio_input, config=config)
