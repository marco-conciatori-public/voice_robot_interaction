"""
Live view of the arm camera with the mat measurements drawn on it, for aiming the robot.

Companion to capture_mat_photos.py, and the step before it. That script is the wrong tool for
deciding where the robot should stand: it opens by creating a session folder and asking for fifteen
cards on the mat. This one takes no photographs and writes nothing at all. It answers one question,
continuously, while you move the robot with both hands: does the camera see the whole mat well
enough for the session to be worth running?

The numbers come from capture_mat_photos itself, measured by the same code and read from the same
config file, because aiming under settings the session will not use answers a different question.
What this script adds is the part aiming actually needs, which is what to do about the numbers:
which corner is missing, which way the mat sits off centre, whether to come closer or back off.

Three ways to watch it, because the Jetson is usually headless:

  - a preview window, when the session has a display (a remote desktop, or ssh -X),
  - an MJPEG stream at http://<jetson>:8080/, which is the useful one over plain ssh: the browser on
    the PC shows the live view while both your hands are on the robot,
  - one line of numbers a second at the prompt, which needs nothing at all.

'output: auto' takes the first of those that works. Run it with no arguments, from the IDE Run
button or the terminal; everything is read from configs/aim_camera.yaml. Stop it with [q] in the
window, or Ctrl+C anywhere.

main_thread.py must not be running, for the same reason as during a capture session: a V4L2 device
opens once, and the second opener gets an error or black frames.
"""

import os
import sys
import json
import time
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Python puts this script's own folder on sys.path, so importing the sibling script works when the
# file is run directly. The insert only covers the case of aim_camera being imported from elsewhere.
SCRIPTS_FOLDER = Path(__file__).resolve().parent
if str(SCRIPTS_FOLDER) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_FOLDER))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# This import has to come before 'args' and 'utils': capture_mat_photos finds the project root and
# puts it on sys.path as it loads, which is what makes the repo's top-level modules importable here.
import capture_mat_photos as capture  # noqa: E402

import args  # noqa: E402
import utils  # noqa: E402

WINDOW_NAME = 'aim camera'
# The corners the marker ids sit on, in the order the ids are listed in the config: that order is the
# way round the mat, clockwise from the top left, which is also what lets their centres be joined
# into the mat quadrilateral rather than a bowtie.
CORNER_NAMES = ('top left', 'top right', 'bottom right', 'bottom left')
OUTPUT_CHOICES = ('auto', 'window', 'http', 'text')


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """
    One thread per connection, so a browser sitting on the MJPEG stream cannot block the status
    requests arriving beside it.

    http.server has had exactly this class since Python 3.7, and importing it from there is how this
    started. The Jetson's interpreter is older than that, and a script that only runs on a board with
    a newer Python is no use here, so the two lines it saves are written out instead.
    """

    daemon_threads = True


def aim_camera(**kwargs) -> Optional[dict]:
    """
    Show the live view until it is stopped, returning the last set of measurements taken.

    Keyword arguments override the YAML config. Running with none at all is the normal case.
    """
    parameters = args.import_args(
        yaml_path=str(capture.PROJECT_ROOT / 'configs' / 'aim_camera.yaml'),
        **kwargs,
    )
    capture_parameters = load_capture_parameters(parameters=parameters)
    output = decide_output(parameters=parameters)

    video = capture.open_camera(parameters=capture_parameters)
    server = None
    try:
        camera_information = capture.describe_camera(video=video, parameters=capture_parameters)
        capture.report_camera(camera_information=camera_information, parameters=capture_parameters)
        capture.settle_camera(video=video, seconds=capture_parameters['settle_seconds'],
                              verbose=parameters['verbose'])

        detect_markers = None
        if capture_parameters['check_markers']:
            detect_markers = capture.make_marker_detector(
                dictionary_name=capture_parameters['aruco_dictionary'])
            if detect_markers is None:
                print('WARNING: this OpenCV build has no working cv2.aruco, so the mat cannot be found '
                      'in the picture and none of the aiming advice below is available. The live view '
                      'still works. (cv2.aruco needs the contrib build.)')

        latest_frame = LatestFrame()
        if output == 'http':
            server = start_http_server(parameters=parameters, latest_frame=latest_frame)
        print_instructions(output=output, capture_parameters=capture_parameters)

        return watch(video=video, detect_markers=detect_markers, output=output, parameters=parameters,
                     capture_parameters=capture_parameters, latest_frame=latest_frame)
    finally:
        video.release()
        close_window()
        if server is not None:
            server.shutdown()
            server.server_close()


