import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: (appController.language, appController.trKey("settings.title")); color: DesignTokens.navigationText; font.pixelSize: DesignTokens.titleLarge; font.weight: Font.Bold }
        Label { text: (appController.language, appController.trKey("settings.note")); color: DesignTokens.textSecondary; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        RowLayout {
            Label { text: (appController.language, appController.trKey("settings.language")); color: DesignTokens.textPrimary }
            Button { text: "한국어"; checkable: true; checked: appController.language === "ko"; onClicked: appController.setLanguage("ko") }
            Button { text: "English"; checkable: true; checked: appController.language === "en"; onClicked: appController.setLanguage("en") }
        }
    }
}
