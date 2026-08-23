"""
Tests that the YAML configs still line up with the code and the files they point at.

This is the cheapest suite here and has already earned its place twice. Nothing validates a config
until the moment its value is used, and several of those moments are rare by definition: a clip named
in service_interface.yaml is only opened when a quota runs out, so a file renamed or deleted months
earlier surfaces as the robot silently failing to explain itself, at the one moment it needed to. The
same goes for a YAML key that no longer matches the parameter it feeds.

Nothing here calls an API or opens a device, so it runs anywhere the repository does.
"""

import inspect
import wave
from pathlib import Path

import pytest
import yaml

import global_constants as gc
from google_ai_studio import tts_service
from google_ai_studio.rate_limit_guard import RateLimitGuard
from google_ai_studio.reasoning_service import ReasoningService
from robot_link import endpoints

CONFIG_FOLDER = Path(gc.CONFIG_FOLDER_PATH)
ASSETS_FOLDER = Path(gc.ASSETS_FOLDER_PATH)
CONFIG_FILES = sorted(path.name for path in CONFIG_FOLDER.glob('*.yaml'))

# One client config per link channel, and the endpoint each one is supposed to be talking to.
CHANNEL_PORTS = {
    'ethernet_client.yaml': endpoints.COMMAND_PORT,
    'frame_streamer.yaml': endpoints.ARM_CAMERA_PORT,
    'mic_stream_client.yaml': endpoints.MIC_STREAM_PORT,
    'speaker_client.yaml': endpoints.SPEAKER_PLAYBACK_PORT,
}


def load_config(file_name: str) -> dict:
    with open(CONFIG_FOLDER / file_name) as config_file:
        return yaml.safe_load(config_file)


def accepted_parameters(callable_object) -> set:
    """The keyword arguments `callable_object` will accept, for checking a config block against it."""
    return set(inspect.signature(callable_object).parameters) - {'self'}


class TestProjectPaths:
    """
    global_constants resolves from its own location, so a move or a rename cannot silently misdirect it.

    It used to be a hardcoded '/home/jetson/...' string, which meant every path in the app pointed at a
    folder that only exists on the robot.
    """

    def test_the_project_folder_is_this_checkout(self):
        assert (Path(gc.PROJECT_FOLDER_PATH) / 'main_thread.py').is_file()

    def test_the_config_and_asset_folders_exist(self):
        assert CONFIG_FOLDER.is_dir()
        assert ASSETS_FOLDER.is_dir()

    def test_paths_end_in_a_separator(self):
        # The call sites build on these by concatenation, e.g. gc.CONFIG_FOLDER_PATH + 'x.yaml'.
        for path in (gc.PROJECT_FOLDER_PATH, gc.DATA_FOLDER_PATH, gc.ASSETS_FOLDER_PATH,
                     gc.OUTPUT_FOLDER_PATH, gc.CONFIG_FOLDER_PATH):
            assert path.endswith('/')


class TestEveryConfigFile:
    @pytest.mark.parametrize('file_name', CONFIG_FILES)
    def test_it_parses_into_a_dict(self, file_name):
        assert isinstance(load_config(file_name), dict)

    @pytest.mark.parametrize('file_name', CONFIG_FILES)
    def test_it_sets_a_verbosity(self, file_name):
        # Every component reads parameters['verbose'], and the app runs with no CLI arguments, so the
        # YAML is the only place the default can come from.
        assert 'verbose' in load_config(file_name)


class TestLinkEndpoints:
    """
    The two computers have to agree on where to meet.

    robot_link.endpoints is the canonical copy, shared with the RDK X3 repo as a submodule, and these
    configs restate its values. A drift here is invisible until the robot is assembled and one channel
    silently never connects.
    """

    @pytest.mark.parametrize('file_name', sorted(CHANNEL_PORTS))
    def test_the_host_is_the_rdk_x3(self, file_name):
        assert load_config(file_name)['host'] == endpoints.ROBOT_HOST

    @pytest.mark.parametrize('file_name', sorted(CHANNEL_PORTS))
    def test_the_port_matches_its_channel(self, file_name):
        assert load_config(file_name)['port'] == CHANNEL_PORTS[file_name]

    def test_each_channel_has_its_own_port(self):
        ports = [load_config(file_name)['port'] for file_name in CHANNEL_PORTS]
        assert len(set(ports)) == len(ports)


