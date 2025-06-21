import wave
import pyaudio
import numpy as np


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


def play_audio(audio_data, output_device_index: int, channels: int = 1, sample_rate: int = 24000) -> None:
    """
    Plays audio data using the specified sample rate.
    :param audio_data: The audio data to be played, in bytes format.
    :param output_device_index: The index of the output device to use for playback.
    :param channels: The number of audio channels, default is 1 (mono).
    :param sample_rate: The sample rate of the audio data, default is 24000 Hz.
    """
    # # Initialize PyAudio
    # pa = pyaudio.PyAudio()
    #
    # # Open a stream for playback
    # stream = pa.open(
    #     format=pyaudio.paInt16,
    #     # format=pa.get_format_from_width(2),
    #     channels=channels,
    #     rate=sample_rate,
    #     output=True,
    #     output_device_index=output_device_index,
    # )
    #
    # # Convert byte data to numpy array for playback
    # audio_array = np.frombuffer(audio_data, dtype=np.int16)
    #
    # # Play the audio data
    # stream.write(audio_array.tobytes())
    #
    # # Stop and close the stream
    # stream.stop_stream()
    # stream.close()
    #
    # # Terminate PyAudio
    # pa.terminate()

    CHUNK = 1024

    with wave.open(f=audio_data, mode='rb') as wf:
        # Instantiate PyAudio and initialize PortAudio system resources (1)
        p = pyaudio.PyAudio()

        print(f'format: {wf.getsampwidth()}')
        print(f'format: {p.get_format_from_width(wf.getsampwidth())}')
        print(f'channels: {wf.getnchannels()}')
        print(f'rate: {wf.getframerate()}')

        # Open stream (2)
        stream = p.open(
            format=p.get_format_from_width(wf.getsampwidth()),
            channels=wf.getnchannels(),
            rate=wf.getframerate(),
            output=True,
            output_device_index=output_device_index,
        )

        # Play samples from the wave file (3)
        while len(data := wf.readframes(CHUNK)):  # Requires Python 3.8+ for :=
            stream.write(data)

        # Close stream (4)
        stream.close()

        # Release PortAudio system resources (5)
        p.terminate()


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