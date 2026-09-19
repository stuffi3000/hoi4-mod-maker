"""M10 regression checks for verifier output on Windows code pages."""
from __future__ import annotations

import io

import pytest

from export.verify_mod import ModVerifier


pytestmark = pytest.mark.unit


class _AsciiOnlyStream(io.StringIO):
    @property
    def encoding(self):
        return "ascii"

    def write(self, text):
        text.encode("ascii")
        return super().write(text)


def test_verify_all_uses_ascii_safe_output(monkeypatch, tmp_path):
    stream = _AsciiOnlyStream()
    monkeypatch.setattr("sys.stdout", stream)

    result = ModVerifier(str(tmp_path)).verify_all()

    assert result is False
    assert "Verifying mod" in stream.getvalue()
    assert "Checking" in stream.getvalue()
