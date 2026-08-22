"""
Capture the arm camera photographs of real card packs on the printed ArUco mat.

This is the data collection session for task 0.7 of the MTG cube draft project (the sibling repo
`mtg_cube_draft`, docs/PLAN.md): about twenty photographs of packs laid out on the mat, varying pack
size, lighting and headlight, each one labelled with the cards it contains. Those photographs are
the reference set that every threshold in the recognition pipeline is tuned against, so they are
worth taking carefully once rather than quickly twice.

It runs on the Jetson because the arm camera is attached here, and it is the deployment condition:
a phone photograph would answer a different question. Nothing in it touches the robot, the arm or
the link to the RDK X3, so it is safe to run over a remote session with the rest of the robot off.
Point the camera at the mat by hand (or park the arm) before starting.

Three things it does beyond taking a picture, each because the alternative is discovering a problem
after the cards are back in the box:

  - It **measures every shot as it is taken**: the four mat markers, the pixels per millimetre
    actually landing on the mat, how much of the frame the mat fills, focus, brightness and
    blown-out glare. A mat with a corner outside the frame is a photo the detector can never use,
    and that is worth knowing while the pack is still on the table.
  - It **groups shots by layout**. Shots that share a `layout` number are the same cards, physically
    untouched, photographed under different light, so the card list is typed once per layout rather
    than once per photo. That list goes in `layout_NN.cards.txt`, one card name per line in the cube
    list's English spelling, with anything after a `#` kept as a note about that card. The test
    harness (task 0.9) reads it next to `session.json`.
  - It **records what the camera actually did**: the resolution really negotiated, the codec, the
    backend, and optionally every mode the camera claims. This is the open question of the whole
    exercise rather than a detail. The arm camera is a 0.3 MP 110-degree module, so 640x480 is the
    sensor and not a setting, which is at best 1.5 px/mm over the 420 mm mat against the ~4.6 px/mm
    the recognition design assumed from a 1080p camera. Whether that is survivable is decided by the
    px/mm each shot reports, measured against the known 378 mm between the mat's marker centres.

Run it with no arguments, from the IDE or the terminal; everything comes from
`configs/capture_mat_photos.yaml`. There is deliberately no command line interface.

`main_thread.py` must not be running: it holds the camera open, and the second opener of a V4L2
device gets an error or black frames.
"""

import os
import sys
import json
import time
import socket
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence


def find_project_root() -> Path:
    """
    The repository root, found by walking up from this file until a project marker appears.

    global_constants knows this already, but it cannot answer the question yet: importing it is
    exactly what needs the root on sys.path. So the root is found once here for the bootstrap below.

    Walking up from __file__ also means the script behaves the same whether the IDE launches it with
    the working directory at the project root or at scripts/.
    """
    start = Path(__file__).resolve().parent
    for candidate in [start, *start.parents]:
        if (candidate / 'main_thread.py').is_file():
            return candidate
    raise RuntimeError('Could not find the project root in any folder above "{}".'.format(start))


PROJECT_ROOT = find_project_root()
# The project modules below are imported as top-level names ('import args'), which only resolves when
# the project root is on the path. Python adds the *script's* folder (scripts/), not the root.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import args  # noqa: E402
import utils  # noqa: E402

WINDOW_NAME = 'mat capture'
SESSION_FILE_NAME = 'session.json'
# Bumped only when the shape of session.json changes in a way the test harness has to know about.
SESSION_FORMAT_VERSION = 1

# Camera controls that are only applied when the config gives them a value. Order matters: a camera
# ignores a manual focus or exposure while the matching automatic mode is still on.
OPTIONAL_CAMERA_CONTROLS = (
    ('autofocus', 'CAP_PROP_AUTOFOCUS'),
    ('focus', 'CAP_PROP_FOCUS'),
    ('auto_exposure', 'CAP_PROP_AUTO_EXPOSURE'),
    ('exposure', 'CAP_PROP_EXPOSURE'),
    ('brightness', 'CAP_PROP_BRIGHTNESS'),
    ('contrast', 'CAP_PROP_CONTRAST'),
    ('saturation', 'CAP_PROP_SATURATION'),
    ('gain', 'CAP_PROP_GAIN'),
)


