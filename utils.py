import numpy as np
import sounddevice as sd


def get_api_key(file_path: str) -> str:
    """
    Reads the API key from a file.

    :param file_path: Path to the file containing the API key.
    :return: The API key as a string.
    """
    try:
        with open(file_path, 'r') as file:
            api_key = file.read().strip()
        return api_key
    except FileNotFoundError:
        raise FileNotFoundError(f'API key file not found: {file_path}')
    except Exception as e:
        raise Exception(f'Error reading API key from file:\n{e}')


def play_audio(audio_data, sample_rate=24000) -> None:
    """
    Plays audio data using the specified sample rate.
    :param audio_data: The audio data to be played, typically in bytes format.
    :param sample_rate: The sample rate of the audio data, default is 24000 Hz.
    """

    # Convert audio data to numpy array
    audio_array = np.frombuffer(audio_data, dtype=np.int16)

    # Play the audio
    sd.play(audio_array, samplerate=sample_rate)
    sd.wait()  # Wait until the audio is finished playing
