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
        "name": "set_arm_joint_angles",
        "description": "Sets the desired angles for the robot's arm joints. There are six joints. You can change all "
                       "of them or only a subset. Angles are expressed in degrees between 0 and 180.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "base_rotation": {
                    "type": "integer",
                    "description": "The rotation angle of the arm's base.",
                    "minimum": 0,
                    "maximum": 180
                },
                "base_inclination": {
                    "type": "integer",
                    "description": "The inclination (up/down) angle of the arm's base.",
                    "minimum": 0,
                    "maximum": 180
                },
                "elbow_1_inclination": {
                    "type": "integer",
                    "description": "The inclination angle of the first elbow joint.",
                    "minimum": 0,
                    "maximum": 180
                },
                "elbow_2_inclination": {
                    "type": "integer",
                    "description": "The inclination angle of the second elbow joint.",
                    "minimum": 0,
                    "maximum": 180
                },
                "gripper_rotation": {
                    "type": "integer",
                    "description": "The rotation angle of the gripper.",
                    "minimum": 0,
                    "maximum": 180
                },
                "gripper_opening": {
                    "type": "integer",
                    "description": "The opening angle of the gripper.",
                    "minimum": 0,
                    "maximum": 180
                }
            },
            "required": []
        }
    },
    {
        "name": "change_light_effect",
        "description": "Cycles to the next available light effect on the robot's internal lights. If they are off, "
                       "they are turned on with the first effect.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
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
        "description": "Slightly increases the robot's speed coefficient. This affects all movements.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "decrease_speed_coefficient",
        "description": "Slightly decreases the robot's speed coefficient. This affects all movements.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "toggle_lidar_listener",
        "description": "Start or stop reading and using data from the LIDAR sensor.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "set_speed",
        "description": "Sets the speed for the robot along the X (forward/backward), Y (left/right translation), and Z"
                       " (rotation) axes.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
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
            "required": []
        }
    }
]
