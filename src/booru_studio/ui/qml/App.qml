import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "components"
import "pages"
import "theme"

ApplicationWindow {
    id: window
    width: 1180
    height: 760
    minimumWidth: 880
    minimumHeight: 620
    visible: true
    title: t("app.title") + " V10"
    color: DesignTokens.windowBackground

    property int currentPage: 0
    function t(key) { appController.language; return appController.trKey(key) }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: DesignTokens.navWidth
            Layout.fillHeight: true
            color: DesignTokens.navigationSurface
            border.color: DesignTokens.hairline
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                Label { text: "Booru Studio"; color: DesignTokens.navigationText; font.pixelSize: DesignTokens.titleMedium; font.weight: Font.Bold; Layout.bottomMargin: 16 }
                NavButton { Layout.fillWidth: true; text: window.t("nav.downloads"); selected: window.currentPage === 0; onClicked: window.currentPage = 0 }
                NavButton { Layout.fillWidth: true; text: window.t("nav.queue"); selected: window.currentPage === 1; onClicked: window.currentPage = 1 }
                NavButton { Layout.fillWidth: true; text: window.t("nav.history"); selected: window.currentPage === 2; onClicked: window.currentPage = 2 }
                NavButton { Layout.fillWidth: true; text: window.t("nav.settings"); selected: window.currentPage === 3; onClicked: window.currentPage = 3 }
                Item { Layout.fillHeight: true }
                Label { text: "Core projection r" + appController.revision; color: DesignTokens.textTertiary; font.pixelSize: DesignTokens.caption }
                Label {
                    text: window.t("status." + appController.status.toLowerCase())
                    color: appController.stale ? DesignTokens.warning : (appController.pendingCommand ? DesignTokens.accent : DesignTokens.positive)
                    font.pixelSize: DesignTokens.caption
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 82
                color: DesignTokens.windowBackground
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 24
                    anchors.rightMargin: 24
                    spacing: 10
                    TextField {
                        id: inputField
                        Layout.fillWidth: true
                        placeholderText: window.t("input.placeholder")
                        selectByMouse: true
                        onAccepted: submitButton.clicked()
                        Accessible.name: "Download input"
                    }
                    Button {
                        id: submitButton
                        text: window.t("action.add_queue")
                        highlighted: true
                        enabled: appController.canSubmit && inputField.text.trim().length > 0
                        onClicked: appController.submitInput(inputField.text)
                        Accessible.name: text
                    }
                    Button {
                        text: window.t("action.refresh")
                        enabled: !appController.pendingCommand
                        onClicked: appController.refresh()
                        Accessible.name: text
                    }
                }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: 24
                Layout.rightMargin: 24
                Layout.bottomMargin: 20
                currentIndex: window.currentPage
                DownloadsPage {}
                QueuePage {}
                HistoryPage {}
                SettingsPage {}
            }
        }
    }

    Connections {
        target: appController
        function onCommandError(message) {
            errorDialog.text = message
            errorDialog.open()
        }
        function onSubmissionCommitted(rawInput) {
            if (inputField.text === rawInput)
                inputField.clear()
        }
    }
    MessageDialog {
        id: errorDialog
        title: "Booru Studio"
    }
}
