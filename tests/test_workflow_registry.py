import pytest

from core.workflows.registry import get_workflow, register_workflow, resolve_workflow


def test_resolve_workflow_for_core_image_types():
    assert resolve_workflow("white_bg") == "white_main"
    assert resolve_workflow("scene_main") == "scene_main"
    assert resolve_workflow("detail") == "detail_material"
    assert resolve_workflow("size_compare") == "size_compare"
    assert resolve_workflow("multilingual_text") == "multilingual_text"


def test_resolve_selling_point_routes_by_description():
    assert resolve_workflow("selling_point", "show plush fabric texture") == "detail_material"
    assert resolve_workflow("selling_point", "highlight stable base and climb path") == "selling_point_annotation"


def test_resolve_workflow_rejects_unsupported_type():
    with pytest.raises(ValueError):
        resolve_workflow("unknown_type")


def test_register_and_get_workflow():
    @register_workflow("test_workflow")
    class TestWorkflow:
        pass

    assert get_workflow("test_workflow") is TestWorkflow
