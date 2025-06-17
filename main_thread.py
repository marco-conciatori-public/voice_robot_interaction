import time

from google import genai
from google.genai import types

import args
import utils
import google_ai_studio_tts
import google_ai_studio_llm
import function_declarations
import global_constants as gc


if __name__ == '__main__':
    parameters = args.import_args(yaml_path=gc.CONFIG_FILE_PATH)

    # get the API key from a file
    api_key = utils.get_api_key(file_path=parameters['api_key_file_path'])
    client = genai.Client(api_key=api_key)
    model_name = parameters['brain_model_name']
    # model_name = 'gemini-2.0-flash-live-001'
    tools = types.Tool(function_declarations=function_declarations.function_list)
    config = types.GenerateContentConfig(tools=[tools])

    request_queue_fifo = []

    while True:
        if len(request_queue_fifo) == 0:
            time.sleep(0.2)
        else:
            request = request_queue_fifo.pop(0)

            # Send the audio input to the model and get the response
            # audio_file_path = gc.DATA_FOLDER_PATH + 'hello.mp3'
            # audio_file_path = gc.DATA_FOLDER_PATH + 'backward.mp3'
            # audio_file_path = gc.DATA_FOLDER_PATH + 'turn_italian.mp3'
            # with open(audio_file_path, 'rb') as f:
            #     audio_bytes = f.read()
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
                audio_data = google_ai_studio_tts.text_to_speech(
                    text_input=response,
                    client=client,
                    model_name=parameters['tts_model_name'],
                    voice_name=parameters['tts_voice_name'],
                    save_file=parameters['save_audio_file'],
                )

                # play the audio
                utils.play_audio(audio_data=audio_data, sample_rate=24000)