def capture_mat_photos(**kwargs) -> Path:
    """
    Run one capture session, returning the folder the photographs were written to.

    Keyword arguments override the YAML config. Running with none at all is the normal case.
    """
    parameters = args.import_args(
        yaml_path=str(PROJECT_ROOT / 'configs' / 'capture_mat_photos.yaml'),
        **kwargs,
    )
    verbose = parameters['verbose']
    if not str(parameters['image_format']).startswith('.'):
        raise ValueError('"image_format" is an OpenCV extension and has to start with a dot, for example '
                         '".png". Got "{}".'.format(parameters['image_format']))
    shot_plan = expand_shot_plan(parameters=parameters)
    session_folder = prepare_session_folder(parameters=parameters)

    video = open_camera(parameters=parameters)
    try:
        camera_information = describe_camera(video=video, parameters=parameters)
        report_camera(camera_information=camera_information, parameters=parameters)
        settle_camera(video=video, seconds=parameters['settle_seconds'], verbose=verbose)

        detect_markers = None
        if parameters['check_markers']:
            detect_markers = make_marker_detector(dictionary_name=parameters['aruco_dictionary'])
            if detect_markers is None:
                print('WARNING: this OpenCV build has no working cv2.aruco, so the mat markers cannot be '
                      'checked. Photos are still usable, but frame them generously: a marker outside the '
                      'frame will only show up on the PC. (cv2.aruco needs the contrib build.)')

        use_preview = decide_preview(parameters=parameters)
        run = {
            'started_at': datetime.now().isoformat(timespec='seconds'),
            'hostname': socket.gethostname(),
            'python_version': sys.version.split()[0],
            'opencv_version': cv2.__version__,
            'camera': camera_information,
            'markers_checked': detect_markers is not None,
            'aruco_dictionary': parameters['aruco_dictionary'],
            'expected_marker_ids': list(parameters['expected_marker_ids']),
            'photos': [],
        }
        session = load_or_create_session(session_folder=session_folder, parameters=parameters)
        session['runs'].append(run)

        print_session_instructions(session_folder=session_folder, shot_plan=shot_plan, use_preview=use_preview)
        run_shots(
            video=video,
            shot_plan=shot_plan,
            session=session,
            run=run,
            session_folder=session_folder,
            detect_markers=detect_markers,
            use_preview=use_preview,
            parameters=parameters,
        )
    finally:
        video.release()
        close_preview_window()

    print_summary(session_folder=session_folder, run=run, parameters=parameters)
    return session_folder


# --- the shot plan -----------------------------------------------------------------------------

def expand_shot_plan(parameters: dict) -> List[dict]:
    """
    Normalize the configured shot plan into a list of complete shot dictionaries.

    Every field is given a default here rather than at the point of use, so a hand-written shot with
    only a pack_size in it still produces a full metadata record.
    """
    configured = parameters['shot_plan']
    if not isinstance(configured, list) or len(configured) == 0:
        raise ValueError('"shot_plan" in configs/capture_mat_photos.yaml is empty. It has to list at '
                         'least one shot.')

    shot_plan = []
    for position, entry in enumerate(configured, start=1):
        if not isinstance(entry, dict):
            raise ValueError('Shot {} of "shot_plan" is not a mapping: {!r}'.format(position, entry))
        shot_plan.append({
            'index': position,
            'layout': int(entry.get('layout', position)),
            'pack_size': entry.get('pack_size'),
            'headlight_on': bool(entry.get('headlight_on', False)),
            'lighting': str(entry.get('lighting', 'unspecified')),
            'note': str(entry.get('note', '')),
        })

    start_at_shot = int(parameters['start_at_shot'])
    if not 1 <= start_at_shot <= len(shot_plan):
        raise ValueError('"start_at_shot" is {}, but the plan has {} shots.'
                         .format(start_at_shot, len(shot_plan)))
    return shot_plan[start_at_shot - 1:]


# --- the camera --------------------------------------------------------------------------------

def open_camera(parameters: dict):
    """Open the arm camera and configure it, or explain why it could not be opened."""
    video_id = parameters['video_id']
    # Which backend opens the device decides whether the settings below do anything at all: only the
    # V4L2 backend really applies FOURCC and frame size to a UVC camera, and a vendor OpenCV build
    # can pick GStreamer instead, where every set() succeeds and changes nothing.
    backend_name = parameters['capture_backend']
    if backend_name:
        backend_id = getattr(cv2, backend_name, None)
        if backend_id is None:
            raise ValueError('This OpenCV has no capture backend called "{}". Leave "capture_backend" '
                             'null to let OpenCV choose.'.format(backend_name))
        video = cv2.VideoCapture(video_id, backend_id)
    else:
        video = cv2.VideoCapture(video_id)
    if not video.isOpened():
        raise RuntimeError(
            'Could not open camera {}. The usual causes, in order of likelihood: main_thread.py is '
            'already running and holding the device, the camera is on a different index (try 1, or '
            'check "ls /dev/video*"), or the USB cable came loose.'.format(video_id))

    # The codec is set first, before probing and before the resolution: on most UVC cameras the full
    # sensor resolution is only offered in MJPG, and asking for it while still in raw YUYV silently
    # gets a smaller frame. Probing in the wrong codec would report the camera as less capable than
    # it is, which is the opposite of what the probe is for.
    fourcc = parameters['fourcc']
    if fourcc:
        video.set(cv2.CAP_PROP_FOURCC, fourcc_code(name=fourcc))

    if parameters['probe_camera_modes']:
        probe_camera_modes(video=video, resolutions=parameters['probe_resolutions'])

    video.set(cv2.CAP_PROP_FRAME_WIDTH, int(parameters['width']))
    video.set(cv2.CAP_PROP_FRAME_HEIGHT, int(parameters['height']))
    video.set(cv2.CAP_PROP_FPS, int(parameters['frame_rate']))
    # A shallow queue means the frame that arrives after a pause is closer to the present. Not every
    # backend honours it, which is why frames are also flushed before each capture.
    video.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    apply_optional_controls(video=video, parameters=parameters)
    return video


def fourcc_code(name: str) -> int:
    """The integer FOURCC for a four-character codec name, across OpenCV versions."""
    if len(name) != 4:
        raise ValueError('A FOURCC is exactly four characters, got "{}".'.format(name))
    # cv2.VideoWriter_fourcc is the name every version has; cv2.VideoWriter.fourcc is the newer one.
    make_code = getattr(cv2, 'VideoWriter_fourcc', None)
    if make_code is None:
        make_code = cv2.VideoWriter.fourcc
    return make_code(*name)


