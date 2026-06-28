import wave
import numpy as np
from pathlib import Path

import global_constants as gc
# pretty_print_dict / print_exception are shared with the RDK X3 via robot_link; re-exported
# here so existing utils.pretty_print_dict(...) / utils.print_exception(...) call sites keep working.
# (This also fixes the old local print_exception, whose message/None branches were inverted.)
from robot_link.common import pretty_print_dict, print_exception


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


def play_audio(audio_bytes: bytes, sample_rate: int, dtype: str, channels: int):
    """
    Plays PCM audio data from a byte string using sounddevice.

    Args:
        audio_bytes: The raw audio data as a bytes object.
        sample_rate: The sample rate of the audio (e.g., 24000 Hz).
        dtype: The data type string (e.g., 'int16' for L16).
        channels: The number of audio channels (e.g., 1 for mono).
    """

    try:
        # Imported lazily so the rest of utils (used by the arm-camera/ethernet path) loads even when the
        # sounddevice library is not installed, which is the case once the speakers move off the Jetson.
        import sounddevice as sd

        # Convert bytes to a numpy array of the specified data type
        # We assume little-endian byte order based on common L16 implementations.
        audio_array = np.frombuffer(audio_bytes, dtype=dtype)

        # Reshape the array if it's stereo (though L16 is usually mono)
        if channels > 1:
            audio_array = audio_array.reshape(-1, channels)

        print(f"Playing audio (Sample Rate: {sample_rate} Hz, DType: {dtype}, Channels: {channels})...")
        # Play the audio. The 'blocking=True' means the function waits until playback finishes.
        sd.play(audio_array, samplerate=sample_rate, blocking=True)
        print("Audio playback finished.")

    except Exception as e:
        print(f"An error occurred during audio playback: {e}")
        print("Please ensure you have 'sounddevice' installed and working audio output.")
        print("You might need to install 'PortAudio' development libraries if on Linux/macOS.")


def save_wave_file(file_path: str, byte_data, channels=1, rate=24000, sample_width=2, verbose: int = 0) -> None:
    # Set up the wave file to save the output:
    with wave.open(file_path, mode='wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(byte_data)
    if verbose >= 1:
        print(f'Saved audio file to "{file_path}"')


def get_yaml_path(caller_name: str) -> str:
    file_name_no_extension = Path(caller_name).resolve().stem
    yaml_path = gc.CONFIG_FOLDER_PATH + file_name_no_extension + '.yaml'
    return yaml_path
