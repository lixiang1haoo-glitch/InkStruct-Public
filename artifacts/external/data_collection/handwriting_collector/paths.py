"""Keep Windows file publication valid beyond the legacy MAX_PATH boundary."""
import os
from pathlib import Path


def native_path(path):
    absolute = str(Path(path).resolve())
    if os.name != 'nt' or absolute.startswith('\\\\?\\'):
        return absolute
    if absolute.startswith('\\\\'):
        return '\\\\?\\UNC\\' + absolute[2:]
    return '\\\\?\\' + absolute
