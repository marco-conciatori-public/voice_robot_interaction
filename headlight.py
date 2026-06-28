import time
import warnings
import threading

import Jetson.GPIO as GPIO

import args
import global_constants as gc


class Headlight:
    """
    Controls the external COB LED strip that illuminates the scene for the camera in low light.

    The strip is a passive 5V load (two wires, no signal input) switched by a MOSFET module; this class
    drives the MOSFET gate from a Jetson Nano GPIO pin. The light used to live on the RDK X3 (Hobot.GPIO,
    hardware PWM on pin 33); it was moved to the Jetson for physical wiring access. The RDK X3 stays the
    single control surface and sends on/off/brightness commands over the wired command channel; this class
    executes them locally (see the command handlers wired in main_thread.py).

    Wiring: expansion-board 5V -> MOSFET load input, strip -> MOSFET load output, this pin -> MOSFET
    trigger, MOSFET trigger ground tied to the Jetson ground (a common ground is required). The Jetson GPIO
    swings 3.3V, so the MOSFET module must fully switch at a 3.3V trigger.

    Configuration (configs/headlight.yaml):
      - pin: BOARD-numbered Jetson GPIO pin driving the MOSFET gate.
      - pwm_mode:
          'hardware' -> Jetson hardware PWM (pins 32/33 only, must be enabled with jetson-io). Smooth,
                        no CPU cost, full brightness control.
          'software' -> best-effort software PWM (a background thread toggles the pin). Works on any
                        output pin but uses CPU and can flicker; use only if no hardware-PWM pin is free.
          'onoff'    -> plain digital output, no brightness (any non-zero level is full on).
      - pwm_frequency / software_pwm_frequency: carrier frequency in Hz for the respective modes.
      - brightness_levels: duty-cycle percentages; index 0 is always OFF (the strip starts dark), the
        remaining entries are the "on" states cycled through. The duty -> perceived brightness mapping
        depends on the strip and is best tuned on the robot.
    """

    def __init__(self, **kwargs):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'headlight.yaml', **kwargs)
        self.verbose = parameters['verbose']
        self.pin = parameters['pin']
        self.pwm_mode = parameters['pwm_mode']
        self.pwm_frequency = parameters['pwm_frequency']
        self.software_pwm_frequency = parameters['software_pwm_frequency']
        self.brightness_levels = parameters['brightness_levels']
        assert len(self.brightness_levels) >= 1, 'brightness_levels must contain at least the OFF level.'
        assert self.pwm_mode in ('hardware', 'software', 'onoff'), \
            f'Unknown pwm_mode "{self.pwm_mode}" (expected hardware/software/onoff).'

        self.current_level = 0
        self.is_on = False
        self.pwm = None
        # software-PWM state (only used when pwm_mode == 'software')
        self._sw_duty = 0
        self._sw_running = False
        self._sw_thread = None

        mode = GPIO.getmode()
        if mode is None:
            GPIO.setmode(GPIO.BOARD)
        elif mode != GPIO.BOARD:
            warnings.warn(f'GPIO was in mode {mode}, but it should be BOARD. Setting GPIO mode to BOARD.')
            GPIO.setmode(GPIO.BOARD)

        # Start turned off: brightness_levels[0] is duty 0, so the strip is dark until a level is applied.
        if self.pwm_mode == 'hardware':
            # Jetson.GPIO requires the pin be set up as an output before creating the PWM object
            # (this is the opposite of Hobot.GPIO on the RDK X3).
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)
            self.pwm = GPIO.PWM(self.pin, self.pwm_frequency)
            self.pwm.start(self.brightness_levels[0])
        elif self.pwm_mode == 'software':
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)
            self._sw_running = True
            self._sw_thread = threading.Thread(
                target=self._software_pwm_loop, name='headlight_software_pwm', daemon=True)
            self._sw_thread.start()
        else:  # onoff
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)

        if self.verbose >= 2:
            print(f'Headlight ready on GPIO pin {self.pin} (mode {self.pwm_mode}, brightness levels '
                  f'{self.brightness_levels}).')

    def _software_pwm_loop(self) -> None:
        """Best-effort software PWM: toggle the pin at software_pwm_frequency with the current duty."""
        period = 1.0 / self.software_pwm_frequency
        while self._sw_running:
            duty = self._sw_duty / 100.0
            if duty <= 0:
                GPIO.output(self.pin, GPIO.LOW)
                time.sleep(period)
            elif duty >= 1:
                GPIO.output(self.pin, GPIO.HIGH)
                time.sleep(period)
            else:
                GPIO.output(self.pin, GPIO.HIGH)
                time.sleep(period * duty)
                GPIO.output(self.pin, GPIO.LOW)
                time.sleep(period * (1.0 - duty))

    def _apply_level(self, level: int) -> None:
        level = level % len(self.brightness_levels)
        self.current_level = level
        self.is_on = level != 0
        duty = self.brightness_levels[level]
        if self.pwm_mode == 'hardware':
            self.pwm.ChangeDutyCycle(duty)
        elif self.pwm_mode == 'software':
            self._sw_duty = duty
        else:  # onoff
            GPIO.output(self.pin, GPIO.HIGH if duty > 0 else GPIO.LOW)
        if self.verbose >= 3:
            print(f'Headlight level {level} -> duty {duty}%.')

    def turn_on(self) -> None:
        # turn on at the first non-off level if there is one, otherwise stay off
        self._apply_level(1 if len(self.brightness_levels) > 1 else 0)

    def turn_off(self) -> None:
        self._apply_level(0)

    def toggle(self) -> None:
        if self.is_on:
            self.turn_off()
        else:
            self.turn_on()

    def set_state(self, on: bool) -> None:
        if on:
            self.turn_on()
        else:
            self.turn_off()

    def next_level(self) -> None:
        """Cycle to the next configured light state (off -> on states -> off)."""
        self._apply_level(self.current_level + 1)

    def __del__(self):
        try:
            self._sw_running = False
            self.turn_off()
            if self.pwm is not None:
                self.pwm.stop()
            GPIO.cleanup(self.pin)
        except Exception:
            pass
