"""Paths resolve against the project (or custom config file's directory)."""
import json
import logging
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = dict(host='127.0.0.1', port=5000, storage_dir='storage',
                database='data/metadata.sqlite3', download_dir='downloads',
                log_file='logs/server.log', log_level='INFO', chunk_size=65536,
                max_file_size=1073741824, socket_timeout=120,
                max_clients=64, max_resources=10000)

def load_config(filename=None):
    path = Path(filename).resolve() if filename else ROOT / 'config/config.json'
    config = DEFAULTS.copy()
    if path.exists():
        config.update(json.loads(path.read_text(encoding='utf-8')))
    base = path.parent.parent if path.parent.name == 'config' else path.parent
    for name in ('storage_dir', 'database', 'download_dir', 'log_file'):
        config[name] = str((base / config[name]).resolve())
    for key, low, high in (('port', 0, 65535), ('chunk_size', 1024, 262144),
                           ('max_file_size', 0, 2**40), ('socket_timeout', 1, 3600),
                           ('max_clients', 1, 1024), ('max_resources', 1, 10000)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError('Invalid configuration: ' + key)
    if not isinstance(config['host'], str) or not config['host']:
        raise ValueError('Invalid host')
    for name in ('database', 'log_file'):
        if Path(config[name]).is_relative_to(Path(config['storage_dir'])):
            raise ValueError(name + ' must be outside storage_dir')
    return config

def configure_logging(config):
    Path(config['log_file']).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('file_sharing.' + config['log_file'])
    logger.setLevel(config['log_level'])
    logger.propagate = False
    if not logger.handlers:
        fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        for handler in (logging.FileHandler(config['log_file'], encoding='utf-8'),
                        logging.StreamHandler()):
            handler.setFormatter(fmt)
            logger.addHandler(handler)
    return logger