class TestServiceInterfaceConfig:
    """
    The blocks of service_interface.yaml that are handed straight to a callable as **kwargs.

    Those are the ones where a stale key is a TypeError at startup rather than a quiet default, so it
    is worth knowing before the robot is switched on.
    """

    @pytest.fixture
    def config(self):
        return load_config('service_interface.yaml')

    def test_rate_limit_matches_the_guard_constructor(self, config):
        # 'name' is supplied by the caller, one guard per service, so it is not in the config.
        expected = accepted_parameters(RateLimitGuard.__init__) - {'name'}
        assert set(config['rate_limit']) == expected

    def test_tts_parameters_are_accepted_by_the_tts_call(self, config):
        assert set(config['tts_parameters']) <= accepted_parameters(tts_service.text_to_speech)

    def test_reasoning_parameters_are_accepted_by_the_reasoning_service(self, config):
        assert set(config['reasoning_parameters']) <= accepted_parameters(ReasoningService.__init__)

    def test_the_cooldown_ceiling_is_above_the_default(self, config):
        rate_limit = config['rate_limit']
        assert rate_limit['default_cooldown'] <= rate_limit['max_cooldown']
        assert rate_limit['backoff_factor'] >= 1, 'a factor below 1 would shorten the wait each failure'

    def test_the_step_budget_leaves_room_to_look_and_act(self, config):
        # One step only ever produces an answer or a single action, so a budget of 1 disables the
        # observe-act loop the prompt tells the model to use.
        assert config['max_reasoning_steps'] >= 2


class TestAudioNotices:
    """
    Every pre-recorded clip the robot might need, checked for existence and format.

    These are played by writing their frames straight to the RDK X3, which passes them to ALSA without
    inspecting them, so a clip at the wrong sample rate is not an error anywhere: it just comes out of
    the speakers at the wrong pitch. Re-record any failure here with scripts/create_message_audio.py.
    """

    NOTICES = load_config('service_interface.yaml')['audio_notices']

    def test_every_situation_in_the_code_has_a_clip_configured(self):
        # The keys the services ask _play_notice for. The rate-limit ones are built by RateLimitGuard
        # from its name, the other two are literals in service_interface.py.
        expected = {f'{service}_{situation}'
                    for service in ('tts', 'reasoning')
                    for situation in ('minute_limit', 'day_limit', 'available')}
        expected |= {'reasoning_error', 'task_incomplete'}
        assert set(self.NOTICES) == expected

    @pytest.mark.parametrize('notice_key', sorted(NOTICES))
    def test_the_clip_exists(self, notice_key):
        assert (ASSETS_FOLDER / self.NOTICES[notice_key]).is_file()

    @pytest.mark.parametrize('notice_key', sorted(NOTICES))
    def test_the_clip_is_in_the_format_the_speakers_expect(self, notice_key):
        with wave.open(str(ASSETS_FOLDER / self.NOTICES[notice_key])) as clip:
            actual = (clip.getnchannels(), clip.getsampwidth(), clip.getframerate())
            assert clip.getnframes() > 0, 'the clip is empty'
        assert actual == (1, 2, endpoints.SPEAKER_SAMPLE_RATE)

    @pytest.mark.parametrize('notice_key', sorted(NOTICES))
    def test_the_clip_is_short_enough_to_listen_to(self, notice_key):
        # These interrupt someone who is waiting for an answer, and nothing can cut one short once it
        # has been queued. A clip this long is a sign the wording drifted into an explanation.
        with wave.open(str(ASSETS_FOLDER / self.NOTICES[notice_key])) as clip:
            duration = clip.getnframes() / clip.getframerate()
        assert duration <= 12


