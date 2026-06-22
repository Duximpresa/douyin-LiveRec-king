from pathlib import Path

from douyin_live_rec_king.utils.filenames import recording_path, safe_component


def test_safe_component_removes_windows_invalid_characters() -> None:
    assert safe_component('a<b>c:d"e/f\\g|h?i*') == "a_b_c_d_e_f_g_h_i_"


def test_recording_path_creates_directory(tmp_path: Path) -> None:
    output = recording_path(
        tmp_path / "out", "douyin", "主播", "ts",
        "{platform}_{anchor}_{time}", folder_by_platform=True,
        folder_by_anchor=True, segmented=True,
    )
    assert output.parent.exists()
    assert output.suffix == ".ts"
    assert "douyin_主播_" in output.name
    assert "%03d" in output.name
    assert output.parent.name == "主播"