def apply_optional_controls(video, parameters: dict) -> None:
    """Apply the camera controls the config actually sets, leaving the rest to the driver."""
    for key, property_name in OPTIONAL_CAMERA_CONTROLS:
        value = parameters.get(key)
        if value is None:
            continue
        property_id = getattr(cv2, property_name, None)
        if property_id is None:
            print('WARNING: this OpenCV has no {}, so "{}" was ignored.'.format(property_name, key))
            continue
        if not video.set(property_id, float(value)):
            print('WARNING: the camera refused {} = {}.'.format(key, value))


def probe_camera_modes(video, resolutions: Sequence) -> List[dict]:
    """
    Ask the camera for each listed resolution and report the frame size it really produced.

    Cameras do not fail when asked for a mode they do not have, they quietly give the nearest one
    they do, so the only honest test is to take a frame and look at its shape.
    """
    print('Probing camera modes (set "probe_camera_modes: false" once you know the answer):')
    probed = []
    for requested in resolutions:
        width, height = int(requested[0]), int(requested[1])
        video.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        video.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        success, frame = video.read()
        actual = [int(frame.shape[1]), int(frame.shape[0])] if success and frame is not None else None
        probed.append({'requested': [width, height], 'actual': actual})
        if actual is None:
            print('    {:>5} x {:<5}  no frame'.format(width, height))
        elif actual == [width, height]:
            print('    {:>5} x {:<5}  supported'.format(width, height))
        else:
            print('    {:>5} x {:<5}  gave {} x {} instead'.format(width, height, actual[0], actual[1]))
    return probed


def describe_camera(video, parameters: dict) -> dict:
    """What the camera ended up configured as, which is not always what was asked for."""
    fourcc_value = int(video.get(cv2.CAP_PROP_FOURCC))
    return {
        'video_id': parameters['video_id'],
        'backend': video.getBackendName() if hasattr(video, 'getBackendName') else 'unknown',
        'requested_resolution': [int(parameters['width']), int(parameters['height'])],
        'actual_resolution': [int(video.get(cv2.CAP_PROP_FRAME_WIDTH)),
                              int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))],
        'requested_fourcc': parameters['fourcc'],
        'actual_fourcc': decode_fourcc(value=fourcc_value),
        'frames_per_second': float(video.get(cv2.CAP_PROP_FPS)),
        'controls_set': {key: parameters.get(key) for key, _ in OPTIONAL_CAMERA_CONTROLS
                         if parameters.get(key) is not None},
    }


def decode_fourcc(value: int) -> str:
    """The four-character codec name behind the integer OpenCV reports."""
    return ''.join(chr((value >> shift) & 0xFF) for shift in (0, 8, 16, 24)).strip()


def report_camera(camera_information: dict, parameters: dict) -> None:
    """Print the negotiated camera mode, with the millimetre resolution it implies over the mat."""
    actual = camera_information['actual_resolution']
    requested = camera_information['requested_resolution']
    print('Camera {}: {} x {} @ {:.0f} fps, codec {}, {} backend'.format(
        camera_information['video_id'], actual[0], actual[1],
        camera_information['frames_per_second'], camera_information['actual_fourcc'],
        camera_information['backend']))
    if actual != requested:
        print('WARNING: asked for {} x {} and got {} x {}. Run once with "probe_camera_modes: true" to '
              'see what this camera really offers, and if every mode comes back the same, try '
              '"capture_backend: CAP_V4L2".'.format(requested[0], requested[1], actual[0], actual[1]))
    # The ceiling this sensor puts on the whole approach, before any lens or geometry is considered.
    # It is the best case by definition: it assumes the 420 mm mat fills the frame edge to edge, which
    # a camera parked far enough away to see the whole mat comfortably will not manage.
    pixels_per_millimetre = actual[0] / 420.0
    print('Ceiling: {:.1f} px/mm across the A3 mat if it filled the frame edge to edge, putting a card '
          'art box at about {:.0f} px wide. Every shot reports what was really achieved.'
          .format(pixels_per_millimetre, pixels_per_millimetre * 52))
    if parameters['verbose'] >= 2 and camera_information['controls_set']:
        print('Camera controls set from the config: {}'.format(camera_information['controls_set']))


def settle_camera(video, seconds: float, verbose: int) -> None:
    """
    Read frames for a moment before the first shot so auto exposure and white balance converge.

    The first frames out of a UVC camera are dark, green, or both. Without this the first photo of
    the session is systematically worse than the rest, which is exactly the one used to judge the
    framing.
    """
    if verbose >= 2:
        print('Letting the camera settle for {:.1f} s...'.format(seconds))
    deadline = time.time() + max(0.0, float(seconds))
    while time.time() < deadline:
        video.read()


def grab_fresh_frame(video, flush_frames: int):
    """
    Take a frame that shows the table as it is now, not as it was when the queue filled up.

    grab() decodes nothing, so throwing away the queued frames costs little; read() then returns the
    first frame captured after the flush.
    """
    for _ in range(max(0, int(flush_frames))):
        video.grab()
    success, frame = video.read()
    if not success or frame is None:
        raise RuntimeError('The camera stopped returning frames. Check the USB cable and start again.')
    return frame


# --- measuring a shot --------------------------------------------------------------------------

