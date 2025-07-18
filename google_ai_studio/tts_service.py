import time
from pathlib import Path

from google import genai
from google.genai import types

import utils
import global_constants as gc


def text_to_speech(text_input: str,
                   client: genai.Client,
                   model_name: str = 'gemini-2.5-flash-preview-tts',
                   voice_name: str = 'kore',
                   save_file: bool = False,
                   verbose: int = 0
                   ):
    """
    Generates speech from text using Google AI Studio's TTS model.
    This function sends a text prompt to the TTS model and saves the generated audio to a file.
    """
    if verbose >= 3:
        print(f'Generating speech for text:\n\t{text_input}')
    # # add 'Say ' prefix to the text input
    # text_input = f'Say "{text_input}"'
    response = client.models.generate_content(
        model=model_name,
        contents=text_input,
        config=types.GenerateContentConfig(
            response_modalities=['AUDIO'],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name))
            ),
        )
    )
    data = response.candidates[0].content.parts[0].inline_data.data

    if save_file:
        # Ensure the output folder exists
        Path(gc.OUTPUT_FOLDER_PATH).mkdir(parents=True, exist_ok=True)
        # Use the first 10 characters of the text as filename
        file_name = f'{text_input[:10].replace(" ", "_")}.wav'
        file_path = gc.OUTPUT_FOLDER_PATH + file_name
        if verbose >= 3:
            print(f'Saving audio to "{file_path}"')
        utils.save_wave_file(file_path=file_path, byte_data=data, verbose=verbose)  # Saves the file

    return data
