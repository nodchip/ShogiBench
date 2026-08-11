import os
import sys
import unittest

CLIENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
if CLIENT_DIRECTORY not in sys.path:
    sys.path.insert(0, CLIENT_DIRECTORY)

import bench


class BenchOutputTests(unittest.TestCase):

    def test_parse_stream_output_accepts_ascii(self):
        output = b"Nodes searched  : 472847\nNodes/second    : 12345\n"
        self.assertEqual(bench.parse_stream_output(output), (472847, 12345))

    def test_parse_stream_output_ignores_cp932_diagnostic_text(self):
        output = (
            "診断メッセージ\n".encode("cp932")
            + b"Nodes searched  : 472847\nNodes/second    : 12345\n"
        )
        self.assertEqual(bench.parse_stream_output(output), (472847, 12345))


if __name__ == "__main__":
    unittest.main()
