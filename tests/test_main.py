"""Tests for the CLI helpers in micron/__main__.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_config(host: str = "0.0.0.0", port: int = 8000):
    """Minimal Config stub."""
    cfg = MagicMock()
    cfg.get = lambda key, default=None: {
        "host": host,
        "port": port,
    }.get(key, default)
    return cfg


class TestResolveServerUrl:
    def test_env_override(self):
        from micron.__main__ import _resolve_server_url
        with patch.dict(os.environ, {"MICRON_SERVER_URL": "http://remote:9000/"}):
            assert _resolve_server_url(_make_config()) == "http://remote:9000"

    def test_env_override_strips_trailing_slash(self):
        from micron.__main__ import _resolve_server_url
        with patch.dict(os.environ, {"MICRON_SERVER_URL": "http://x:1//"}):
            assert _resolve_server_url(_make_config()) == "http://x:1"

    def test_default_localhost_with_zero_dot_zero(self):
        from micron.__main__ import _resolve_server_url
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MICRON_SERVER_URL", None)
            assert _resolve_server_url(_make_config("0.0.0.0", 8000)) == "http://localhost:8000"

    def test_explicit_host_kept(self):
        from micron.__main__ import _resolve_server_url
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MICRON_SERVER_URL", None)
            assert _resolve_server_url(_make_config("192.168.1.5", 9000)) == "http://192.168.1.5:9000"


class TestUploadFile:
    # _upload_file does `import requests` inside the function, so the
    # patch target is the global `requests` module, not `micron.__main__.requests`.
    def test_upload_returns_path(self, tmp_path):
        from micron.__main__ import _upload_file

        f = tmp_path / "hello.txt"
        f.write_bytes(b"hello world")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "path": "context/uploads/20260811_hello.txt",
            "filename": "hello.txt",
            "size": 11,
            "mimetype": "text/plain",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp) as mock_post:
            data = _upload_file(f, "http://localhost:8000")

        assert data["path"] == "context/uploads/20260811_hello.txt"
        assert mock_post.call_args.kwargs["files"]["file"][0] == "hello.txt"

    def test_upload_propagates_http_error(self, tmp_path):
        from micron.__main__ import _upload_file

        f = tmp_path / "x.txt"
        f.write_text("x")

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = RuntimeError("500")

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="500"):
                _upload_file(f, "http://localhost:8000")


class TestUploadArg:
    def test_upload_arg_prints_path(self, tmp_path, capsys):
        from micron.__main__ import main

        f = tmp_path / "doc.txt"
        f.write_text("content")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"path": "context/uploads/doc.txt"}
        mock_resp.raise_for_status = MagicMock()

        with patch("sys.argv", ["micron", "--upload", str(f)]):
            with patch("requests.post", return_value=mock_resp):
                with patch("micron.__main__._resolve_server_url", return_value="http://localhost:8000"):
                    with patch("micron.__main__.create_agent_and_logger") as mock_cag:
                        mock_cag.return_value = (MagicMock(), MagicMock(), "session-id")
                        main()

        out = capsys.readouterr().out
        assert "context/uploads/doc.txt" in out

    def test_upload_missing_file(self, tmp_path, capsys):
        from micron.__main__ import main

        missing = tmp_path / "absent.txt"
        with patch("sys.argv", ["micron", "--upload", str(missing)]):
            with patch("micron.__main__.create_agent_and_logger") as mock_cag:
                mock_cag.return_value = (MagicMock(), MagicMock(), "session-id")
                with pytest.raises(SystemExit):
                    main()

        err = capsys.readouterr().err
        assert "File not found" in err

    def test_upload_server_error(self, tmp_path, capsys):
        from micron.__main__ import main

        f = tmp_path / "ok.txt"
        f.write_text("ok")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "File too large"}
        mock_resp.raise_for_status = MagicMock()

        with patch("sys.argv", ["micron", "--upload", str(f)]):
            with patch("requests.post", return_value=mock_resp):
                with patch("micron.__main__._resolve_server_url", return_value="http://localhost:8000"):
                    with patch("micron.__main__.create_agent_and_logger") as mock_cag:
                        mock_cag.return_value = (MagicMock(), MagicMock(), "session-id")
                        with pytest.raises(SystemExit):
                            main()

        err = capsys.readouterr().err
        assert "File too large" in err