def load_capture_parameters(parameters: dict) -> dict:
    """
    The camera and mat settings the capture session will use, which is what makes this preview honest.

    They are read from capture_mat_photos.yaml rather than restated here on purpose. A second copy of
    the resolution, the codec and the marker geometry would drift from the first one, and the drift
    would show up as a camera aimed under settings the session never uses: a preview at a different
    resolution measures a different number of pixels per millimetre, which is the whole point of the
    exercise.
    """
    configured_path = Path(str(parameters['capture_config']))
    if not configured_path.is_absolute():
        configured_path = capture.PROJECT_ROOT / configured_path
    if not configured_path.is_file():
        raise FileNotFoundError(
            'The capture config "{}" does not exist. "capture_config" points at the config the capture '
            'session is driven by, so the aim and the session agree about the camera.'
            .format(configured_path))

    capture_parameters = args.import_args(yaml_path=str(configured_path))
    # Probing walks the camera through every resolution it might support, which costs seconds and
    # answers a question about the camera rather than about the aim. The capture session asks it.
    capture_parameters['probe_camera_modes'] = bool(parameters['probe_camera_modes'])
    return capture_parameters


# --- choosing and running an output --------------------------------------------------------------

def decide_output(parameters: dict) -> str:
    """
    Which of the three views to use.

    'auto' prefers the window, because it costs nothing and opens no port, and falls back to the
    browser stream rather than to text: aiming a camera from a column of numbers is possible but
    miserable, and the fallback is what a plain ssh session will actually hit.
    """
    setting = str(parameters['output']).strip().lower()
    if setting not in OUTPUT_CHOICES:
        raise ValueError('"output" is one of {}. Got "{}".'.format(', '.join(OUTPUT_CHOICES),
                                                                   parameters['output']))
    if setting == 'window':
        if not display_available(forced=True):
            raise RuntimeError('"output: window" was asked for, but this session has no usable display. '
                               'Leave it on "auto" to fall back to the browser stream.')
        return 'window'
    if setting == 'auto':
        if display_available(forced=False):
            return 'window'
        print('No display in this session, so the live view goes to the browser instead.')
        return 'http'
    return setting


