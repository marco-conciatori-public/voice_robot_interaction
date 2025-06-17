def get_api_key(file_path: str) -> str:
    """
    Reads the API key from a file.

    :param file_path: Path to the file containing the API key.
    :return: The API key as a string.
    """
    try:
        with open(file_path, 'r') as file:
            api_key = file.read().strip()
        return api_key
    except FileNotFoundError:
        raise FileNotFoundError(f'API key file not found: {file_path}')
    except Exception as e:
        raise Exception(f'Error reading API key from file:\n{e}')
