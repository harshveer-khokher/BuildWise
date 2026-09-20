"""DWG -> DXF conversion via the ODA File Converter.

ezdxf (this project's DXF reader) cannot read native DWG at all -- DWG is a proprietary,
undocumented AutoDesk binary format, and no open-source Python library reads it directly.
ezdxf's own FAQ recommends converting through the ODA File Converter first
(https://www.opendesign.com/guestfiles/oda_file_converter) -- a free (no license fee), officially
redistributable desktop application from the Open Design Alliance that reads/writes essentially
every DWG/DXF version ever published. This module wraps that external tool; it does not, and
cannot, parse DWG itself.

This is a REAL external dependency, not a pip package -- it must be installed separately on
whatever machine runs this backend. If it isn't found, every function here fails loudly with the
exact install instructions (INSTALL_INSTRUCTIONS below) rather than silently skipping conversion
or guessing at a DXF equivalent -- CLAUDE.md's "declared uncertainty over fake precision"
principle applies just as much to tooling availability as to numeric values.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile

# ODA File Converter's own CLI signature (stable, documented behaviour across versions):
#   ODAFileConverter <input_folder> <output_folder> <output_version> <output_type> <recurse> <audit> [filter]
# It only operates on whole FOLDERS, never a single file -- so every call here stages the one
# input file into a scratch folder and reads the one output file back out of another.
_ODA_OUTPUT_VERSION = "ACAD2018"  # a modern DXF version ezdxf reads cleanly
_ODA_OUTPUT_TYPE = "DXF"
_ODA_TIMEOUT_S = 120

# Common install locations on Windows/Linux/Mac across ODA File Converter releases, as
# (fixed_base_dir, glob_pattern_relative_to_it) pairs -- the version number embedded in the
# folder name changes per release, so the wildcard has to be globbed as part of one multi-
# segment pattern relative to a real, non-wildcard ancestor directory (pathlib.Path.glob()
# does not expand a "*" that appears inside the base path string itself). Necessarily a
# best-effort list, not exhaustive -- CHD_ODA_CONVERTER_PATH is the reliable override.
_CANDIDATE_GLOBS: list[tuple[str, str]] = [
    (r"C:\Program Files\ODA", "ODAFileConverter*/ODAFileConverter.exe"),
    (r"C:\Program Files (x86)\ODA", "ODAFileConverter*/ODAFileConverter.exe"),
    (r"C:\Program Files\ODA File Converter", "ODAFileConverter.exe"),
    ("/usr/bin", "ODAFileConverter"),
    ("/usr/local/bin", "ODAFileConverter"),
    ("/opt/ODAFileConverter", "ODAFileConverter"),
    ("/Applications", "ODAFileConverter*.app/Contents/MacOS/ODAFileConverter"),
]

INSTALL_INSTRUCTIONS = (
    "No DWG-to-DXF converter was found on this machine. This is a permanent limitation of every "
    "open-source DXF library (including ezdxf, which this project uses) -- DWG is a proprietary "
    "AutoDesk format with no publicly documented spec, so there is no way to add DWG support in "
    "pure Python. The fix is the free ODA File Converter from the Open Design Alliance: "
    "https://www.opendesign.com/guestfiles/oda_file_converter -- a real desktop application "
    "(not a pip package) that reads and writes essentially every AutoCAD DWG/DXF version ever "
    "published, and is the tool ezdxf's own documentation recommends for DWG support. After "
    "installing it, either it will be auto-detected at its default install path, or set the "
    "CHD_ODA_CONVERTER_PATH environment variable to its ODAFileConverter.exe (or equivalent "
    "binary) location."
)


class DwgConversionError(RuntimeError):
    """Raised whenever a DWG cannot be converted -- converter missing, conversion failed, or the
    output DXF wasn't produced. Callers should surface this to the user directly (it already
    contains actionable next steps), not swallow it."""


def find_oda_converter() -> pathlib.Path | None:
    """Locates the ODA File Converter executable, or None if not found. Checked in order:
    explicit env var override, then a best-effort list of common install locations."""
    env_path = os.environ.get("CHD_ODA_CONVERTER_PATH")
    if env_path:
        p = pathlib.Path(env_path)
        if p.exists():
            return p

    for base_dir, rel_pattern in _CANDIDATE_GLOBS:
        base = pathlib.Path(base_dir)
        if not base.exists():
            continue
        matches = sorted(base.glob(rel_pattern))
        if matches:
            return matches[-1]  # newest-sorting version string, best effort

    found = shutil.which("ODAFileConverter")
    return pathlib.Path(found) if found else None


def is_available() -> bool:
    return find_oda_converter() is not None


def convert_dwg_to_dxf(dwg_path: str | pathlib.Path, out_dxf_path: str | pathlib.Path) -> None:
    """Converts one .dwg file to .dxf at `out_dxf_path`.

    Raises DwgConversionError (with INSTALL_INSTRUCTIONS baked in) if the converter isn't
    installed, times out, or doesn't produce output -- never silently skips conversion or
    leaves a stale/missing file for the caller to trip over later.
    """
    converter = find_oda_converter()
    if converter is None:
        raise DwgConversionError(INSTALL_INSTRUCTIONS)

    dwg_path = pathlib.Path(dwg_path)
    out_dxf_path = pathlib.Path(out_dxf_path)
    if not dwg_path.exists():
        raise DwgConversionError(f"input DWG file not found: {dwg_path}")

    with tempfile.TemporaryDirectory(prefix="dwg_in_") as in_dir, \
         tempfile.TemporaryDirectory(prefix="dwg_out_") as out_dir:
        in_dir_p = pathlib.Path(in_dir)
        out_dir_p = pathlib.Path(out_dir)
        staged = in_dir_p / dwg_path.name
        staged.write_bytes(dwg_path.read_bytes())

        cmd = [
            str(converter), str(in_dir_p), str(out_dir_p),
            _ODA_OUTPUT_VERSION, _ODA_OUTPUT_TYPE,
            "0",  # recurse subfolders: no, single flat folder
            "1",  # audit: yes, repair minor structural issues on the way through
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_ODA_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise DwgConversionError(
                f"ODA File Converter timed out after {_ODA_TIMEOUT_S}s converting "
                f"{dwg_path.name} -- the file may be unusually large or corrupt."
            ) from exc
        except OSError as exc:
            raise DwgConversionError(
                f"could not run the ODA File Converter at {converter}: {exc}. "
                + INSTALL_INSTRUCTIONS
            ) from exc

        expected = out_dir_p / (staged.stem + ".dxf")
        if not expected.exists():
            raise DwgConversionError(
                f"ODA File Converter did not produce a DXF for {dwg_path.name} "
                f"(exit code {result.returncode}). "
                f"stdout: {result.stdout[-500:]!r} stderr: {result.stderr[-500:]!r}. "
                "The DWG file may be corrupt, password-protected, or in a version this "
                "converter build can't read."
            )
        out_dxf_path.parent.mkdir(parents=True, exist_ok=True)
        out_dxf_path.write_bytes(expected.read_bytes())
