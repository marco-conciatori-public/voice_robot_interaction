"""
Record one spoken message into assets/, in the same Gemini voice the robot speaks with.

Development-machine helper, not robot code: the Jetson only ever *plays* these files (see
GoogleAIStudioService._play_rate_limit_notice), it never creates them. Nothing here is imported by
main_thread.py, and it is the only script in the repo that is expected to run off the robot.

Two things make the result usable by the robot rather than merely correct-sounding:

  - The model and voice are read from the robot's own configs/service_interface.yaml
    ('tts_parameters'), and the call goes through the same google_ai_studio.tts_service function the
    robot uses, so a recording cannot drift from what the robot itself would have said.
  - The file is written as mono 16 bit at robot_link.endpoints.SPEAKER_SAMPLE_RATE and re-opened
    afterwards to confirm it. The playback path does not tolerate anything else: the Jetson strips
    the WAV header and streams the frames to the RDK X3, which writes them straight to ALSA without
    inspecting them, so a wrong sample rate would show up as noise from the robot rather than as an
    error at playback time.

Run it from the IDE with no arguments (everything comes from configs/create_message_audio.yaml), or
override single values on the command line:

    python scripts/create_message_audio.py --text "Battery low." --output_file_name battery_low.wav
"""

import sys
import wave
from pathlib import Path


def find_project_root() -> Path:
    """
    The repository root, found by walking up from this file until a project marker appears.

    Deliberately not global_constants.PROJECT_FOLDER_PATH: that is the absolute path the code lives at
    on the robot ('/home/jetson/GIT/voice_robot_interaction/'), which does not exist on the machine
    this script runs on. Walking up from __file__ also means the script behaves the same whether the
    IDE launches it with the working directory at the project root or at scripts/.
    """
    start = Path(__file__).resolve().parent
    for candidate in [start, *start.parents]:
        if (candidate / 'main_thread.py').is_file():
            return candidate
    raise RuntimeError(f'Could not find the project root in any folder above "{start}".')


PROJECT_ROOT = find_project_root()
# The project modules below are imported as top-level names ('import args'), which only resolves when
# the project root is on the path. Python adds the *script's* folder (scripts/), not the root, so it
# has to be added here, before those imports.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from google import genai  # noqa: E402

import args  # noqa: E402
import utils  # noqa: E402
from robot_link import endpoints  # noqa: E402
from google_ai_studio import tts_service  # noqa: E402


def create_message_audio(**kwargs) -> Path:
    """
    Synthesise the configured text and write it to assets/, returning the path of the new file.

    Keyword arguments override the YAML config, which in turn overrides nothing else: running with no
    arguments at all is the normal case.
    """
    parameters = args.import_args(
        yaml_path=str(PROJECT_ROOT / 'configs' / 'create_message_audio.yaml'),
        read_from_command_line=True,
        **kwargs,
    )
    verbose = parameters['verbose']

    text = parameters['text']
    if not text or not text.strip():
        raise ValueError('No text to record. Set "text" in configs/create_message_audio.yaml, '
                         'or pass --text "...".')

    output_file_name = parameters['output_file_name']
    if not output_file_name.lower().endswith('.wav'):
        raise ValueError(f'output_file_name must end in .wav, got "{output_file_name}".')
    output_path = PROJECT_ROOT / 'assets' / output_file_name
    if output_path.exists() and not parameters['overwrite']:
        raise FileExistsError(f'"{output_path}" already exists. Choose another output_file_name, or set '
                              f'"overwrite: True" in configs/create_message_audio.yaml to replace it.')

    # Read the robot's own TTS settings so this recording matches its live voice.
    tts_config_path = PROJECT_ROOT / parameters['tts_config_file']
    tts_parameters = args.import_args(yaml_path=str(tts_config_path))['tts_parameters']
    model_name = tts_parameters['model_name']
    voice_name = tts_parameters['voice_name']

    api_key_path = PROJECT_ROOT / parameters['api_key_file']
    client = genai.Client(api_key=utils.get_api_key(file_path=str(api_key_path)))

    if verbose >= 2:
        print(f'Recording with model "{model_name}", voice "{voice_name}":\n\t{text}')
    # save_file is forced off: tts_service would write into the robot's absolute output folder, while
    # this script writes to assets/ under the resolved project root.
    pcm_bytes = tts_service.text_to_speech(
        text_input=text,
        client=client,
        model_name=model_name,
        voice_name=voice_name,
        save_file=False,
        verbose=verbose,
    )
    if not pcm_bytes:
        raise RuntimeError('The TTS model returned no audio.')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    utils.save_wave_file(
        file_path=str(output_path),
        byte_data=pcm_bytes,
        channels=1,
        rate=endpoints.SPEAKER_SAMPLE_RATE,
        sample_width=2,
        verbose=0,
    )

    duration = verify_playable(file_path=output_path)
    if verbose >= 1:
        print(f'Saved "{output_path}" ({duration:.2f} s, {endpoints.SPEAKER_SAMPLE_RATE} Hz mono 16 bit).')
        print('Listen to it before committing, then point the relevant config entry at the file name.')
    return output_path


def verify_playable(file_path: Path) -> float:
    """
    Re-open the written file and confirm the robot will accept it, returning its duration in seconds.

    Cheap insurance against a silent mistake: nothing downstream validates the audio until it is
    already coming out of the speakers, so a format problem is much better caught here.
    """
    with wave.open(str(file_path), mode='rb') as recording:
        channels = recording.getnchannels()
        sample_width = recording.getsampwidth()
        frame_rate = recording.getframerate()
        frame_count = recording.getnframes()

    expected = (1, 2, endpoints.SPEAKER_SAMPLE_RATE)
    if (channels, sample_width, frame_rate) != expected:
        raise ValueError(f'"{file_path}" came out as {frame_rate} Hz, {channels} channel(s), '
                         f'{sample_width * 8} bit, but the robot speakers need '
                         f'{endpoints.SPEAKER_SAMPLE_RATE} Hz mono 16 bit.')
    if frame_count == 0:
        raise ValueError(f'"{file_path}" contains no audio.')
    return frame_count / frame_rate


if __name__ == '__main__':
    create_message_audio()
