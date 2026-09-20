"""packages/parser/dwg_convert.py -- the ODA File Converter wrapper.

ezdxf cannot read native DWG at all; this module shells out to the free ODA File Converter,
a real desktop application that isn't installed in this environment (or, presumably, most CI
environments) and can't be pip-installed. Two different testing strategies are used here:

  1. find_oda_converter()'s env-var override and glob logic are tested directly -- no external
     binary needed, since these are pure path-resolution functions.
  2. convert_dwg_to_dxf()'s actual subprocess invocation (argument order, folder staging, output-
     file expectation) is tested against a FAKE "converter" -- a tiny Python script that mimics
     the real ODA File Converter's CLI contract (same positional args, writes a same-stem .dxf
     into the output folder) -- pointed at via CHD_ODA_CONVERTER_PATH. This exercises the real
     subprocess/staging code path, not just a mock, without needing the actual proprietary binary.

The genuinely untested thing, unavoidably, is the real ODA File Converter itself -- that can only
be verified once it's actually installed somewhere and a real DWG is run through it.
"""

from __future__ import annotations

import os
import pathlib
import sys
import textwrap

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from packages.parser import dwg_convert

FAKE_CONVERTER_SCRIPT = textwrap.dedent(
    """\
    import sys
    from pathlib import Path

    # Mimics: ODAFileConverter <in_dir> <out_dir> <version> <type> <recurse> <audit>
    in_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in in_dir.glob("*.dwg"):
        (out_dir / (f.stem + ".dxf")).write_text("FAKE DXF CONTENT FROM " + f.name, encoding="utf-8")
    """
)

FAKE_CONVERTER_SCRIPT_NO_OUTPUT = "import sys\nsys.exit(0)\n"


def _write_fake_converter(tmp_path: pathlib.Path, script: str) -> pathlib.Path:
    """Writes a fake converter as a real, directly-executable script (a .bat wrapper around the
    Python interpreter on Windows, a shebang'd script elsewhere) since convert_dwg_to_dxf()
    invokes it directly via subprocess, not through `python <script>`."""
    py_path = tmp_path / "fake_oda.py"
    py_path.write_text(script, encoding="utf-8")
    if sys.platform.startswith("win"):
        wrapper = tmp_path / "ODAFileConverter.bat"
        wrapper.write_text(f'@echo off\r\n"{sys.executable}" "{py_path}" %*\r\n', encoding="utf-8")
        return wrapper
    wrapper = tmp_path / "ODAFileConverter"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py_path}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def test_find_oda_converter_uses_env_var_override(tmp_path, monkeypatch):
    fake = tmp_path / "MyConverter.exe"
    fake.write_text("not a real binary, just needs to exist", encoding="utf-8")
    monkeypatch.setenv("CHD_ODA_CONVERTER_PATH", str(fake))
    assert dwg_convert.find_oda_converter() == fake


def test_find_oda_converter_ignores_nonexistent_env_var_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CHD_ODA_CONVERTER_PATH", str(tmp_path / "does_not_exist.exe"))
    # Falls through to the real candidate-path search, which correctly finds nothing on a
    # machine without the converter installed (this test's own CI/dev machine).
    result = dwg_convert.find_oda_converter()
    assert result is None or result.exists()  # never a nonexistent path


def test_is_available_reflects_find_oda_converter(monkeypatch):
    monkeypatch.setattr(dwg_convert, "find_oda_converter", lambda: None)
    assert dwg_convert.is_available() is False
    monkeypatch.setattr(dwg_convert, "find_oda_converter", lambda: pathlib.Path("fake"))
    assert dwg_convert.is_available() is True


def test_convert_dwg_to_dxf_fails_loudly_with_install_instructions_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(dwg_convert, "find_oda_converter", lambda: None)
    dwg = tmp_path / "test.dwg"
    dwg.write_bytes(b"not a real dwg")
    with pytest.raises(dwg_convert.DwgConversionError) as exc_info:
        dwg_convert.convert_dwg_to_dxf(dwg, tmp_path / "out.dxf")
    assert "opendesign.com" in str(exc_info.value)
    assert "CHD_ODA_CONVERTER_PATH" in str(exc_info.value)


def test_convert_dwg_to_dxf_missing_input_file_fails_loudly(tmp_path, monkeypatch):
    fake_converter = _write_fake_converter(tmp_path, FAKE_CONVERTER_SCRIPT)
    monkeypatch.setattr(dwg_convert, "find_oda_converter", lambda: fake_converter)
    with pytest.raises(dwg_convert.DwgConversionError, match="not found"):
        dwg_convert.convert_dwg_to_dxf(tmp_path / "nonexistent.dwg", tmp_path / "out.dxf")


def test_convert_dwg_to_dxf_real_subprocess_invocation_succeeds(tmp_path, monkeypatch):
    """Exercises the actual subprocess call, folder staging, and output-file readback against a
    fake converter that mimics the real ODA File Converter's CLI contract exactly."""
    fake_converter = _write_fake_converter(tmp_path, FAKE_CONVERTER_SCRIPT)
    monkeypatch.setattr(dwg_convert, "find_oda_converter", lambda: fake_converter)

    dwg = tmp_path / "elevation_front.dwg"
    dwg.write_bytes(b"pretend this is real dwg binary content")
    out_dxf = tmp_path / "result" / "converted.dxf"

    dwg_convert.convert_dwg_to_dxf(dwg, out_dxf)

    assert out_dxf.exists()
    assert "FAKE DXF CONTENT FROM elevation_front.dwg" in out_dxf.read_text(encoding="utf-8")


def test_convert_dwg_to_dxf_raises_when_converter_produces_no_output(tmp_path, monkeypatch):
    fake_converter = _write_fake_converter(tmp_path, FAKE_CONVERTER_SCRIPT_NO_OUTPUT)
    monkeypatch.setattr(dwg_convert, "find_oda_converter", lambda: fake_converter)

    dwg = tmp_path / "test.dwg"
    dwg.write_bytes(b"content")
    with pytest.raises(dwg_convert.DwgConversionError, match="did not produce a DXF"):
        dwg_convert.convert_dwg_to_dxf(dwg, tmp_path / "out.dxf")
