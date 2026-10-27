from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import queue
from unittest.mock import Mock, patch

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


class H264SubscriptionTests(unittest.TestCase):
    CONFIG = b"\x00\x00\x00\x01\x67\x42\x00\x1e\x00\x00\x00\x01\x68\xee"
    KEY = b"\x00\x00\x00\x01\x65\x88"
    DELTA = b"\x00\x00\x00\x01\x41\x99"

    def setUp(self):
        from web_server.screencast import FrameSubscriber
        self.manager = ScrcpyScreencast("adb", "server")
        self.manager._width, self.manager._height = 320, 240
        self.sub = FrameSubscriber(1, queue.Queue(maxsize=2), codec="h264")
        self.manager._subscribers[1] = self.sub
        self.manager._set_config(self.CONFIG)

    def test_new_subscriber_waits_for_keyframe_and_gets_complete_bootstrap(self):
        from web_server.screencast import encode_packet, encode_session
        self.manager._publish_h264(self.DELTA, 100, False)
        self.assertTrue(self.sub.frames.empty())
        self.manager._publish_h264(self.KEY, 12345678901234, True)
        self.assertEqual(self.sub.frames.get_nowait(), encode_session(320, 240)
                         + encode_packet(self.CONFIG, config=True)
                         + encode_packet(self.KEY, 12345678901234, key_frame=True))
        self.manager._publish_h264(self.DELTA, 12345678934567, False)
        self.assertEqual(parse_stream_header(self.sub.frames.get_nowait()[:12]).pts, 12345678934567)

    def test_overflow_discards_gop_and_waits_for_next_keyframe(self):
        self.manager._publish_h264(self.KEY, 0, True)
        self.manager._publish_h264(self.DELTA, 1, False)
        self.manager._publish_h264(self.DELTA, 2, False)
        self.assertTrue(self.sub.frames.empty())
        self.assertTrue(self.sub.waiting_keyframe)
        self.manager._publish_h264(self.DELTA, 3, False)
        self.assertTrue(self.sub.frames.empty())
        self.manager._publish_h264(self.KEY, 4, True)
        self.assertIsInstance(parse_stream_header(self.sub.frames.get_nowait()[:12]), StreamSession)

    def test_resize_clears_old_packets_and_requires_new_config(self):
        self.manager._publish_h264(self.KEY, 100, True)
        self.manager._set_session(StreamSession(640, 480))
        self.manager._publish_h264(self.KEY, 0, True)
        self.assertTrue(self.sub.frames.empty())
        self.manager._set_config(self.CONFIG)
        self.manager._publish_h264(self.KEY, 0, True)
        self.assertEqual(parse_stream_header(self.sub.frames.get_nowait()[:12]), StreamSession(640, 480))

    def test_jpeg_publish_is_shared_and_does_not_enter_h264_queue(self):
        from web_server.screencast import FrameSubscriber
        subscribers = [FrameSubscriber(n, queue.Queue(maxsize=1)) for n in (2, 3)]
        for sub in subscribers:
            self.manager._subscribers[sub.identifier] = sub
        self.manager._publish(b"jpeg", 320, 240)
        self.assertTrue(self.sub.frames.empty())
        self.assertEqual([sub.frames.get_nowait() for sub in subscribers], [b"jpeg", b"jpeg"])

    def test_h264_only_reader_never_creates_decoder_or_encodes_jpeg(self):
        from web_server.screencast import encode_packet
        packets = [encode_packet(self.CONFIG, config=True), encode_packet(self.KEY, 99, key_frame=True)]
        data = bytearray(b"".join(packets))
        def receive(_connection, size):
            if not data:
                self.manager._stop_requested = True
                raise EOFError()
            part = bytes(data[:size])
            del data[:size]
            return part
        with patch("web_server.screencast._recv_exact", side_effect=receive), \
             patch.object(self.manager, "_new_decoder") as decoder, \
             patch("web_server.screencast.cv2.imencode") as encode:
            self.manager._reader_loop(Mock())
        decoder.assert_not_called()
        encode.assert_not_called()
        self.assertFalse(self.sub.frames.empty())

    def test_default_subscription_is_jpeg_and_h264_has_bounded_queue(self):
        self.manager._reader_thread = Mock(is_alive=Mock(return_value=True))
        self.manager._latest_jpeg = b"cached"
        with patch.object(self.manager, "_schedule_subscriber_guard_locked"):
            jpeg = self.manager.subscribe()
            h264 = self.manager.subscribe_h264()
        self.assertEqual(jpeg.codec, "jpeg")
        self.assertEqual(jpeg.frames.get_nowait(), b"cached")
        self.assertEqual(h264.codec, "h264")
        self.assertEqual(h264.frames.maxsize, 32)
        self.assertTrue(h264.frames.empty())

    def test_late_h264_subscriber_replays_current_gop_on_static_display(self):
        from web_server.screencast import encode_packet, encode_session
        self.manager._reader_thread = Mock(is_alive=Mock(return_value=True))
        self.manager._next_subscriber = 2
        self.manager._publish_h264(self.KEY, 10, True)
        self.manager._publish_h264(self.DELTA, 11, False)
        with patch.object(self.manager, "_schedule_subscriber_guard_locked"):
            late = self.manager.subscribe_h264()
        self.assertEqual(late.frames.get_nowait(), encode_session(320, 240)
                         + encode_packet(self.CONFIG, config=True)
                         + encode_packet(self.KEY, 10, key_frame=True)
                         + encode_packet(self.DELTA, 11))
        self.manager._publish_h264(self.DELTA, 12, False)
        self.assertEqual(late.frames.get_nowait(), encode_packet(self.DELTA, 12))

    def test_static_jpeg_fallback_decodes_cached_gop_once_and_shares_latest(self):
        self.manager._reader_thread = Mock(is_alive=Mock(return_value=True))
        self.manager._next_subscriber = 2
        self.manager._publish_h264(self.KEY, 10, True)
        self.manager._publish_h264(self.DELTA, 11, False)
        decoder = Mock()
        def decode(_decoder, payload):
            if payload == self.KEY or payload == self.DELTA:
                self.manager._publish(b"latest", 320, 240)
        with patch.object(self.manager, "_schedule_subscriber_guard_locked"), \
             patch.object(self.manager, "_new_decoder", return_value=decoder) as new_decoder, \
             patch.object(self.manager, "_decode", side_effect=decode) as decoded:
            first = self.manager.subscribe()
            second = self.manager.subscribe()
        self.assertEqual(first.frames.get_nowait(), b"latest")
        self.assertEqual(second.frames.get_nowait(), b"latest")
        new_decoder.assert_called_once()
        self.assertEqual([call.args[1] for call in decoded.call_args_list], [self.CONFIG, self.KEY, self.DELTA])

    def test_config_change_clears_cached_jpeg_and_gop(self):
        self.manager._publish_h264(self.KEY, 0, True)
        self.manager._latest_jpeg = b"stale"
        self.manager._set_config(self.CONFIG.replace(b"\x42", b"\x64"))
        self.assertIsNone(self.manager._latest_jpeg)
        self.assertFalse(self.manager._gop)

    def test_guard_does_not_expire_a_recent_subscriber_with_an_older_one(self):
        from web_server.screencast import FrameSubscriber
        older = FrameSubscriber(1, queue.Queue(), created_at=0)
        recent = FrameSubscriber(2, queue.Queue(), created_at=14.9)
        self.manager._subscribers = {1: older, 2: recent}
        with patch("web_server.screencast.time.monotonic", return_value=15.0), \
             patch.object(self.manager, "_schedule_subscriber_guard_locked") as schedule:
            self.manager._drop_abandoned_subscribers()
        self.assertNotIn(1, self.manager._subscribers)
        self.assertIn(2, self.manager._subscribers)
        schedule.assert_called_once()

    def test_idle_close_rechecks_subscribers_after_timer_check(self):
        self.manager._subscribers.clear()
        self.manager._reader_thread = Mock(is_alive=Mock(return_value=True))
        self.manager._next_subscriber = 2
        close = self.manager.close
        joined = []

        def subscribe_then_close(**kwargs):
            joined.append(self.manager.subscribe_h264())
            close(**kwargs)

        with patch.object(self.manager, "close", side_effect=subscribe_then_close), \
             patch.object(self.manager, "_schedule_subscriber_guard_locked"), \
             patch.object(self.manager, "_release") as release:
            self.manager._stop_after_idle()
            release.assert_not_called()
            self.assertIn(joined[0].identifier, self.manager._subscribers)
            self.assertFalse(self.manager._stop_requested)
            # Explicit shutdown still closes an active stream.
            close()
            release.assert_called_once()
        self.assertIsNone(joined[0].frames.get_nowait())

    def test_idle_close_releases_stream_without_subscribers(self):
        self.manager._subscribers.clear()
        with patch.object(self.manager, "_release") as release:
            self.manager._stop_after_idle()
        release.assert_called_once()
        self.assertTrue(self.manager._stop_requested)

    def test_h264_fanout_shares_keyframe_bootstrap_and_delta_bytes(self):
        from web_server.screencast import FrameSubscriber, encode_packet
        other = FrameSubscriber(2, queue.Queue(maxsize=2), codec="h264")
        self.manager._subscribers[2] = other
        with patch("web_server.screencast.encode_packet", wraps=encode_packet) as encode:
            self.manager._publish_h264(self.KEY, 10, True)
            self.assertEqual(2, encode.call_count)  # one keyframe and one config
            self.assertIs(self.sub.frames.get_nowait(), other.frames.get_nowait())
            encode.reset_mock()
            self.manager._publish_h264(self.DELTA, 11, False)
            encode.assert_called_once()
            self.assertIs(self.sub.frames.get_nowait(), other.frames.get_nowait())

    def test_shutdown_terminator_replaces_all_queued_h264_packets(self):
        self.manager._publish_h264(self.KEY, 0, True)
        self.manager._publish_h264(self.DELTA, 1, False)
        self.manager._offer(self.sub, None)
        self.assertIsNone(self.sub.frames.get_nowait())
        self.assertTrue(self.sub.frames.empty())


if __name__ == "__main__":
    unittest.main()
