import yaml
import copy
import argparse

import utils


def import_args(yaml_path: str = None, caller_name: str = None, read_from_command_line: bool = False, **kwargs) -> dict:
    # read data from yaml config file
    # it will use either yaml_path or caller_name, one and only one must be supplied
    # caller_name is expected to be __file__ of the calling script
    # if the file is not found, it will try to go up one level and look for the file again (up to max_iterations times)
    assert caller_name is not None or yaml_path is not None, 'Either yaml_path or caller_name must be supplied'
    assert caller_name is None or yaml_path is None, 'Only one of yaml_path or caller_name can be supplied'
    if caller_name is not None:
        yaml_path = utils.get_yaml_path(caller_name)

    max_iterations = 5
    level_up = 0
    data_dict = None
    while data_dict is None:
        try:
            with open(yaml_path) as f:
                data_dict = yaml.safe_load(f)
        except FileNotFoundError:
            print(f'File "{yaml_path}" not found. Trying to go up one level...')
            if level_up == max_iterations:
                raise
            level_up += 1
            yaml_path = '../' + yaml_path

    if read_from_command_line:
        # command line arguments have priority over yaml arguments
        data_dict = from_command_line(default_data_dict=data_dict)

    # function arguments have priority over yaml AND command line arguments
    data_dict = from_function_arguments(default_data_dict=data_dict, **kwargs)

    try:
        verbose = data_dict['verbose']
    except KeyError:
        verbose = 0
    if verbose >= 3:
        print(f'Yaml config file: "{yaml_path}"')
        print('Imported parameters:')
        utils.pretty_print_dict(data_dict)

    return data_dict


def from_command_line(default_data_dict: dict) -> dict:
    parser = argparse.ArgumentParser()
    for key in default_data_dict:
        value = default_data_dict[key]
        parser.add_argument(f'--{key}', dest=key, type=type(value))

    updated_data_dict = copy.deepcopy(default_data_dict)
    args = parser.parse_args()
    args_dict = vars(args)
    for key in args_dict:
        if args_dict[key] is not None:
            updated_data_dict[key] = args_dict[key]

    return updated_data_dict


def from_function_arguments(default_data_dict: dict, **kwargs) -> dict:
    updated_data_dict = copy.deepcopy(default_data_dict)
    for key in kwargs:
        updated_data_dict[key] = kwargs[key]

    return updated_data_dict
