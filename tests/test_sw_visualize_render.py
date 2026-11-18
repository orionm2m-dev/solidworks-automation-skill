"""Visualize 渲染模块的入参校验测试（不连接 SOLIDWORKS）。"""
import pytest

from scripts.sw_visualize_render import IMAGE_FORMATS, validate_render_request


def test_accepts_new_job_in_existing_folder(tmp_path):
    job_dir, box = validate_render_request(str(tmp_path), "bms_hero", 1200, 1200, 200, "png", [0, 0, 0, 1, 2, 3])
    assert job_dir == tmp_path / "bms_hero" and box == [0.0, 0.0, 0.0, 1.0, 2.0, 3.0]


def test_rejects_existing_job_folder(tmp_path):
    (tmp_path / "done").mkdir()
    with pytest.raises(ValueError):
        validate_render_request(str(tmp_path), "done", 1200, 1200, 200, "png", None)


@pytest.mark.parametrize("output_dir", ["relative", "C:/missing/never/there"])
def test_rejects_bad_output_dir(output_dir):
    with pytest.raises(ValueError):
        validate_render_request(output_dir, "job", 1200, 1200, 200, "png", None)


@pytest.mark.parametrize("kwargs", [
    {"job_name": "has space"}, {"job_name": ".."}, {"job_name": ""}, {"width": 100}, {"height": 5000},
    {"frame_count": 0}, {"frame_count": 6000}, {"frame_count": 1.5}, {"image_format": "gif"},
    {"zoom_box_mm": [0, 0, 0, 0, 1, 1]}, {"zoom_box_mm": [0, 0, 0, 1, 1]}])
def test_rejects_bad_values(tmp_path, kwargs):
    args = {"job_name": "job", "width": 1200, "height": 1200, "frame_count": 200,
            "image_format": "png", "zoom_box_mm": None}
    args.update(kwargs)
    with pytest.raises(ValueError):
        validate_render_request(str(tmp_path), args["job_name"], args["width"], args["height"],
                                args["frame_count"], args["image_format"], args["zoom_box_mm"])


def test_image_format_values_match_type_library():
    assert IMAGE_FORMATS == {"jpeg": 0, "bmp": 1, "tiff": 2, "png": 3}
