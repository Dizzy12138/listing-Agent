from core.schemas.sku import SKU, SceneRequirements


def test_scene_requirements_accepts_string():
    sku = SKU(product_id="P1", name="Test SKU", scene_requirements="bright studio")

    assert isinstance(sku.scene_requirements, SceneRequirements)
    assert sku.scene_requirements.main_scene == "bright studio"


def test_sku_defaults_are_isolated():
    first = SKU(product_id="P1", name="One")
    second = SKU(product_id="P2", name="Two")

    first.selling_points.append("stable base")

    assert second.selling_points == []
