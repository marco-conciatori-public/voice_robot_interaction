# import numpy as np
# import sounddevice as sd
import wave
#
#
# def get_api_key(file_path: str) -> str:
#     """
#     Reads the API key from a file.
#
#     :param file_path: Path to the file containing the API key.
#     :return: The API key as a string.
#     """
#     try:
#         with open(file_path, 'r') as file:
#             api_key = file.read().strip()
#         return api_key
#     except FileNotFoundError:
#         raise FileNotFoundError(f'API key file not found: {file_path}')
#     except Exception as e:
#         raise Exception(f'Error reading API key from file:\n{e}')
#
#
# def play_audio(audio_data, sample_rate=24000) -> None:
#     """
#     Plays audio data using the specified sample rate.
#     :param audio_data: The audio data to be played, typically in bytes format.
#     :param sample_rate: The sample rate of the audio data, default is 24000 Hz.
#     """
#
#     # Convert audio data to numpy array
#     audio_array = np.frombuffer(audio_data, dtype=np.int16)
#
#     # Play the audio
#     sd.play(audio_array, samplerate=sample_rate)
#     sd.wait()  # Wait until the audio is finished playing


def pretty_print_dict(data, _level: int = 0) -> None:
    if isinstance(data, dict):
        if _level > 0:
            print()
        for key in data:
            for i in range(_level + 1):
                print('\t', end='')
            print(f'{key}: ', end='')
            pretty_print_dict(data[key], _level=_level + 1)
    else:
        print(data)


def save_wave_file(file_path: str, byte_data, channels=1, rate=24000, sample_width=2):
    # Set up the wave file to save the output:
    with wave.open(file_path, mode='wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(byte_data)