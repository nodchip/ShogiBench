import contextlib
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

CLIENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if CLIENT_DIRECTORY not in sys.path:
    sys.path.insert(0, CLIENT_DIRECTORY)

import worker


class WorkerCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.previous = os.getcwd()
        self.addCleanup(os.chdir, self.previous)
        os.chdir(self.temporary.name)
        for name in ('PGNs', 'Engines', 'Networks'):
            Path(name).mkdir()

    def age(self, path, days):
        timestamp = time.time() - days * 86400
        os.utime(path, (timestamp, timestamp))

    def test_preserves_old_eval_directory_and_model_hard_link(self):
        model = Path('Networks/model')
        model.write_bytes(b'model fixture')
        evaluation = Path('Networks/model.eval')
        evaluation.mkdir()
        linked = evaluation / 'nn.bin'
        os.link(model, linked)
        self.age(evaluation, 29)
        self.age(model, 29)
        worker.cleanup_client()
        self.assertTrue(evaluation.is_dir())
        self.assertEqual(linked.read_bytes(), b'model fixture')
        self.assertFalse(model.exists())

    def test_retains_recent_and_removes_expired_regular_files(self):
        for directory, days in (('PGNs', 1), ('Engines', 7), ('Networks', 28)):
            recent = Path(directory) / 'recent'
            expired = Path(directory) / 'expired'
            recent.touch()
            expired.touch()
            self.age(expired, days + 1)
        worker.cleanup_client()
        for directory in ('PGNs', 'Engines', 'Networks'):
            self.assertTrue((Path(directory) / 'recent').exists())
            self.assertFalse((Path(directory) / 'expired').exists())

    def test_locked_file_does_not_prevent_other_cleanup_or_return(self):
        locked = Path('PGNs/private-name')
        following = Path('Networks/expired')
        for path in (locked, following):
            path.touch()
            self.age(path, 29)
        original_remove = os.remove

        def remove(path):
            if Path(path) == locked:
                raise PermissionError('private-name must never be printed')
            return original_remove(path)

        output = io.StringIO()
        with patch.object(worker.os, 'remove', side_effect=remove):
            with contextlib.redirect_stdout(output):
                worker.cleanup_client()
        self.assertTrue(locked.exists())
        self.assertFalse(following.exists())
        self.assertEqual(output.getvalue(), 'Cache file cleanup deferred\n')

    def test_inaccessible_directory_does_not_prevent_other_cleanup(self):
        following = Path('Networks/expired')
        following.touch()
        self.age(following, 29)
        original_scandir = os.scandir

        def scandir(path):
            if path == 'PGNs':
                raise PermissionError('private directory')
            return original_scandir(path)

        output = io.StringIO()
        with patch.object(worker.os, 'scandir', side_effect=scandir):
            with contextlib.redirect_stdout(output):
                worker.cleanup_client()
        self.assertFalse(following.exists())
        self.assertEqual(output.getvalue(), 'Cache directory cleanup deferred\n')

    def test_symlink_is_never_followed_or_removed(self):
        target = Path('target')
        target.write_bytes(b'outside cache')
        self.age(target, 29)
        link = Path('Networks/link')
        try:
            link.symlink_to(target.resolve())
        except OSError:
            self.skipTest('symlink creation requires platform permission')
        worker.cleanup_client()
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_bytes(), b'outside cache')

    def test_non_regular_entries_are_skipped_without_stat_or_unlink(self):
        entry = Mock()
        entry.is_file.return_value = False
        with patch.object(worker.os, 'scandir') as scan:
            scan.return_value.__enter__.return_value = [entry]
            with patch.object(worker.os, 'remove') as remove:
                worker.cleanup_client()
        self.assertEqual(entry.is_file.call_count, 3)
        entry.is_file.assert_called_with(follow_symlinks=False)
        entry.stat.assert_not_called()
        remove.assert_not_called()


if __name__ == '__main__':
    unittest.main()
