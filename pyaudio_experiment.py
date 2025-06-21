import argparse
from pathlib import Path

import utils
import global_constants as gc


file_audio_list = []

# add all mp3 files in the data folder
for file in Path(gc.DATA_FOLDER_PATH).glob('*.mp3'):
    with open(file, 'rb') as audio_file:
        file_audio_list.append(audio_file.read())

# read command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('-o', '--output_device_index', type=int, default=1,)
args = parser.parse_args()
output_device_index = args.output_device_index
print(f'Output device index: {output_device_index}')

# play all audio files
counter = 0
for audio_data in file_audio_list:
    print(f'Playing audio file {counter + 1}/{len(file_audio_list)}')
    utils.play_audio(
        audio_data=audio_data,
        output_device_index=output_device_index,
        sample_rate=16000
    )
    counter += 1

print('All audio files played.')
