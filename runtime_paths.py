"""Resolve the local dashboard data directory."""
import os
from pathlib import Path


def get_data_dir(base_dir=None):
    override = os.environ.get('QUOTACANVAS_DATA_DIR')
    if override:
        directory = Path(override).expanduser()
        if not directory.is_absolute():
            raise ValueError('QUOTACANVAS_DATA_DIR must be an absolute path')
        return directory
    return (Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent) / 'data'
