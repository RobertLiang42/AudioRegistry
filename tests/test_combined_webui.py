import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audio_registry.combined_webui import serve_both_webuis
from audio_registry.i18n import t


class CombinedWebUiTests(unittest.TestCase):
    def test_two_servers_start_and_stop_together(self):
        review_app = SimpleNamespace(close=Mock())
        review_server = SimpleNamespace(
            server_port=8765, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        assembly_server = SimpleNamespace(
            server_port=8766, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        with (
            patch("audio_registry.combined_webui.ReviewApplication", return_value=review_app),
            patch("audio_registry.combined_webui.AssemblyApplication"),
            patch("audio_registry.combined_webui.ReviewServer", return_value=review_server),
            patch("audio_registry.combined_webui.AssemblyServer", return_value=assembly_server),
        ):
            serve_both_webuis(
                Path("movie.wav"), SimpleNamespace(), project_name="movie", open_browser=False
            )
        review_server.serve_forever.assert_called_once_with(poll_interval=0.25)
        assembly_server.serve_forever.assert_called_once_with(poll_interval=0.25)
        review_server.shutdown.assert_called_once()
        assembly_server.shutdown.assert_called_once()
        review_app.close.assert_called_once()

    def test_combined_webui_rejects_same_port(self):
        with self.assertRaisesRegex(ValueError, re.escape(t("errors.ports_different"))):
            serve_both_webuis(
                Path("movie.wav"), SimpleNamespace(), project_name="movie",
                webui1_port=8765, webui2_port=8765, open_browser=False,
            )

    def test_process_launch_can_preselect_new_project_in_assembly(self):
        review_app = SimpleNamespace(close=Mock())
        review_server = SimpleNamespace(
            server_port=8765, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        assembly_server = SimpleNamespace(
            server_port=8766, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        with (
            patch("audio_registry.combined_webui.ReviewApplication", return_value=review_app),
            patch("audio_registry.combined_webui.AssemblyApplication"),
            patch("audio_registry.combined_webui.ReviewServer", return_value=review_server),
            patch("audio_registry.combined_webui.AssemblyServer", return_value=assembly_server),
            patch("audio_registry.combined_webui.webbrowser.open") as opened,
        ):
            serve_both_webuis(
                Path("movie.wav"), SimpleNamespace(), project_name="电影 一",
                assembly_project_name="电影 一", open_browser=True,
            )
        self.assertEqual(opened.call_count, 2)
        self.assertIn("initial_project=%E7%94%B5%E5%BD%B1+%E4%B8%80", opened.call_args_list[1].args[0])

    def test_direct_combined_launch_explicitly_starts_assembly_blank(self):
        review_app = SimpleNamespace(close=Mock())
        review_server = SimpleNamespace(
            server_port=8765, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        assembly_server = SimpleNamespace(
            server_port=8766, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        with (
            patch("audio_registry.combined_webui.ReviewApplication", return_value=review_app),
            patch("audio_registry.combined_webui.AssemblyApplication"),
            patch("audio_registry.combined_webui.ReviewServer", return_value=review_server),
            patch("audio_registry.combined_webui.AssemblyServer", return_value=assembly_server),
            patch("audio_registry.combined_webui.webbrowser.open") as opened,
        ):
            serve_both_webuis(
                None, SimpleNamespace(), project_name=None, open_browser=True,
            )
        self.assertTrue(opened.call_args_list[1].args[0].endswith("/?initial_blank=1"))

    def test_batch_process_can_preselect_all_new_projects_in_assembly(self):
        review_app = SimpleNamespace(close=Mock())
        review_server = SimpleNamespace(
            server_port=8765, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        assembly_server = SimpleNamespace(
            server_port=8766, serve_forever=Mock(), shutdown=Mock(), server_close=Mock()
        )
        with (
            patch("audio_registry.combined_webui.ReviewApplication", return_value=review_app),
            patch("audio_registry.combined_webui.AssemblyApplication"),
            patch("audio_registry.combined_webui.ReviewServer", return_value=review_server),
            patch("audio_registry.combined_webui.AssemblyServer", return_value=assembly_server),
            patch("audio_registry.combined_webui.webbrowser.open") as opened,
        ):
            serve_both_webuis(
                Path("second.wav"), SimpleNamespace(), project_name="项目二",
                assembly_project_name=["项目一", "项目二"], open_browser=True,
            )
        url = opened.call_args_list[1].args[0]
        self.assertIn("initial_project=%E9%A1%B9%E7%9B%AE%E4%B8%80", url)
        self.assertIn("initial_project=%E9%A1%B9%E7%9B%AE%E4%BA%8C", url)


if __name__ == "__main__":
    unittest.main()
