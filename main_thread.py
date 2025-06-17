import time
import threading

from google import genai
from google.genai import types

import args
import utils
import google_ai_studio_tts
import google_ai_studio_llm
import function_declarations
import global_constants as gc


def llm_worker(request, model_name, client, config, parameters, tts_queue):
    audio_input = [
        parameters['prompt_template'],
        types.Part.from_bytes(data=request['audio_bytes'], mime_type='audio/mp3')
    ]
    is_function_call, response = google_ai_studio_llm.get_llm_response(
        model_name=model_name,
        model_input=audio_input,
        client=client,
        config=config,
    )
    if not is_function_call:
        tts_queue.append(response)
    else:
        # If the response is a function call, execute the function and get the response
        function_name = response.name
        function_args = response.args
        print(f'Executing function: {function_name} with arguments: {function_args}')
        # TODO: Implement the function execution logic here


def tts_worker(response, client, parameters):
    audio_data = google_ai_studio_tts.text_to_speech(
        text_input=response,
        client=client,
        model_name=parameters['tts_model_name'],
        voice_name=parameters['tts_voice_name'],
        save_file=parameters['save_audio_file'],
    )
    utils.play_audio(audio_data=audio_data, sample_rate=24000)


if __name__ == '__main__':
    parameters = args.import_args(yaml_path=gc.CONFIG_FILE_PATH)
    api_key = utils.get_api_key(file_path=parameters['api_key_file_path'])
    client = genai.Client(api_key=api_key)
    model_name = parameters['brain_model_name']
    tools = types.Tool(function_declarations=function_declarations.function_list)
    config = types.GenerateContentConfig(tools=[tools])

    request_queue = []
    tts_queue = []

    audio_file_path = gc.DATA_FOLDER_PATH + 'hello.mp3'
    with open(audio_file_path, 'rb') as audio_file:
        request_queue.append({'audio_bytes': audio_file.read()})
    audio_file_path = gc.DATA_FOLDER_PATH + 'backward.mp3'
    with open(audio_file_path, 'rb') as audio_file:
        request_queue.append({'audio_bytes': audio_file.read()})
    audio_file_path = gc.DATA_FOLDER_PATH + 'turn_italian.mp3'
    with open(audio_file_path, 'rb') as audio_file:
        request_queue.append({'audio_bytes': audio_file.read()})

    while True:
        if len(request_queue) == 0 and len(tts_queue) == 0:
            time.sleep(0.2)
        else:
            if len(request_queue) > 0:
                request = request_queue.pop(0)
                threading.Thread(
                    target=llm_worker,
                    args=(request, model_name, client, config, parameters, tts_queue)
                ).start()
            if len(tts_queue) > 0:
                response = tts_queue.pop(0)
                threading.Thread(
                    target=tts_worker,
                    args=(response, client, parameters)
                ).start()
