"""Load an administrator-installed local engine without fetching or compiling."""

import hashlib
import json
import re
import stat
from pathlib import Path

SOURCE_PREFIX = 'goal-local-v1:'
UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
SHA_PATTERN = r'[0-9a-f]{64}'
SOURCE_PATTERN = re.compile(SOURCE_PREFIX + '(' + UUID_PATTERN + '):(' + SHA_PATTERN + ')')


class LocalEngineError(Exception):
    """A fixed diagnostic that never includes private paths or file contents."""

    def __init__(self):
        super().__init__('Goal local engine identity is unavailable or differs')


def parse_source(value):
    match = SOURCE_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise LocalEngineError()
    return match.groups()


def descriptor(value):
    if not isinstance(value, dict) or set(value) != {
        'kind', 'artifact_id', 'binary_sha256', 'name', 'bench',
    }:
        raise LocalEngineError()
    if (
        value['kind'] != 'local_private'
        or not isinstance(value['artifact_id'], str)
        or re.fullmatch(UUID_PATTERN, value['artifact_id']) is None
        or not isinstance(value['binary_sha256'], str)
        or re.fullmatch(SHA_PATTERN, value['binary_sha256']) is None
        or value['name'] != 'goal-local-' + value['artifact_id']
        or type(value['bench']) is not int
        or not 1 <= value['bench'] <= 2**63 - 1
    ):
        raise LocalEngineError()
    return dict(value)


def source_uri(value):
    value = descriptor(value)
    return SOURCE_PREFIX + value['artifact_id'] + ':' + value['binary_sha256']


def _regular(path, directory=False):
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or (not directory and info.st_nlink != 1)
    ):
        raise LocalEngineError()
    return info


def load_installed(side, worker_root=None):
    """Verify the complete binary on every load; never reuse the public cache path.

    The fixed maintenance adapter installs both files while workers are quiescent.
    The worker has no install, compile, download, repair, or retry fallback here.
    """
    try:
        artifact_id, binary_sha = parse_source(side['source'])
        identity = descriptor({
            'kind': 'local_private', 'artifact_id': artifact_id,
            'binary_sha256': binary_sha, 'name': side['name'], 'bench': side['bench'],
        })
        if side['sha'] != binary_sha or side['private'] is not False:
            raise LocalEngineError()
        root = Path.cwd() if worker_root is None else Path(worker_root)
        root = root.absolute()
        for parent in (*reversed(root.parents), root):
            _regular(parent, directory=True)
        engines = root / 'Engines'
        metadata_root = root / 'PrivateEngines'
        _regular(engines, directory=True)
        _regular(metadata_root, directory=True)
        metadata = metadata_root / (artifact_id + '.json')
        if _regular(metadata).st_size > 4096:
            raise LocalEngineError()
        record = json.loads(metadata.read_text(encoding='utf-8'))
        if (
            not isinstance(record, dict)
            or set(record) != {'schema_version', 'descriptor', 'binary_size'}
            or type(record['schema_version']) is not int
            or record['schema_version'] != 1
            or descriptor(record['descriptor']) != identity
            or type(record['binary_size']) is not int
            or not 1 <= record['binary_size'] <= 512 * 1024**2
        ):
            raise LocalEngineError()
        filename = 'goal-local-' + artifact_id + '-' + binary_sha + '.exe'
        binary = engines / filename
        before = _regular(binary)
        if before.st_size != record['binary_size']:
            raise LocalEngineError()
        digest = hashlib.sha256()
        with binary.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024**2), b''):
                digest.update(chunk)
        after = _regular(binary)
        if (
            digest.hexdigest() != binary_sha
            or (before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise LocalEngineError()
        return filename
    except (KeyError, TypeError, ValueError, OSError, LocalEngineError):
        raise LocalEngineError() from None