class TestCaptureShotPlan:
    """
    The shot plan of scripts/capture_mat_photos.py, which is a config describing a session with real
    cards on a table rather than a set of numbers.

    It is checked here instead of by importing the script, because the script needs OpenCV and the
    development machine does not have it. What is worth checking is the part a person edits: a plan
    that comes back to a layout after moving on from it, or that gives one layout two different pack
    sizes, is asking for cards to be laid out again exactly as they were, which nobody can do. The
    cost of finding that out during the session is the session.
    """

    SHOT_FIELDS = {'layout', 'pack_size', 'headlight_on', 'lighting', 'note'}

    @pytest.fixture
    def config(self):
        return load_config('capture_mat_photos.yaml')

    @pytest.fixture
    def shot_plan(self, config):
        return config['shot_plan']

    def test_every_shot_describes_itself_completely(self, shot_plan):
        for shot in shot_plan:
            assert set(shot) == self.SHOT_FIELDS, shot
            assert isinstance(shot['pack_size'], int) and shot['pack_size'] >= 1
            assert isinstance(shot['headlight_on'], bool), 'YAML reads a bare "off" as False anyway'
            assert shot['lighting'] and shot['note']

    def test_the_shots_of_a_layout_are_consecutive(self, shot_plan):
        # Shots sharing a layout are the same cards left untouched, so coming back to a layout later
        # would mean rebuilding it card for card from the photos already taken.
        seen_layouts = []
        for shot in shot_plan:
            if not seen_layouts or seen_layouts[-1] != shot['layout']:
                assert shot['layout'] not in seen_layouts, f'layout {shot["layout"]} is split up'
                seen_layouts.append(shot['layout'])

    def test_a_layout_holds_one_number_of_cards(self, shot_plan):
        # One layout means one card list file, so two pack sizes under the same number would label
        # some of the photos wrongly.
        for layout in {shot['layout'] for shot in shot_plan}:
            sizes = {shot['pack_size'] for shot in shot_plan if shot['layout'] == layout}
            assert len(sizes) == 1, f'layout {layout} claims {sizes} cards in different shots'

    def test_the_plan_varies_what_it_is_supposed_to_vary(self, shot_plan):
        # The point of the exercise is a spread of conditions, not twenty photographs of one.
        assert len({shot['pack_size'] for shot in shot_plan}) >= 4
        assert len({shot['lighting'] for shot in shot_plan}) >= 2
        assert {shot['headlight_on'] for shot in shot_plan} == {True, False}

    def test_the_session_starts_inside_the_plan(self, config):
        assert 1 <= config['start_at_shot'] <= len(config['shot_plan'])

    def test_the_image_format_is_an_extension_opencv_understands(self, config):
        assert config['image_format'].startswith('.')

    def test_the_mat_has_four_distinct_corner_markers(self, config):
        marker_ids = config['expected_marker_ids']
        assert len(marker_ids) == len(set(marker_ids)) == 4


class TestAimCameraConfig:
    """
    The aiming targets of scripts/aim_camera.py, which have to stay stricter than the session's own.

    The script says READY when nothing in aim_camera.yaml complains, and the capture session then
    warns about the same frame from capture_mat_photos.yaml. Targets that slipped below the session's
    thresholds would produce the one failure worth guarding against here: a green light that is
    followed by twenty warnings, discovered with the cards already on the table.
    """

    OUTPUT_CHOICES = ('auto', 'window', 'http', 'text')

    @pytest.fixture
    def config(self):
        return load_config('aim_camera.yaml')

    @pytest.fixture
    def capture_config(self, config):
        return load_config(Path(config['capture_config']).name)

    def test_it_points_at_a_capture_config_that_exists(self, config):
        # Read at startup and resolved against the project root, so a rename shows up as a crash on
        # the Jetson rather than here, where it is free to find.
        assert (Path(gc.PROJECT_FOLDER_PATH) / config['capture_config']).is_file()

    def test_the_output_is_one_the_script_knows(self, config):
        assert config['output'] in self.OUTPUT_CHOICES

    def test_the_coverage_target_is_above_what_the_session_merely_tolerates(self, config, capture_config):
        assert config['target_mat_coverage'] >= capture_config['min_mat_coverage']

    def test_the_coverage_window_is_a_window(self, config):
        assert config['target_mat_coverage'] < config['max_mat_coverage'] <= 1.0

    def test_the_mat_may_sit_somewhat_off_centre(self, config):
        # Half the frame off centre would mean the mat is barely in the picture at all.
        assert 0.0 < config['centre_tolerance'] < 0.5

    def test_a_shallow_view_is_still_a_view(self, config):
        # 1.0 is straight down, so a threshold at or below it would ask for the impossible.
        assert config['max_scale_ratio'] > 1.0
