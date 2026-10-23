"""A visible editor must remain a foreground app alongside its console worker."""

import importlib.util
import plistlib
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "editor_builder", Path(__file__).resolve().parents[1] / "packaging/build_editor_app.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def bundle(tmp_path, **overrides):
    app = tmp_path / "InkStructEditor.app"
    binaries = app / "Contents/MacOS"
    binaries.mkdir(parents=True)
    for name in ("InkStructEditor", "InkStructTool"):
        binary = binaries / name
        binary.write_bytes(b"test executable placeholder")
        binary.chmod(0o755)
    info = {"CFBundleExecutable": "InkStructEditor", "CFBundlePackageType": "APPL"}
    info.update(overrides)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    return app


@pytest.mark.parametrize("flags", [{}, {"LSBackgroundOnly": False, "LSUIElement": False}])
def test_accept_foreground_editor_with_console_companion(tmp_path, flags):
    assert builder.validate_macos_bundle(bundle(tmp_path, **flags))[
        "foreground_application_metadata_verified"
    ]


@pytest.mark.parametrize("key", ["LSBackgroundOnly", "LSUIElement"])
@pytest.mark.parametrize("value", [True, "1", "true"])
def test_reject_background_or_agent_bundle(tmp_path, key, value):
    with pytest.raises(ValueError, match=key):
        builder.validate_macos_bundle(bundle(tmp_path, **{key: value}))


@pytest.mark.parametrize(
    "overrides", [{"CFBundleExecutable": "InkStructTool"}, {"CFBundlePackageType": "BNDL"}]
)
def test_reject_wrong_application_entry(tmp_path, overrides):
    with pytest.raises(ValueError):
        builder.validate_macos_bundle(bundle(tmp_path, **overrides))


def test_require_executable_companion(tmp_path):
    app = bundle(tmp_path)
    (app / "Contents/MacOS/InkStructTool").chmod(0o644)
    with pytest.raises(ValueError, match="InkStructTool"):
        builder.validate_macos_bundle(app)
