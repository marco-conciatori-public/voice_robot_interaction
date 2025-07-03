function_list = [
    {
        "name": "beep",
        "description": "Makes the robot emit a beeping sound for a specified duration.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "The duration of the beep in seconds.",
                    "minimum": 0,
                    "maximum": 5
                }
            },
            "required": ["seconds"]
        }
    },
    {
        "name": "move_arm",
        "description": "Moves the point of the arm (gripper) along the specified axes.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "x_axis": {
                    "type": "number",
                    "description": "Movement along the X-axis (left/right).",
                    "minimum": -1,
                    "maximum": 1
                },
                "y_axis": {
                    "type": "number",
                    "description": "Movement along the Y-axis (forward/backward).",
                    "minimum": -1,
                    "maximum": 1
                },
                "z_axis": {
                    "type": "number",
                    "description": "Movement along the Z-axis (up/down).",
                    "minimum": -1,
                    "maximum": 1
                }
            },
            "required": []
        }
    },
    {
        "name": "control_gripper",
        "description": "Controls the rotation of the gripper and its open/close state.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "rotation": {
                    "type": "integer",
                    "description": "The rotation angle of the gripper.",
                    "minimum": 0,
                    "maximum": 180
                },
                "opening": {
                    "type": "boolean",
                    "description": "Whether to open (True) or close (False) the gripper.",
                }
            },
            "required": []
        }
    },
    {
        "name": "next_mode",
        "description": "Switches the robot to the next main operating mode in its predefined sequence.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "set_target",
        "description": "Set a target for the robot from a predefined list. The robot will use an object detection "
                       "model to find this target.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target": {
                    "type": "string",
                    "enum": ["person", "cat", "orange"],
                    "description": "The target to set for the robot. Must be selected from the predefined targets."
                },
            },
            "required": ["target"]
        }
    },
    {
        "name": "increase_speed_coefficient",
        "description": "Slightly increases the robot's speed coefficient. This affects all movements and increases the "
                       "maximum allowed speed.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "decrease_speed_coefficient",
        "description": "Slightly decreases the robot's speed coefficient. This affects all movements and decreases the "
                       "maximum allowed speed.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "set_movement_with_duration",
        "description": "Sets the speed for the robot along the X (forward/backward), Y (left/right translation), and Z"
                       " (rotation) axes. The movement will automatically stop after the specified duration.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "duration": {
                    "type": "number",
                    "description": "The duration of the movement in seconds. After this time, the robot will stop "
                                   "moving.",
                    "minimum": 0.1,
                    "maximum": 5
                },
                "speed_x": {
                    "type": "number",
                    "description": "Move forward (positive value) or move backward (negative value) in the direction "
                                   "the robot is currently facing.",
                    "minimum": -1,
                    "maximum": 1
                },
                "speed_y": {
                    "type": "number",
                    "description": "Move to the right (positive value) or move to the left (negative value) with "
                                   "respect to the direction the robot is currently facing (without rotating).",
                    "minimum": -1,
                    "maximum": 1
                },
                "speed_z": {
                    "type": "number",
                    "description": "Rotate the robot (change the direction the robot is facing). Positive values "
                                   "rotate the robot to the right, negative values rotate it to the left.",
                    "minimum": -1,
                    "maximum": 1
                }
            },
            "required": ["duration"]
        }
    }
]