def display_available(forced: bool) -> bool:
    """
    Whether a preview window can actually be opened here.

    capture_mat_photos has its own version of this test, and they are deliberately not shared: there
    the question is "window or prompt" and the fallback is typing at the terminal, here it is "window
    or browser". The overlap is the OpenCV part, which is one call: some builds have no GUI support
    at all, and the only way to find that out is to create a window.
    """
    if not forced and os.name != 'nt' and not (os.environ.get('DISPLAY') or
                                               os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.waitKey(1)
    except Exception as exception:
        if forced:
            raise
        utils.print_exception(exception=exception, message='No preview window')
        return False
    return True


def window_was_closed() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1
    except Exception:
        return False


def close_window() -> None:
    try:
        cv2.destroyAllWindows()
        cv2.waitKey(1)
    except Exception:
        pass


def print_instructions(output: str, capture_parameters: dict) -> None:
    print('')
    print('Aiming against the mat printed from configs/mat_geometry.toml: {} markers {}, {:.0f} mm '
          'between the two top marker centres.'.format(capture_parameters['aruco_dictionary'],
                                                       capture_parameters['expected_marker_ids'],
                                                       capture_parameters['marker_centre_spacing_mm']))
    print('Nothing is written to disk. Move the robot until the view says READY, park it there, then '
          'run scripts/capture_mat_photos.py without touching the camera again.')
    if output == 'window':
        print('[q] or [esc] closes the window and ends the preview.')
    elif output == 'text':
        print('Ctrl+C ends the preview.')
    print('')


# --- the loop -------------------------------------------------------------------------------------

def watch(video, detect_markers: Optional[Callable], output: str, parameters: dict,
          capture_parameters: dict, latest_frame: 'LatestFrame') -> Optional[dict]:
    """Read frames, measure them, and put the result wherever the chosen output wants it."""
    detect, remembered = remembering_detector(detect_markers=detect_markers)
    expected = [int(marker_id) for marker_id in capture_parameters['expected_marker_ids']]
    measure_every = max(1, int(parameters['measure_every_frames']))
    preview_width = int(parameters['preview_max_width'])
    jpeg_quality = int(parameters['jpeg_quality'])
    text_interval = float(parameters['text_interval_seconds'])

    frame_counter = 0
    measurements = None
    warnings = []
    guidance = []
    centres = {}
    verdict = ''
    last_reported = None
    last_text_at = 0.0

    try:
        while True:
            success, frame = video.read()
            if not success or frame is None:
                continue

            # Measuring every frame is wasted work: marker detection is the only expensive thing in
            # the loop, and a hand moving a robot does not need thirty updates a second. The drawing
            # in between reuses the last detection, so the outlines can lag by a frame or two.
            if measurements is None or frame_counter % measure_every == 0:
                measurements = capture.inspect_frame(
                    frame=frame,
                    detect_markers=detect,
                    expected_marker_ids=expected,
                    marker_centre_spacing_mm=capture_parameters['marker_centre_spacing_mm'],
                )
                warnings = capture.warnings_for(measurements=measurements, parameters=capture_parameters)
                centres = centres_from(remembered=remembered)
                guidance = aim_guidance(measurements=measurements, centres=centres,
                                        frame_width=frame.shape[1], frame_height=frame.shape[0],
                                        expected_marker_ids=expected, parameters=parameters)
                verdict = verdict_for(measurements=measurements, warnings=warnings, guidance=guidance)
            frame_counter += 1

            # The terminal keeps a short log even when the view is elsewhere, so the session that
            # started the script still shows what happened while you were looking at the browser.
            report_key = (verdict, guidance[0] if guidance else '')
            if output != 'text' and parameters['report_changes'] and report_key != last_reported:
                print('{}: {}'.format(verdict, capture.describe_measurements(measurements=measurements)))
                for line in guidance[:2]:
                    print('    {}'.format(line))
                last_reported = report_key

            if output == 'text':
                now = time.time()
                if now - last_text_at >= text_interval:
                    print('{}: {}'.format(verdict,
                                          capture.describe_measurements(measurements=measurements)))
                    for line in guidance[:2]:
                        print('    {}'.format(line))
                    last_text_at = now
                continue

            preview = capture.downscale(image=frame, max_width=preview_width)
            if parameters['draw_markers']:
                scale = float(preview.shape[1]) / float(frame.shape[1])
                draw_marker_outlines(image=preview, remembered=remembered, scale=scale, expected=expected)
                draw_aim_marks(image=preview, centres=centres, expected=expected, scale=scale)
            capture.draw_overlay(image=preview,
                                 lines=overlay_lines(verdict=verdict, measurements=measurements,
                                                     guidance=guidance, warnings=warnings,
                                                     expected_count=len(expected), output=output))

            if output == 'window':
                cv2.imshow(WINDOW_NAME, preview)
                key = cv2.waitKey(20) & 0xFF
                if key in (27, ord('q')) or window_was_closed():
                    break
            else:
                encoded, buffer = cv2.imencode('.jpg', preview,
                                               [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
                if encoded:
                    latest_frame.publish(jpeg=buffer.tobytes(),
                                         status=status_of(verdict=verdict, measurements=measurements,
                                                          guidance=guidance, warnings=warnings))
    except KeyboardInterrupt:
        print('')

    if measurements is not None:
        print('')
        print('Last reading: {}: {}'.format(verdict,
                                            capture.describe_measurements(measurements=measurements)))
        print('Leave the robot exactly there and start scripts/capture_mat_photos.py.')
    return measurements


def remembering_detector(detect_markers: Optional[Callable]) -> Tuple[Optional[Callable], dict]:
    """
    The marker detector, wrapped so that its last result stays available for drawing.

    inspect_frame() detects once and returns numbers, not corners, while the preview wants the corners
    to outline. Detecting a second time just to draw them would double the only expensive thing in the
    loop, so the wrapper keeps what the measurement pass already found.
    """
    remembered = {'corners': None, 'ids': None}
    if detect_markers is None:
        return None, remembered

    def detect(image):
        corners, ids, rejected = detect_markers(image)
        remembered['corners'] = corners
        remembered['ids'] = ids
        return corners, ids, rejected

    return detect, remembered


def centres_from(remembered: dict) -> Dict[int, np.ndarray]:
    """Marker id to the centre of its four corners, from the detection inspect_frame already did."""
    centres = {}
    if remembered['ids'] is None:
        return centres
    for marker_corners, marker_id in zip(remembered['corners'], np.asarray(remembered['ids']).flatten()):
        centres[int(marker_id)] = np.asarray(marker_corners, dtype=np.float32).reshape(4, 2).mean(axis=0)
    return centres


# --- what to do about the numbers ------------------------------------------------------------------

def marker_roles(expected_marker_ids: Sequence) -> Dict[int, str]:
    """Which corner of the mat each marker id sits on, following the order the config lists them in."""
    return {int(marker_id): CORNER_NAMES[position % len(CORNER_NAMES)]
            for position, marker_id in enumerate(expected_marker_ids)}


def aim_guidance(measurements: dict, centres: Dict[int, np.ndarray], frame_width: int, frame_height: int,
                 expected_marker_ids: Sequence, parameters: dict) -> List[str]:
    """
    What to change about where the camera is, in the order it matters. Empty when the aim is good.

    This is the half capture_mat_photos does not have. Its warnings say what is wrong with a
    photograph, which is what you want once the cards are on the table; here the same measurements
    have to say which way to move a robot, and a missing marker or a mat sitting off to one side is a
    different instruction from "the shot is too dark".
    """
    found = measurements['markers_found']
    if found is None:
        return ['The mat cannot be located (no cv2.aruco), so aim by eye: the whole sheet in frame, '
                'with a margin, and the camera looking down at it rather than across it.']

    expected = [int(marker_id) for marker_id in expected_marker_ids]
    roles = marker_roles(expected_marker_ids=expected)
    missing = [marker_id for marker_id in expected if marker_id not in found]
    if len(missing) == len(expected):
        return ['No markers at all. Point the camera at the mat, put some light on it, and check that '
                'nothing is lying over the four white patches at the mat corners.']
    if missing:
        named = ', '.join('{} ({})'.format(roles[marker_id], marker_id) for marker_id in missing)
        return ['Cannot see the {} marker. Pull back, or move the camera that way, until all four are '
                'in frame: a photo missing a mat corner is one the detector can never use.'.format(named)]

    advice = []
    centroid = np.mean([centres[marker_id] for marker_id in expected], axis=0)
    horizontal = (float(centroid[0]) - frame_width / 2.0) / float(frame_width)
    vertical = (float(centroid[1]) - frame_height / 2.0) / float(frame_height)
    tolerance = float(parameters['centre_tolerance'])
    if abs(horizontal) > tolerance:
        advice.append('The mat sits {:.0%} of the frame to the {}: aim further {}.'.format(
            abs(horizontal), 'right' if horizontal > 0 else 'left',
            'right' if horizontal > 0 else 'left'))
    if abs(vertical) > tolerance:
        advice.append('The mat sits {:.0%} of the frame too {}: aim further {}.'.format(
            abs(vertical), 'low' if vertical > 0 else 'high', 'down' if vertical > 0 else 'up'))

    coverage = measurements['mat_coverage']
    target_coverage = float(parameters['target_mat_coverage'])
    if coverage is not None and coverage < target_coverage:
        advice.append('The mat fills {:.0%} of the frame; come closer until it fills about {:.0%}. Every '
                      'pixel spent on the table is a pixel not spent on a card.'
                      .format(coverage, target_coverage))
    elif coverage is not None and coverage > float(parameters['max_mat_coverage']):
        advice.append('The mat fills {:.0%} of the frame, so there is no margin left: back off a little, '
                      'or a card near the edge ends up half outside the picture.'.format(coverage))

    near = measurements['pixels_per_millimetre_max']
    far = measurements['pixels_per_millimetre_min']
    if near and far and far > 0 and near / far > float(parameters['max_scale_ratio']):
        advice.append('The far edge of the mat is at {:.0%} of the scale of the near edge, so the camera '
                      'is looking across the mat more than down at it: raise it, or steepen the angle.'
                      .format(far / near))
    return advice


def verdict_for(measurements: dict, warnings: List[str], guidance: List[str]) -> str:
    """The one word the whole view exists to show, short enough to read from across the table."""
    if measurements['markers_found'] is None:
        return 'NOT MEASURED'
    if guidance:
        return 'ADJUST'
    if warnings:
        return 'FRAMED, but check the warnings'
    return 'READY'


def status_of(verdict: str, measurements: dict, guidance: List[str], warnings: List[str]) -> dict:
    """Everything the browser page shows, in one JSON-safe dictionary."""
    text_lines = [verdict, capture.describe_measurements(measurements=measurements)]
    text_lines.extend(guidance)
    text_lines.extend('! ' + warning for warning in warnings)
    return {
        'verdict': verdict,
        'measurements': measurements,
        'guidance': guidance,
        'warnings': warnings,
        'text': '\n'.join(text_lines),
    }


# --- drawing ---------------------------------------------------------------------------------------

def draw_marker_outlines(image, remembered: dict, scale: float, expected: Sequence) -> None:
    """Outline every marker the detector found, so it is obvious which corner it is missing."""
    if remembered['ids'] is None:
        return
    for marker_corners, marker_id in zip(remembered['corners'], np.asarray(remembered['ids']).flatten()):
        points = (np.asarray(marker_corners, dtype=np.float32).reshape(4, 2) * scale).astype(np.int32)
        # Orange for a marker that is not one of the mat's four: a stray tag in view is worth seeing
        # rather than silently ignoring, since it usually means the wrong dictionary is configured.
        colour = (0, 255, 0) if int(marker_id) in expected else (0, 165, 255)
        cv2.polylines(image, [points], isClosed=True, color=colour, thickness=2)
        cv2.putText(image, str(int(marker_id)), (int(points[0][0]), int(points[0][1]) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2, cv2.LINE_AA)


def draw_aim_marks(image, centres: Dict[int, np.ndarray], expected: Sequence, scale: float) -> None:
    """
    The mat quadrilateral, its centre, and the centre of the frame.

    Two dots and the gap between them say more about which way to move than any sentence: the aim is
    good when the mat's dot sits on the frame's cross and the quadrilateral fills most of the view.
    """
    height, width = image.shape[:2]
    cv2.drawMarker(image, (width // 2, height // 2), (255, 255, 255), cv2.MARKER_CROSS, 18, 1)
    if not all(int(marker_id) in centres for marker_id in expected):
        return
    quadrilateral = np.array([centres[int(marker_id)] * scale for marker_id in expected], dtype=np.int32)
    cv2.polylines(image, [quadrilateral], isClosed=True, color=(255, 200, 0), thickness=2)
    centroid = quadrilateral.mean(axis=0)
    cv2.circle(image, (int(centroid[0]), int(centroid[1])), 6, (255, 200, 0), thickness=-1)


def overlay_lines(verdict: str, measurements: dict, guidance: List[str], warnings: List[str],
                  expected_count: int, output: str) -> List[str]:
    """The text band over the live view: the verdict, the numbers, and at most a few things to do."""
    lines = [verdict, short_measurements(measurements=measurements, expected_count=expected_count)]
    lines.extend(shorten(text=line, width=78) for line in guidance[:2])
    lines.extend('! ' + shorten(text=warning, width=76) for warning in warnings[:2])
    if output == 'window':
        lines.append('[q] quit')
    return lines


def short_measurements(measurements: dict, expected_count: int = 4) -> str:
    """
    The numbers, compressed to fit the overlay.

    describe_measurements() is the version for a terminal line and is too long to draw over a 960 px
    preview, where it would run off the right edge and lose the px/mm at the end of it.
    """
    parts = []
    if measurements['markers_found'] is not None:
        parts.append('markers {}/{}'.format(len(measurements['markers_found']), expected_count))
    if measurements['mat_coverage'] is not None:
        parts.append('mat {:.0%}'.format(measurements['mat_coverage']))
    if measurements['pixels_per_millimetre_min'] is not None:
        parts.append('{:.2f}-{:.2f} px/mm'.format(measurements['pixels_per_millimetre_min'],
                                                  measurements['pixels_per_millimetre_max']))
    parts.append('sharp {:.0f}'.format(measurements['sharpness']))
    parts.append('bright {:.0f}'.format(measurements['mean_brightness']))
    parts.append('clipped {:.1%}'.format(measurements['clipped_fraction']))
    return '  '.join(parts)


def shorten(text: str, width: int) -> str:
    """One line's worth of a sentence: the overlay draws a fixed band, so the text has to fit it."""
    return text if len(text) <= width else text[:width - 3] + '...'


# --- the browser view ------------------------------------------------------------------------------

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>aim camera</title>
<style>
 body { background:#111; color:#eee; font-family:system-ui,sans-serif; margin:0; padding:16px; }
 h1 { font-size:16px; font-weight:600; margin:0 0 12px; color:#9ad; }
 img { max-width:100%; border:1px solid #333; display:block; }
 pre { white-space:pre-wrap; font-size:14px; line-height:1.5; margin:12px 0 0; }
</style></head>
<body>
<h1>aim camera: move the robot until this says READY</h1>
<img src="/stream.mjpg" alt="live camera view">
<pre id="status">waiting for the first measurement...</pre>
<script>
async function tick() {
  try {
    const response = await fetch('/status.json', {cache: 'no-store'});
    document.getElementById('status').textContent = (await response.json()).text;
  } catch (error) { /* the script was stopped; the stream will show that too */ }
  setTimeout(tick, 500);
}
tick();
</script>
</body></html>
"""


class LatestFrame:
    """
    The most recent annotated frame and its numbers, handed from the capture loop to the HTTP threads.

    One slot rather than a queue, on purpose: a browser that cannot keep up should see the newest
    frame and skip the rest, which is what aiming needs and what a queue would prevent.
    """

    def __init__(self):
        self._condition = threading.Condition()
        self._jpeg = b''
        self._status = {}
        self._version = 0

    def publish(self, jpeg: bytes, status: dict) -> None:
        with self._condition:
            self._jpeg = jpeg
            self._status = status
            self._version += 1
            self._condition.notify_all()

    def wait_for_next(self, seen_version: int, timeout: float = 5.0) -> Tuple[bytes, int]:
        with self._condition:
            if self._version == seen_version:
                self._condition.wait(timeout=timeout)
            return self._jpeg, self._version

    def status(self) -> dict:
        with self._condition:
            return dict(self._status)


def make_http_server(host: str, port: int, latest_frame: LatestFrame) -> ThreadingHTTPServer:
    """The little MJPEG server: a page, the stream it embeds, and the numbers as JSON."""

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0 closes the connection at the end of a response, which is what an unbounded
        # multipart stream wants: there is no content length to promise and none to get wrong.
        protocol_version = 'HTTP/1.0'

        def log_message(self, format, *arguments):  # noqa: A002 (the base class names it 'format')
            pass  # the default logs a line per frame, which would bury the aiming advice

        def do_GET(self):
            path = self.path.split('?')[0]
            if path in ('/', '/index.html'):
                self.send_bytes(content_type='text/html; charset=utf-8', payload=PAGE.encode('utf-8'))
            elif path == '/status.json':
                payload = json.dumps(latest_frame.status()).encode('utf-8')
                self.send_bytes(content_type='application/json', payload=payload)
            elif path == '/stream.mjpg':
                self.send_stream()
            else:
                self.send_error(404)

        def send_bytes(self, content_type: str, payload: bytes) -> None:
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)

        def send_stream(self) -> None:
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            version = -1
            try:
                while True:
                    jpeg, version = latest_frame.wait_for_next(seen_version=version)
                    if not jpeg:
                        continue
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ')
                    self.wfile.write(str(len(jpeg)).encode('ascii') + b'\r\n\r\n')
                    self.wfile.write(jpeg + b'\r\n')
            except (BrokenPipeError, ConnectionResetError):
                pass  # the tab was closed or reloaded, which is not worth a traceback

    return ThreadingHTTPServer((host, port), Handler)


def start_http_server(parameters: dict, latest_frame: LatestFrame) -> ThreadingHTTPServer:
    """Start serving the live view in the background, and say out loud where to open it."""
    host = str(parameters['http_host'])
    port = int(parameters['http_port'])
    try:
        server = make_http_server(host=host, port=port, latest_frame=latest_frame)
    except OSError as exception:
        raise RuntimeError('Could not listen on {}:{} ({}). Another aim_camera is probably still '
                           'running, or something else holds the port: stop it, or set a different '
                           '"http_port".'.format(host, port, exception))
    threading.Thread(target=server.serve_forever, name='aim-camera-http', daemon=True).start()
    print('')
    print('Live view: http://{}:{}/   (or http://{}:{}/ by name)'.format(
        local_address(), port, socket.gethostname(), port))
    print('Open it in a browser on the PC, on the same network. Ctrl+C here ends the preview.')
    return server


def local_address() -> str:
    """
    This machine's address on the network it routes through, for a URL that can actually be opened.

    The server binds 0.0.0.0, which is not something to type into a browser. Opening a UDP socket
    towards an outside address makes the kernel choose the interface it would use and reveals its
    address, without a single packet being sent; with no route at all, the hostname is the better
    guess.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 80))
        return probe.getsockname()[0]
    except Exception:
        return socket.gethostname()
    finally:
        probe.close()


if __name__ == '__main__':
    aim_camera()
