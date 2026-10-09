import QtQuick
import QtQuick.Controls
import "../theme"

Button {
    id: root
    property bool selected: false
    implicitHeight: Math.max(42, DesignTokens.minimumHitTarget)
    leftPadding: 14
    rightPadding: 14
    font.pixelSize: 14
    font.weight: selected ? Font.DemiBold : Font.Normal
    background: Rectangle {
        radius: DesignTokens.radiusSmall
        color: root.selected ? DesignTokens.accent : (root.hovered ? DesignTokens.elevatedSurface : "transparent")
        opacity: root.selected ? 1.0 : 0.95
    }
    contentItem: Text {
        text: root.text
        color: root.selected ? DesignTokens.windowBackground : DesignTokens.textPrimary
        font: root.font
        verticalAlignment: Text.AlignVCenter
    }
    Accessible.name: text
    Accessible.role: Accessible.Button
}
