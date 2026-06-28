"""
Thin shim over the shared config loader in robot_link.

The real implementation lives in robot_link/config.py (shared with the RDK X3 via the
git submodule). This module is kept only so existing ``import args`` /
``args.import_args(...)`` call sites keep working unchanged. It injects this repo's
CONFIG_FOLDER_PATH so robot_link.config stays repo-agnostic.
"""

import global_constants as gc
from robot_link import config as _config
from robot_link.config import from_command_line, from_function_arguments  # re-exported for callers


def import_args(yaml_path: str = None,
                caller_name: str = None,
                read_from_command_line: bool = False,
                **kwargs) -> dict:
    return _config.import_args(
        yaml_path=yaml_path,
        caller_name=caller_name,
        config_folder=gc.CONFIG_FOLDER_PATH,
        read_from_command_line=read_from_command_line,
        **kwargs,
    )
