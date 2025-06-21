import numpy as np
import sounddevice as sd
import struct


# --- Configuration for your audio ---
# Mime type: audio/L16;codec=pcm;rate=24000
SAMPLE_RATE = 24000  # Samples per second (Hz)
DTYPE = 'int16'      # Data type for L16 PCM (16-bit signed integers)
CHANNELS = 1         # L16 typically means mono audio

# --- Simulate receiving audio data from gemini-2.5-flash-preview-tts ---
# In a real scenario, you would replace this with the actual audio bytes
# received from the Gemini API.
#
# For demonstration, let's create a simple sine wave as a byte string
# that mimics L16 PCM.
# L16 PCM means 16-bit signed little-endian integers.
# A simple sine wave to test:
duration = 1.0  # seconds
frequency = 440  # Hz (A4 note)
num_samples = int(SAMPLE_RATE * duration)
time_array = np.linspace(0, duration, num_samples, endpoint=False)
amplitude = 32767  # Max value for 16-bit signed integer (2^15 - 1)

# Generate a sine wave, scale it, and convert to int16
sine_wave = (amplitude * np.sin(2 * np.pi * frequency * time_array)).astype(DTYPE)

# Convert the numpy array of int16 to a byte string (little-endian)
# Each int16 value becomes 2 bytes.
# For 'L16' (Linear PCM, 16-bit), it's typically little-endian.
simulated_audio_bytes = b''
for sample in sine_wave:
    simulated_audio_bytes += struct.pack('<h', sample)  # '<h' means little-endian short (2 bytes)

print(f"Simulated audio data length: {len(simulated_audio_bytes)} bytes")
print(f"Simulated audio duration: {duration} seconds")


# --- Function to play PCM audio data ---
def play_pcm_audio(audio_bytes: bytes, samplerate: int, dtype: str, channels: int):
    """
    Plays PCM audio data from a byte string using sounddevice.

    Args:
        audio_bytes: The raw audio data as a bytes object.
        samplerate: The sample rate of the audio (e.g., 24000 Hz).
        dtype: The data type string (e.g., 'int16' for L16).
        channels: The number of audio channels (e.g., 1 for mono).
    """
    if not audio_bytes:
        print("No audio data to play.")
        return

    try:
        # Convert bytes to a numpy array of the specified data type
        # The .frombuffer method is efficient for this.
        # We assume little-endian byte order based on common L16 implementations.
        audio_array = np.frombuffer(audio_bytes, dtype=dtype)

        # Reshape the array if it's stereo (though L16 is usually mono)
        if channels > 1:
            audio_array = audio_array.reshape(-1, channels)

        print(f"Playing audio (Sample Rate: {samplerate} Hz, DType: {dtype}, Channels: {channels})...")
        # Play the audio. The 'blocking=True' means the function waits until playback finishes.
        sd.play(audio_array, samplerate=samplerate, blocking=True)
        print("Audio playback finished.")

    except Exception as e:
        print(f"An error occurred during audio playback: {e}")
        print("Please ensure you have 'sounddevice' installed and working audio output.")
        print("You might need to install 'PortAudio' development libraries if on Linux/macOS.")


# --- Call the function with your simulated data ---
if __name__ == "__main__":
    play_pcm_audio(simulated_audio_bytes, SAMPLE_RATE, DTYPE, CHANNELS)

    # Example of playing an empty data to show the 'no audio data' message
    # play_pcm_audio(b'', SAMPLE_RATE, DTYPE, CHANNELS)
