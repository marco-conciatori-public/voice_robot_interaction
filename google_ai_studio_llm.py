from google import genai
from google.genai import types


def get_llm_response(model_name: str, model_input, client: genai.Client, config=None) -> tuple:
    """
    Sends a text prompt to the Google AI Studio LLM and returns the response.

    Args:
        model_name: str: The model to use for generating the response.
        model_input: The prompt to send to the LLM, can be text, audio or images.
        client: genai.Client: The Google AI Studio client to use for generating the response.
        config (types.GenerateContentConfig): Configuration for the content generation, including tools.

    Returns:
        tuple: A tuple containing:
            - is_function_call (bool): Indicates if the response is a function call.
            - response: The response from the LLM, which can be either text or a function call with parameters, or an
             error message if an exception occurs.
    """
    try:
        # Send the prompt to the model and get the response.
        if isinstance(model_input, str):
            print(f'Sending prompt to LLM: "{model_input}"...')
        if config is None:
            response = client.models.generate_content(
                model=model_name,
                contents=model_input,
            )
        else:
            response = client.models.generate_content(
                model=model_name,
                contents=model_input,
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