def make_marker_detector(dictionary_name: str) -> Optional[Callable]:
    """
    A `detect(image) -> (corners, ids, rejected)` callable, or None if this OpenCV cannot do it.

    Two APIs have to be covered, and which one is present is a property of the board rather than of
    the code: OpenCV 4.7 replaced the module-level `detectMarkers` with an `ArucoDetector` object,
    and Ubuntu 20.04 still ships 4.2. Both are wrapped behind the same call so the caller never has
    to care. cv2.aruco itself only exists in the contrib build, hence the None.
    """
    aruco = getattr(cv2, 'aruco', None)
    if aruco is None:
        return None
    dictionary_id = getattr(aruco, dictionary_name, None)
    if dictionary_id is None:
        raise ValueError('cv2.aruco has no dictionary "{}". It has to match the mat, which was printed '
                         'from configs/mat_geometry.toml in the mtg_cube_draft repo.'
                         .format(dictionary_name))

    try:
        if hasattr(aruco, 'ArucoDetector'):
            dictionary = aruco.getPredefinedDictionary(dictionary_id)
            detector = aruco.ArucoDetector(dictionary, aruco.DetectorParameters())
            return detector.detectMarkers
        dictionary = aruco.Dictionary_get(dictionary_id)
        detector_parameters = aruco.DetectorParameters_create()

        def detect(image):
            return aruco.detectMarkers(image, dictionary, parameters=detector_parameters)

        return detect
    except Exception as exception:
        utils.print_exception(exception=exception, message='cv2.aruco is present but unusable')
        return None


def find_marker_centres(image, detect_markers: Callable) -> Dict[int, np.ndarray]:
    """Marker id to the centre of its four corners, in pixels."""
    corners, ids, _ = detect_markers(image)
    centres = {}
    if ids is not None:
        for marker_corners, marker_id in zip(corners, np.asarray(ids).flatten()):
            centres[int(marker_id)] = np.asarray(marker_corners, dtype=np.float32).reshape(4, 2).mean(axis=0)
    return centres


