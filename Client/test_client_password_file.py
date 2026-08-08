import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Client import client


class PasswordFileTests(unittest.TestCase):

    def test_parse_arguments_reads_password_file(self):
        with tempfile.TemporaryDirectory() as directory:
            password_file = Path(directory) / 'worker-password'
            password_file.write_text('local-worker-secret', encoding='utf-8')
            environment = {
                'OPENBENCH_USERNAME': 'worker',
                'OPENBENCH_PASSWORD_FILE': str(password_file.resolve()),
                'OPENBENCH_SERVER': 'http://127.0.0.1:8001',
            }
            with patch.dict(os.environ, environment, clear=True), patch.object(sys, 'argv', ['client.py']):
                args = client.parse_arguments()

        self.assertEqual(args.username, 'worker')
        self.assertEqual(args.password, 'local-worker-secret')
        self.assertEqual(args.server, 'http://127.0.0.1:8001')

    def test_password_file_rejects_multiple_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            password_file = Path(directory) / 'worker-password'
            password_file.write_text('first\nsecond', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'one password'):
                client.read_password_file(str(password_file.resolve()))

    def test_password_inputs_are_mutually_exclusive(self):
        environment = {
            'OPENBENCH_USERNAME': 'worker',
            'OPENBENCH_PASSWORD': 'environment-secret',
            'OPENBENCH_PASSWORD_FILE': 'C:\\not-used',
            'OPENBENCH_SERVER': 'http://127.0.0.1:8001',
        }
        with patch.dict(os.environ, environment, clear=True), self.assertRaisesRegex(
            ValueError, 'only one',
        ):
            client.parse_arguments()
