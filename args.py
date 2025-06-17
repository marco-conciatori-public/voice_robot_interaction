import yaml
import copy
import argparse

import utils


def import_args(yaml_path: str, read_from_command_line: bool = False, **kwargs) -> dict:
    # read data from yaml config file
    with open(yaml_path) as f:
        data_dict = yaml.safe_load(f)

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