def inspect_frame(frame, detect_markers: Optional[Callable], expected_marker_ids: Sequence,
                  marker_centre_spacing_mm: float) -> dict:
    """
    Measure the things about a shot that decide whether it is usable, before the cards are moved.

    Brightness and glare are measured **inside the four markers** whenever the mat is found, and only
    over the whole frame as a fallback. That is not fussiness: the mat is printed on white paper and
    usually sits on a lit table, so a whole-frame measurement is dominated by paper and tabletop that
    no card is ever on, and every single shot would be reported as blown out. The recorded
    'measured_on' says which of the two happened, because the numbers are not comparable between them.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    measurements = {
        'width': int(width),
        'height': int(height),
        'markers_found': None,
        'mat_coverage': None,
        'pixels_per_millimetre_min': None,
        'pixels_per_millimetre_max': None,
        'measured_on': 'frame',
    }

    mat_quadrilateral = None
    if detect_markers is not None:
        centres = find_marker_centres(image=gray, detect_markers=detect_markers)
        measurements['markers_found'] = sorted(centres)
        expected = [int(marker_id) for marker_id in expected_marker_ids]
        if all(marker_id in centres for marker_id in expected):
            # The expected ids are listed in the order they go round the mat, so joining the centres
            # in that order gives the mat quadrilateral rather than a bowtie.
            mat_quadrilateral = np.array([centres[marker_id] for marker_id in expected], dtype=np.float32)
            covered = abs(cv2.contourArea(mat_quadrilateral))
            measurements['mat_coverage'] = round(covered / float(width * height), 3)

            # Pixels per millimetre ON THE MAT, which is the number that decides whether a card can
            # be recognised at all, and the only one that survives the camera being moved. The two
            # marker pairs that run across the mat give it directly: their real separation is known,
            # their pixel separation is measured. They differ under perspective, the near edge coming
            # out larger, so both are kept: the smaller one is the resolution the worst-placed card
            # on the mat actually gets.
            spacing = float(marker_centre_spacing_mm)
            near_and_far = sorted([
                float(np.linalg.norm(centres[expected[1]] - centres[expected[0]])) / spacing,
                float(np.linalg.norm(centres[expected[2]] - centres[expected[3]])) / spacing,
            ])
            measurements['pixels_per_millimetre_min'] = round(near_and_far[0], 2)
            measurements['pixels_per_millimetre_max'] = round(near_and_far[1], 2)

    if mat_quadrilateral is not None:
        measurements['measured_on'] = 'mat'
        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.fillConvexPoly(mask, mat_quadrilateral.astype(np.int32), 255)
        values = gray[mask > 0]
        left, top, box_width, box_height = cv2.boundingRect(mat_quadrilateral.astype(np.int32))
        focus_region = gray[max(0, top):top + box_height, max(0, left):left + box_width]
    else:
        values = gray.reshape(-1)
        focus_region = gray

    # Variance of the Laplacian: the standard cheap focus measure. Higher is sharper, and the scale
    # is camera specific, so it is only meaningful next to the other shots of the same session.
    measurements['sharpness'] = round(float(cv2.Laplacian(focus_region, cv2.CV_64F).var()), 1)
    measurements['mean_brightness'] = round(float(values.mean()), 1)
    # Pixels at or near pure white: sleeve glare, the one defect no later processing can undo. The
    # mat's own white marker patches sit inside the quadrilateral and contribute a percent or two.
    measurements['clipped_fraction'] = round(float(np.count_nonzero(values >= 250)) / float(values.size), 4)
    return measurements


def warnings_for(measurements: dict, parameters: dict) -> List[str]:
    """Everything about this shot worth a second look, in the order it matters."""
    warnings = []
    expected = [int(marker_id) for marker_id in parameters['expected_marker_ids']]
    found = measurements['markers_found']
    if found is not None:
        missing = [marker_id for marker_id in expected if marker_id not in found]
        if missing:
            warnings.append('markers {} not found: a mat corner is outside the frame, hidden by a card '
                            'or a hand, or too blurred to read'.format(missing))
    coverage = measurements['mat_coverage']
    if coverage is not None and coverage < parameters['min_mat_coverage']:
        warnings.append('the mat fills only {:.0%} of the frame, so most of the sensor is looking at the '
                        'table: move the camera closer or zoom the framing in'.format(coverage))
    scale = measurements['pixels_per_millimetre_min']
    if scale is not None and scale < parameters['min_pixels_per_millimetre']:
        # A card art box is about 52 mm wide, and it is the whole input to the hash.
        warnings.append('only {:.2f} px/mm on the far side of the mat, which puts a card art box at '
                        'about {:.0f} px wide: the camera has to get closer, or the mat has to be '
                        'photographed in more than one shot'.format(scale, scale * 52))
    if measurements['sharpness'] < parameters['min_sharpness']:
        warnings.append('low sharpness ({:.0f}): out of focus, or the arm was still moving'
                        .format(measurements['sharpness']))
    where = 'the mat' if measurements['measured_on'] == 'mat' else 'the frame'
    if measurements['clipped_fraction'] > parameters['max_clipped_fraction']:
        warnings.append('{:.1%} of {} is blown out: that is sleeve glare, and no amount of later '
                        'processing recovers it'.format(measurements['clipped_fraction'], where))
    if measurements['mean_brightness'] < parameters['min_mean_brightness']:
        warnings.append('very dark: {} averages {:.0f}/255'
                        .format(where, measurements['mean_brightness']))
    return warnings


def describe_measurements(measurements: dict) -> str:
    """One line of numbers to print under a shot."""
    parts = ['{}x{}'.format(measurements['width'], measurements['height']),
             'sharpness {:.0f}'.format(measurements['sharpness']),
             'brightness {:.0f}'.format(measurements['mean_brightness']),
             'clipped {:.1%}'.format(measurements['clipped_fraction'])]
    if measurements['markers_found'] is not None:
        parts.append('markers {}'.format(measurements['markers_found']))
    if measurements['mat_coverage'] is not None:
        parts.append('mat {:.0%} of frame'.format(measurements['mat_coverage']))
    if measurements['pixels_per_millimetre_min'] is not None:
        parts.append('{:.2f} to {:.2f} px/mm on the mat'.format(measurements['pixels_per_millimetre_min'],
                                                                measurements['pixels_per_millimetre_max']))
    parts.append('measured on the {}'.format(measurements['measured_on']))
    return ', '.join(parts)


# --- the session on disk -----------------------------------------------------------------------

def prepare_session_folder(parameters: dict) -> Path:
    """The folder this session writes into, created if needed. Relative paths hang off the root."""
    output_folder = Path(parameters['output_folder'])
    if not output_folder.is_absolute():
        output_folder = PROJECT_ROOT / output_folder
    session_name = parameters['session_name']
    if not session_name:
        session_name = 'mat_photos_' + datetime.now().strftime('%Y%m%d_%H%M%S')
    session_folder = output_folder / str(session_name)
    session_folder.mkdir(parents=True, exist_ok=True)
    return session_folder


def load_or_create_session(session_folder: Path, parameters: dict) -> dict:
    """
    The session record, read back if this folder already holds one.

    Photographs are grouped into runs rather than one flat list because a session can be continued:
    naming an existing session in the config adds to it, and the camera settings of the earlier run
    are part of what its photos mean, so they cannot be overwritten by the settings of this one.
    """
    session_path = session_folder / SESSION_FILE_NAME
    if session_path.is_file():
        with open(str(session_path)) as session_file:
            session = json.load(session_file)
        session.setdefault('runs', [])
        return session
    return {
        'format': 'mtg_cube_draft mat capture session',
        'format_version': SESSION_FORMAT_VERSION,
        'session': session_folder.name,
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'mat': {
            'aruco_dictionary': parameters['aruco_dictionary'],
            'expected_marker_ids': list(parameters['expected_marker_ids']),
        },
        'runs': [],
    }


def write_session(session_folder: Path, session: dict) -> None:
    """Rewrite session.json. Called after every photo, so an interrupted session keeps its work."""
    with open(str(session_folder / SESSION_FILE_NAME), 'w') as session_file:
        json.dump(session, session_file, indent=2, sort_keys=False)
        session_file.write('\n')


def next_photo_index(session_folder: Path) -> int:
    """One past the highest photo number already in the folder, so a resumed session never overwrites."""
    highest = 0
    for existing in session_folder.glob('photo_*.*'):
        digits = existing.stem[len('photo_'):]
        if digits.isdigit():
            highest = max(highest, int(digits))
    return highest + 1


def cards_file_name(layout: int) -> str:
    return 'layout_{:02d}.cards.txt'.format(int(layout))


def card_name_from_line(line: str) -> str:
    """
    The card name in one line of a layout file, or '' when the line holds no name.

    Everything from the first '#' onwards is a note for whoever reads the labels later, not part of
    the name: no Magic card name contains '#', and a note belongs on the same line as the card it
    describes ("Preordain  # Italian M11 printing"). The name has to come out clean because the test
    harness looks it up in the cube list, where a name it cannot find is indistinguishable from a
    card the recognition got wrong.
    """
    return line.split('#', 1)[0].strip()


def write_cards_file(session_folder: Path, session_name: str, layout: int, pack_size, photo_names: List[str]) -> Path:
    """
    Create or refresh the card list for one layout, keeping anything already typed into it.

    This is the labelling half of task 0.7 and the only part a human has to supply. It is a plain
    text file rather than a field in session.json because it is meant to be typed into: fifteen card
    names, one per line, with no quoting, no commas and no chance of breaking the metadata file that
    sits next to it. The header is rewritten as photos are added; only the comment lines are touched.
    """
    path = session_folder / cards_file_name(layout=layout)
    # The whole line is kept, note and all, rather than just the name the parser pulls out of it:
    # this file is rewritten after every shot of the layout, so anything dropped here is lost the
    # next time the shutter fires, which is exactly when nobody is looking at the file.
    existing_lines = []
    if path.is_file():
        with open(str(path)) as cards_file:
            for line in cards_file:
                if card_name_from_line(line):
                    existing_lines.append(line.rstrip())

    header = [
        '# Card names for layout {} of session {}.'.format(layout, session_name),
        '#',
        '# One name per line, in any order, spelled the way the cube list spells it, which is the',
        '# ENGLISH name even when the card in front of you is not: that is what the hash database is',
        '# keyed on. Split and double-faced cards keep the full name, for example "Fire // Ice".',
        '#',
        '# Anything after a "#" is a note. It stays with the card and is not part of the name. Write',
        '# one whenever the card is not the ordinary case, because the test harness prints it beside',
        '# the result, and a miss then explains itself:',
        '#     Preordain  # Italian M11 printing, "Predestinare"',
        '#     Sol Ring   # Commander 2019, the database only has the Alpha frame of this art',
        '#',
        '# Blank lines and lines that start with "#" are ignored.',
        '#',
        '# Expected number of cards: {}'.format(pack_size if pack_size is not None else 'unspecified'),
        '# Photos of this layout: {}'.format(', '.join(photo_names) if photo_names else 'none yet'),
        '',
    ]
    with open(str(path), 'w') as cards_file:
        cards_file.write('\n'.join(header))
        for line in existing_lines:
            cards_file.write(line + '\n')
    return path


def count_named_cards(path: Path) -> int:
    """How many card names have been typed into a layout file so far."""
    if not path.is_file():
        return 0
    with open(str(path)) as cards_file:
        return sum(1 for line in cards_file if card_name_from_line(line))


def save_photo(frame, path: Path, parameters: dict) -> None:
    """Write the frame, lossless unless the config asked for JPEG."""
    encode_parameters = []
    if path.suffix.lower() in ('.jpg', '.jpeg'):
        encode_parameters = [int(cv2.IMWRITE_JPEG_QUALITY), int(parameters['jpeg_quality'])]
    if not cv2.imwrite(str(path), frame, encode_parameters):
        raise RuntimeError('Could not write "{}". Is the disk full?'.format(path))


# --- the interactive session -------------------------------------------------------------------

def decide_preview(parameters: dict) -> bool:
    """
    Whether to drive the session from a preview window or from the prompt.

    'auto' is the useful setting: over a remote desktop the window works and is much the better way
    to aim the camera, while over a plain ssh session there is no display and OpenCV would abort the
    script rather than fall back. Some builds also have no GUI support at all, which only shows up
    when a window is actually created, so the test is to create one.
    """
    setting = parameters['show_preview']
    if setting is False or str(setting).lower() in ('false', 'no', 'off'):
        return False
    forced = setting is True or str(setting).lower() in ('true', 'yes', 'on')
    if not forced and os.name != 'nt' and not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        print('No display in this session, so the preview window is off and the prompt drives the '
              'capture instead. Connect with a remote desktop, or ssh -X, to get a preview.')
        return False
    try:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.waitKey(1)
    except Exception as exception:
        if forced:
            raise
        utils.print_exception(exception=exception, message='No preview window (falling back to the prompt)')
        return False
    return True


def close_preview_window() -> None:
    try:
        cv2.destroyAllWindows()
        cv2.waitKey(1)
    except Exception:
        pass


def downscale(image, max_width: int):
    """A copy of the image no wider than max_width, for display only."""
    if image.shape[1] <= max_width:
        return image.copy()
    scale = float(max_width) / image.shape[1]
    return cv2.resize(image, (int(image.shape[1] * scale), int(image.shape[0] * scale)))


def draw_overlay(image, lines: List[str]) -> None:
    """Write the session state over the top of the preview, on a band dark enough to read it on."""
    if not lines:
        return
    line_height = 20
    band_height = line_height * len(lines) + 12
    shaded = image.copy()
    cv2.rectangle(shaded, (0, 0), (image.shape[1], band_height), (0, 0, 0), thickness=-1)
    cv2.addWeighted(shaded, 0.55, image, 0.45, 0, image)
    for position, line in enumerate(lines):
        cv2.putText(image, line, (10, 22 + position * line_height), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)


def shot_headline(shot: dict, remaining: int, first_of_layout: bool) -> List[str]:
    """
    The instruction lines for one shot, shared by the window and the prompt.

    The first shot of a layout says so loudly. Every other shot of that layout only asks for the light
    to change, and photographing a stale layout with the wrong card list attached is the one mistake
    here that produces data which looks fine and is wrong.
    """
    card_count = shot['pack_size'] if shot['pack_size'] is not None else '?'
    lines = []
    if first_of_layout:
        lines.append('>>> NEW LAYOUT {}: put {} different cards on the mat <<<'.format(
            shot['layout'], card_count))
    lines.append('Shot {} (layout {}, {} left)'.format(shot['index'], shot['layout'], remaining))
    lines.append('{} cards, headlight {}, {}'.format(
        card_count, 'ON' if shot['headlight_on'] else 'off', shot['lighting']))
    lines.append(shot['note'])
    return lines


def wait_for_shot_in_window(video, shot: dict, remaining: int, first_of_layout: bool,
                            detect_markers: Optional[Callable], parameters: dict) -> str:
    """
    Show the live view until a key says what to do: capture, skip the shot, or end the session.

    The marker count is refreshed every few frames on the downscaled image. That is fast enough to
    keep the view responsive and good enough to aim with; the number that gets recorded is always
    measured on the full-resolution frame after the shutter.
    """
    headline = shot_headline(shot=shot, remaining=remaining, first_of_layout=first_of_layout)
    marker_line = 'markers: checking...' if detect_markers is not None else 'markers: not checked'
    expected = [int(marker_id) for marker_id in parameters['expected_marker_ids']]
    check_every = max(1, int(parameters['preview_marker_check_every']))
    frame_counter = 0
    while True:
        success, frame = video.read()
        if not success or frame is None:
            continue
        preview = downscale(image=frame, max_width=int(parameters['preview_max_width']))
        if detect_markers is not None and frame_counter % check_every == 0:
            centres = find_marker_centres(image=cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY),
                                          detect_markers=detect_markers)
            marker_line = 'markers: {}/{} found {}'.format(
                sum(1 for marker_id in expected if marker_id in centres), len(expected), sorted(centres))
        frame_counter += 1

        draw_overlay(preview, headline + [marker_line, '[space] capture   [s] skip   [q] end session'])
        cv2.imshow(WINDOW_NAME, preview)
        key = cv2.waitKey(20) & 0xFF
        if key in (32, 13, 10):
            return 'capture'
        if key == ord('s'):
            return 'skip'
        if key in (27, ord('q')):
            return 'quit'
        if window_was_closed():
            return 'quit'


def window_was_closed() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
    except Exception:
        return False


def wait_for_shot_at_prompt(shot: dict, remaining: int) -> str:
    """
    The same choice as the preview window, for a session with no display.

    The new-layout line is left out here, unlike in the window: the layout banner has just been
    printed a few lines above, and this text scrolls rather than being redrawn over the live view.
    """
    for line in shot_headline(shot=shot, remaining=remaining, first_of_layout=False):
        if line:
            print('  ' + line)
    return read_choice(prompt='  [Enter] capture   [s] skip   [q] end session > ',
                       choices={'': 'capture', 's': 'skip', 'q': 'quit'})


def confirm_in_window(image, lines: List[str]) -> str:
    """Show the shot just taken and ask whether to keep it."""
    preview = image.copy()
    draw_overlay(preview, lines + ['[Enter] keep   [r] retake   [q] end session'])
    while True:
        cv2.imshow(WINDOW_NAME, preview)
        key = cv2.waitKey(20) & 0xFF
        if key in (32, 13, 10):
            return 'keep'
        if key == ord('r'):
            return 'retake'
        if key in (27, ord('q')):
            return 'quit'
        if window_was_closed():
            return 'quit'


def confirm_at_prompt() -> str:
    return read_choice(prompt='  [Enter] keep   [r] retake   [q] end session > ',
                       choices={'': 'keep', 'r': 'retake', 'q': 'quit'})


def read_choice(prompt: str, choices: Dict[str, str]) -> str:
    """Read one of a few single-key answers from the prompt, re-asking until it is one of them."""
    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print('')
            return 'quit'
        if answer in choices:
            return choices[answer]
        print('  Not one of {}.'.format(', '.join(repr(key) for key in choices)))


def print_session_instructions(session_folder: Path, shot_plan: List[dict], use_preview: bool) -> None:
    print('')
    print('Session folder: {}'.format(session_folder))
    print('{} shots planned. Shots sharing a layout use the SAME cards: leave them untouched and only '
          'change the light between them.'.format(len(shot_plan)))
    if use_preview:
        print('Aim with the preview window, then [space] to capture, [s] to skip a shot, [q] to stop.')
    else:
        print('No preview: [Enter] captures, [s] skips a shot, [q] stops.')
    print('Before each layout, write down which cards you laid out. The script creates the file to put '
          'them in.')


def run_shots(video, shot_plan: List[dict], session: dict, run: dict, session_folder: Path,
              detect_markers: Optional[Callable], use_preview: bool, parameters: dict) -> None:
    """Walk the plan, one shot at a time, writing the session file after every photograph kept."""
    photo_index = next_photo_index(session_folder=session_folder)
    # Seeded from the whole session, not just this run, so continuing a session keeps naming the
    # earlier photos of a layout in that layout's card file.
    photos_by_layout = {}
    for earlier_run in session['runs']:
        for photo in earlier_run['photos']:
            photos_by_layout.setdefault(photo['layout'], []).append(photo['file_name'])
    current_layout = None

    for position, shot in enumerate(shot_plan):
        remaining = len(shot_plan) - position - 1
        first_of_layout = shot['layout'] != current_layout
        if first_of_layout:
            current_layout = shot['layout']
            photos_by_layout.setdefault(current_layout, [])
            announce_layout(shot=shot, session_folder=session_folder, session=session,
                            photo_names=photos_by_layout[current_layout])
        print('')

        while True:
            if use_preview:
                action = wait_for_shot_in_window(video=video, shot=shot, remaining=remaining,
                                                 first_of_layout=first_of_layout,
                                                 detect_markers=detect_markers, parameters=parameters)
            else:
                action = wait_for_shot_at_prompt(shot=shot, remaining=remaining)
            if action == 'quit':
                print('Session ended early. Everything captured so far is saved.')
                return
            if action == 'skip':
                print('  Shot {} skipped.'.format(shot['index']))
                break

            frame = grab_fresh_frame(video=video, flush_frames=parameters['flush_frames'])
            measurements = inspect_frame(
                frame=frame,
                detect_markers=detect_markers,
                expected_marker_ids=parameters['expected_marker_ids'],
                marker_centre_spacing_mm=parameters['marker_centre_spacing_mm'],
            )
            warnings = warnings_for(measurements=measurements, parameters=parameters)
            print('  {}'.format(describe_measurements(measurements=measurements)))
            for warning in warnings:
                print('  WARNING: {}'.format(warning))

            decision = 'keep'
            if parameters['confirm_each_shot']:
                if use_preview:
                    decision = confirm_in_window(
                        image=downscale(image=frame, max_width=int(parameters['preview_max_width'])),
                        lines=[describe_measurements(measurements=measurements)] +
                              ['! ' + warning[:70] for warning in warnings])
                else:
                    decision = confirm_at_prompt()
            if decision == 'quit':
                print('Session ended early. Everything captured so far is saved.')
                return
            if decision == 'retake':
                print('  Retaking shot {}.'.format(shot['index']))
                continue

            file_name = 'photo_{:03d}{}'.format(photo_index, parameters['image_format'])
            save_photo(frame=frame, path=session_folder / file_name, parameters=parameters)
            photo_index += 1
            photos_by_layout[current_layout].append(file_name)

            record = {
                'file_name': file_name,
                'captured_at': datetime.now().isoformat(timespec='seconds'),
                'shot': shot['index'],
                'layout': current_layout,
                'cards_file': cards_file_name(layout=current_layout),
                'pack_size': shot['pack_size'],
                'headlight_on': shot['headlight_on'],
                'lighting': shot['lighting'],
                'note': shot['note'],
                'warnings': warnings,
            }
            record.update(measurements)
            run['photos'].append(record)
            write_session(session_folder=session_folder, session=session)
            write_cards_file(session_folder=session_folder, session_name=session['session'],
                             layout=current_layout, pack_size=shot['pack_size'],
                             photo_names=photos_by_layout[current_layout])
            print('  Saved {}'.format(file_name))
            break


def announce_layout(shot: dict, session_folder: Path, session: dict, photo_names: List[str]) -> None:
    """Tell the user to change the cards on the mat, and where this layout's card list lives."""
    cards_path = write_cards_file(session_folder=session_folder, session_name=session['session'],
                                  layout=shot['layout'], pack_size=shot['pack_size'],
                                  photo_names=photo_names)
    print('')
    print('=' * 100)
    print('LAYOUT {}: lay out {} cards on the mat.'.format(
        shot['layout'], shot['pack_size'] if shot['pack_size'] is not None else 'the'))
    print('Keep them exactly there for every shot of this layout, and write their names into:')
    print('    {}'.format(cards_path))
    print('=' * 100)


