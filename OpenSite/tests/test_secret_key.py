import json
import os
import tempfile
import unittest
from contextlib import contextmanager

from OpenSite.secret_key import load_secret_key


SECRET_ENVIRONMENT_NAMES = (
    "SHOGIBENCH_DJANGO_SECRET_KEY",
    "SHOGIBENCH_DJANGO_SECRET_KEY_FILE",
    "SHOGIBENCH_LOCAL_CONFIG_PATH",
)


@contextmanager
def isolated_secret_environment():
    previous = {name: os.environ.get(name) for name in SECRET_ENVIRONMENT_NAMES}
    for name in SECRET_ENVIRONMENT_NAMES:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name in SECRET_ENVIRONMENT_NAMES:
            os.environ.pop(name, None)
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


class LoadSecretKeyTests(unittest.TestCase):
    def test_reads_direct_environment_value_first(self):
        expected = "environment-" + "x" * 64
        with isolated_secret_environment():
            os.environ["SHOGIBENCH_DJANGO_SECRET_KEY"] = expected
            os.environ["SHOGIBENCH_DJANGO_SECRET_KEY_FILE"] = "missing"
            self.assertEqual(load_secret_key("unused"), expected)

    def test_reads_explicit_secret_file(self):
        expected = "explicit-file-" + "x" * 64
        with tempfile.TemporaryDirectory() as directory:
            secret_path = os.path.join(directory, "signing-key")
            with open(secret_path, "w", encoding="utf-8") as secret_file:
                secret_file.write(expected)

            with isolated_secret_environment():
                os.environ["SHOGIBENCH_DJANGO_SECRET_KEY_FILE"] = secret_path
                self.assertEqual(load_secret_key(directory), expected)

    def test_reads_secret_path_from_production_local_config(self):
        expected = "local-config-" + "x" * 64
        with tempfile.TemporaryDirectory() as directory:
            secret_path = os.path.join(directory, "signing-key")
            config_path = os.path.join(directory, "local.json")
            with open(secret_path, "w", encoding="utf-8") as secret_file:
                secret_file.write(expected)
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump({"django_signing_key_path": secret_path}, config_file)

            with isolated_secret_environment():
                os.environ["SHOGIBENCH_LOCAL_CONFIG_PATH"] = config_path
                self.assertEqual(load_secret_key(directory), expected)

    def test_reads_default_untracked_file(self):
        expected = "default-file-" + "x" * 64
        with tempfile.TemporaryDirectory() as directory:
            secret_path = os.path.join(directory, ".django-secret-key")
            with open(secret_path, "w", encoding="utf-8") as secret_file:
                secret_file.write(expected)

            with isolated_secret_environment():
                self.assertEqual(load_secret_key(directory), expected)

    def test_rejects_short_secret(self):
        with isolated_secret_environment():
            os.environ["SHOGIBENCH_DJANGO_SECRET_KEY"] = "too-short"
            with self.assertRaisesRegex(RuntimeError, "at least 50"):
                load_secret_key("unused")

    def test_missing_secret_error_does_not_expose_path(self):
        private_path = os.path.join("private", "missing-signing-key")
        with isolated_secret_environment():
            os.environ["SHOGIBENCH_DJANGO_SECRET_KEY_FILE"] = private_path
            with self.assertRaises(RuntimeError) as raised:
                load_secret_key("unused")
        self.assertNotIn(private_path, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
