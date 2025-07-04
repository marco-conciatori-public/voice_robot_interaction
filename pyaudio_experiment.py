import argparse
from pathlib import Path

import utils
import global_constants as gc


file_audio_list = []

# add all mp3 files in the data folder
for file in Path(gc.OUTPUT_FOLDER_PATH).glob('*.wav'):
    print(file)
    with open(file, 'rb') as audio_file:
        file_audio_list.append(audio_file.read())

# read command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('-o', '--output_device_index', type=int, default=1,)
parser.add_argument('-s', '--sample_rate', type=int, default=24000,)
parser.add_argument('-c', '--channels', type=int, default=1,)
args = parser.parse_args()
output_device_index = args.output_device_index
sample_rate = args.sample_rate
channels = args.channels
print(f'Output device index: {output_device_index}')
print(f'Sample rate: {sample_rate}')
print(f'Channels: {channels}')

# play all audio files
counter = 1
for audio_file in file_audio_list:
    print(f'Playing audio file {counter}/{len(file_audio_list)}')
    utils.play_audio(
        audio_bytes=audio_file,
        # output_device_index=output_device_index,
        sample_rate=sample_rate,
        channels=channels,
        dtype='int16',
    )
    counter += 1

print('All audio files played.')