def print_summary(session_folder: Path, run: dict, parameters: dict) -> None:
    """Close the session with what was captured, what still needs labelling, and how to fetch it."""
    photos = run['photos']
    print('')
    print('=' * 100)
    print('{} photo(s) written to {}'.format(len(photos), session_folder))
    if not photos:
        print('Nothing captured, so nothing to label.')
        print('=' * 100)
        return

    flagged = [photo for photo in photos if photo['warnings']]
    if flagged:
        print('{} of them raised a warning:'.format(len(flagged)))
        for photo in flagged:
            print('    {}: {}'.format(photo['file_name'], '; '.join(photo['warnings'])))

    print('')
    print('Still to do, and the photos are worthless without it: write the card names into these files, '
          'one name per line.')
    layouts = sorted({photo['layout'] for photo in photos})
    for layout in layouts:
        path = session_folder / cards_file_name(layout=layout)
        named = count_named_cards(path=path)
        expected = next((photo['pack_size'] for photo in photos if photo['layout'] == layout), None)
        state = 'empty' if named == 0 else '{} name(s)'.format(named)
        if expected is not None and named != expected:
            state += ', expected {}'.format(expected)
        print('    {}  ({})'.format(path.name, state))

    print('')
    print('Then copy the whole folder to the PC, into the mtg_cube_draft repo:')
    print('    scp -r {}@{}:{} <mtg_cube_draft>/data/photos/'.format(
        os.environ.get('USER', 'jetson'), socket.gethostname(), session_folder))
    print('=' * 100)


if __name__ == '__main__':
    capture_mat_photos()
