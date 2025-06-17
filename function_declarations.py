buzzer_function = {
    'name': 'set_beep',
    'description': 'Control the buzzer of the robot. It can emit only one type of sound, the only parameter that can '
                   'be controlled is if it is active or not.',
    'parameters': {
        'type': 'object',
        'properties': {
            'on_time': {
                'type': 'number',
                'minimum': 0,
                'description': 'Beep duration. on_time=0: turn off the buzzer. on_time=1: the buzzer keeps '
                               'ringing. on_time >=10: automatically closes after "on_time" milliseconds. For the '
                               'last case, on_time must be a multiple of 10.',
            },
        },
        'required': ['on_time'],
    },
}

move_function = {
    'name': 'set_car_motion',
    'description': 'Move the robot by specifying its speed along the forward-backward axis, its speed along the '
                   'left-right axis (it can translate left or right without rotating), and its speed of left-right '
                   'rotation.',
    'parameters': {
        'type': 'object',
        'properties': {
            'v_x': {
                'type': 'number',
                'minimum': -1,
                'maximum': 1,
                'description': 'Velocity of the robot along the forward-backward axis. Positive values move the '
                               'robot forward, negative values move it backward. The absolute value of v_x '
                               'represents the speed of the robot movement along this axis. A value of 0 means the '
                               'robot is stationary along this axis.',

            },
            'v_y': {
                'type': 'number',
                'minimum': -1,
                'maximum': 1,
                'description': 'Velocity of the robot along the left-right axis. Positive values move the robot to the '
                               'left, negative values move it to the right. The absolute value of v_y represents the '
                               'speed of the robot movement along this axis. A value of 0 means the robot is '
                               'stationary along this axis.',
            },
            'v_z': {
                'type': 'number',
                'minimum': -5,
                'maximum': 5,
                'description': 'Speed of left-right rotation along the vertical axis of the robot. Positive values '
                               'rotate the robot to the left, negative values rotate it to the right. The absolute '
                               'value of v_z represents the speed of the rotation. A value of 0 means the robot is '
                               'stationary along this axis.',
            },
        },
        'required': ['v_x', 'v_y', 'v_z'],
    },
}

function_list = [buzzer_function, move_function]
