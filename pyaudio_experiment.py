from pathlib import Path

import utils
import global_constants as gc


file_audio_list = []

# add all mp3 files in the data folder
for file in Path(gc.DATA_FOLDER_PATH).glob('*.mp3'):
    with open(file, 'rb') as audio_file:
        file_audio_list.append(audio_file.read())

# play all audio files
counter = 0
for audio_data in file_audio_list:
    print(f'Playing audio file {counter + 1}/{len(file_audio_list)}')
    utils.play_audio(
        audio_data=audio_data,
        output_device_index=1,
    )
    counter += 1

print('All audio files played.')
