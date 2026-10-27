from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from web_server.screencast import (
    ScreencastError,
    StreamSession,
    VideoPacket,
    ScrcpyScreencast,
    avcc_to_annexb,
    config_to_annexb,
    parse_stream_header,
    payload_to_annexb,
)


class StreamProtocolTests(unittest.TestCase):
    def test_session_header_is_parsed(self) -> None:
        header = (
            (0x80000000).to_bytes(4, "big")
            + (1080).to_bytes(4, "big")
            + (2400).to_bytes(4, "big")
        )

        session = parse_stream_header(header)

        self.assertEqual(StreamSession(1080, 2400), session)

    def test_packet_header_exposes_flags_and_pts(self) -> None:
        flags = (1 << 62) | (1 << 61) | 123456
        header = flags.to_bytes(8, "big") + (8192).to_bytes(4, "big")

        packet = parse_stream_header(header)

        self.assertEqual(
            VideoPacket(pts=123456, size=8192, config=True, key_frame=True),
            packet,
        )

    def test_invalid_packet_size_is_rejected(self) -> None:
        header = (0).to_bytes(8, "big") + (0).to_bytes(4, "big")

        with self.assertRaises(ScreencastError):
            parse_stream_header(header)

    def test_avcc_payload_is_converted_to_annex_b(self) -> None:
        data = b"\x00\x00\x00\x03abc\x00\x00\x00\x02de"

        converted = avcc_to_annexb(data, 4)

        self.assertEqual(
            b"\x00\x00\x00\x01abc\x00\x00\x00\x01de",
            converted,
        )
        self.assertEqual(converted, payload_to_annexb(data))
        self.assertEqual(
            b"\x00\x00\x00\x01frame",
            payload_to_annexb(b"\x00\x00\x00\x01frame"),
        )

    def test_avcc_config_is_converted_to_annex_b(self) -> None:
        sps = b"\x67\x64\x00\x1f"
        pps = b"\x68\xee\x06\xf2"
        config = (
            bytes([1, 0x64, 0x00, 0x1F, 0xFF, 0xE1])
            + len(sps).to_bytes(2, "big")
            + sps
            + bytes([1])
            + len(pps).to_bytes(2, "big")
            + pps
        )

        annexb, length_size = config_to_annexb(config)

        self.assertEqual(4, length_size)
        self.assertEqual(
            b"\x00\x00\x00\x01" + sps + b"\x00\x00\x00\x01" + pps,
            annexb,
        )

    def test_annex_b_config_is_passed_through(self) -> None:
        config = b"\x00\x00\x00\x01\x67\x64\x00\x1f\x00\x00\x00\x01\x68\xee"

        self.assertEqual((config, 4), config_to_annexb(config))


class ScreencastManagerTests(unittest.TestCase):
    def test_missing_server_reports_an_error_without_using_adb(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ScrcpyScreencast(
                root / "missing-adb.exe",
                root / "missing-scrcpy-server",
            )

            with self.assertRaises(ScreencastError):
                manager.subscribe()

            status = manager.status()
            self.assertEqual("error", status["state"])
            self.assertIn("scrcpy", status["message"])
            manager.close()
            self.assertEqual("idle", manager.status()["state"])


if __name__ == "__main__":
    unittest.main()
