from pathlib import Path


def test_design_system_is_principle_synthesis_not_skin_mix():
    text=Path("docs/design-system.md").read_text(encoding="utf-8")
    for phrase in ["Apple / iOS / macOS","Samsung One UI","Windows 11","Windows 10 familiarity","Large icons are semantic anchors","Settings use familiar Windows information architecture"]:
        assert phrase in text
    tokens=Path("src/booru_studio/ui/qml/theme/DesignTokens.qml").read_text(encoding="utf-8")
    for token in ["minimumHitTarget","navWidth","motionNormal","textPrimary","elevatedSurface"]:
        assert token in tokens


def test_feature_qml_cannot_define_private_hex_palettes():
    import re
    root=Path("src/booru_studio/ui/qml")
    offenders=[]
    for path in root.rglob("*.qml"):
        if path.name == "DesignTokens.qml":
            continue
        if re.search(r'#[0-9A-Fa-f]{6,8}', path.read_text(encoding="utf-8")):
            offenders.append(str(path))
    assert offenders == []
