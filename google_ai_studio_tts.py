import wave
from google import genai
from google.genai import types

import global_constants as gc


# Set up the wave file to save the output:
def wave_file(filename, pcm, channels=1, rate=24000, sample_width=2):
    with wave.open(filename, mode='wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def text_to_speech(text_input: str,
                   client: genai.Client,
                   model_name: str = 'gemini-2.5-flash-preview-tts',
                   voice_name: str = 'Kore',
                   save_file: bool = False
                   ):
    """
    Generates speech from text using Google AI Studio's TTS model.
    This function sends a text prompt to the TTS model and saves the generated audio to a file.
    """
    response = client.models.generate_content(
        model=model_name,
        contents=text_input,
        config=types.GenerateContentConfig(
            response_modalities=['AUDIO'],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        )
    )
    data = response.candidates[0].content.parts[0].inline_data.data

    if save_file:
        # Use first 10 characters of text as filename
        file_name = f'{gc.DATA_FOLDER_PATH}{text_input[:10].replace(" ", "_")}.wav'
        file_path = gc.DATA_FOLDER_PATH + file_name
        print(f'Saving audio to {file_path}')
        wave_file(file_path, data)  # Saves the file
