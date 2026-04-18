import types
import unittest
import os
from unittest.mock import patch

import worker


class WorkerBookTests(unittest.TestCase):
    def test_engine_settings_adds_bookfile_and_bookonthefly(self):
        config = types.SimpleNamespace(
            syzygy_max=0,
            workload={
                "test": {
                    "type": "GAMES",
                    "syzygy_wdl": "DISABLED",
                    "book": {"name": "startpos.epd"},
                    "dev": {
                        "options": "Threads=1 Hash=16",
                        "network": "",
                        "private": False,
                        "engine": "tanuki-",
                        "book": "ABCDEF12",
                        "book_name": "dev-book.db",
                        "time_control": "8.0+0.08",
                    },
                }
            },
        )

        with patch.object(worker, "scale_time_control", return_value="tc"):
            command = worker.MatchRunner.engine_settings(config, "engine.exe", "dev", 1.0, 0)

        normalized = command.replace("\\", "/")
        self.assertIn(
            "option.BookFile=ABCDEF12",
            normalized,
        )
        self.assertIn("option.BookDir=../Books", normalized)
        self.assertNotIn("option.BookOnTheFly=", normalized)

    def test_safe_download_engine_book_uses_books_api(self):
        config = types.SimpleNamespace(
            server="https://example.com",
            username="tester",
            password="secret",
            workload={
                "test": {
                    "dev": {
                        "engine": "tanuki-",
                        "book": "ABCDEF12",
                        "book_name": "dev-book.db",
                    }
                }
            },
        )

        with patch.object(worker.utils, "download_book") as download_book:
            book_path = worker.safe_download_engine_book(config, "dev")

        self.assertEqual(book_path, os.path.join("Books", "ABCDEF12"))
        download_book.assert_called_once_with(
            "https://example.com",
            "tester",
            "secret",
            "tanuki-",
            "dev-book.db",
            "ABCDEF12",
            os.path.join("Books", "ABCDEF12"),
        )


if __name__ == "__main__":
    unittest.main()
