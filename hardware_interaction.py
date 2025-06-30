#!/usr/bin/env python3
# coding: utf-8
import smbus

import args
import global_constants as gc


class HardwareInteraction:
    def __init__(self):
        parameters = args.import_args(yaml_path=gc.CONFIG_FOLDER_PATH + 'hardware_interaction.yaml')
        self.bus_address = parameters['bus_address']
        self.bus = smbus.SMBus(parameters['bus_number'])

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

    # PWD servo control servo_id: 1-6 (0 controls all servos). Angle: 0-180
    def pwm_servo_write(self, servo_id: int, angle: int) -> None:
        try:
            if servo_id == 0:
                self.bus.write_byte_data(self.bus_address, 0x57, angle & 0xff)
            else:
                self.bus.write_byte_data(self.bus_address, 0x50 + servo_id, angle & 0xff)
        except:
            print('arm_pwm_servo_write I2C error')

    # Turn on the buzzer, the default delay is 0xff (=255), and the buzzer keeps ringing
    # delay=1~50, the buzzer will be automatically turned off after delay*100 milliseconds after the buzzer is turned
    # on, and the maximum delay time is 5 seconds.
    def buzzer_on(self, delay: int = 0xff):
        try:
            if delay != 0:
                self.bus.write_byte_data(self.bus_address, 0x06, delay & 0xff)
        except:
            print('arm_buzzer_on I2C error')

    # Turn off the buzzer
    def buzzer_off(self):
        try:
            self.bus.write_byte_data(self.bus_address, 0x06, 0x00)
        except:
            print('arm_buzzer_off I2C error')
