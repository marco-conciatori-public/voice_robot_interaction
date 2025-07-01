#!/usr/bin/env python3
# coding: utf-8
import smbus

import args
import global_constants as gc


class HardwareInteraction:
    def __init__(self, **kwargs):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'hardware_interaction.yaml', **kwargs)
        self.bus_address = parameters['bus_address']
        self.bus = smbus.SMBus(parameters['bus_number'])
        self.verbose = parameters['verbose']

    # Set the specified color of the RGB light. Red, green, and blue: 0-255
    def rgb_led(self, red: int, green: int, blue: int) -> None:
        try:
            self.bus.write_i2c_block_data(self.bus_address, 0x02, [red & 0xff, green & 0xff, blue & 0xff])
        except:
            print('arm_rgb_set I2C error')

    # Restart the driver board
    def arm_reset(self) -> None:
        try:
            self.bus.write_byte_data(self.bus_address, 0x05, 0x01)
        except:
            print('arm_reset I2C error')

    # PWD servo control servo_id: 1-6 (0 controls all servos). Angle: 0-180 degrees.
    def pwm_servo_write(self, servo_id: int, angle: int) -> None:
        try:
            if servo_id == 0:
                self.bus.write_byte_data(self.bus_address, 0x57, angle & 0xff)
            else:
                self.bus.write_byte_data(self.bus_address, 0x50 + servo_id, angle & 0xff)
        except:
            print('arm_pwm_servo_write I2C error')

    # Turn on the buzzer for a specified duration. If duration is 0, turn off the buzzer. Duration: 0.1-5 seconds.
    # 0.1 and 5 seconds.
    def set_beep(self, duration: int) -> None:
        """
        Set the buzzer to beep for a specified duration.
        :param duration: Duration in seconds for which the buzzer should beep.
        """
        try:
            if duration == 0:
                self.bus.write_byte_data(self.bus_address, 0x06, 0x00)
            else:
                if duration < 0.1 or duration > 5:
                    raise ValueError(f'Duration must be between 0.1 and 5 seconds. Given: {duration} seconds.')
                # duration * 10: convert seconds to deciseconds (= 0.1 seconds)
                self.bus.write_byte_data(self.bus_address, 0x06, duration * 10 & 0xff)
        except:
            print('set_beep I2C error')
