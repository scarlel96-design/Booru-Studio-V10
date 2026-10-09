import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: (appController.language, appController.trKey("queue.title")); color: DesignTokens.navigationText; font.pixelSize: DesignTokens.titleLarge; font.weight: Font.Bold }
        Label { text: (appController.language, appController.trKey("queue.subtitle")); color: DesignTokens.textSecondary; font.pixelSize: DesignTokens.body }
        ListView {
            id: queueList
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8
            model: queueModel
            reuseItems: true
            clip: true
            delegate: Rectangle {
                required property int index
                width: ListView.view.width
                height: 70
                radius: 12
                color: DesignTokens.contentSurface
                border.color: DesignTokens.hairline
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    Rectangle {
                        implicitWidth: 38; implicitHeight: 38; radius: 10; color: DesignTokens.elevatedSurface
                        Text { anchors.centerIn: parent; text: model.position || (index + 1); color: DesignTokens.accentText; font.weight: Font.Bold }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 2
                        Text { Layout.fillWidth: true; text: model.title || model.job_id; color: DesignTokens.textPrimary; font.pixelSize: 14; elide: Text.ElideMiddle; textFormat: Text.PlainText }
                        Text { text: (appController.language, appController.trKey("queue.priority")) + " " + (model.priority || 0); color: DesignTokens.textSecondary; font.pixelSize: DesignTokens.caption }
                    }
                    ToolButton { text: "↑"; enabled: index > 0 && !appController.pendingCommand && !appController.stale; onClicked: appController.moveQueueJob(model.job_id, "UP"); Accessible.name: (appController.language, appController.trKey("action.move_up")) }
                    ToolButton { text: "↓"; enabled: index < queueList.count - 1 && !appController.pendingCommand && !appController.stale; onClicked: appController.moveQueueJob(model.job_id, "DOWN"); Accessible.name: (appController.language, appController.trKey("action.move_down")) }
                    Button { enabled: !appController.pendingCommand && !appController.stale; text: (appController.language, appController.trKey("action.pause")); flat: true; onClicked: appController.pauseJob(model.job_id); Accessible.name: text }
                    Button { visible: model.control_intent !== "CANCEL_REQUESTED"; enabled: !appController.pendingCommand && !appController.stale; text: (appController.language, appController.trKey("action.cancel")); flat: true; onClicked: appController.cancelJob(model.job_id); Accessible.name: text }
                }
            }
            Label { anchors.centerIn: parent; visible: parent.count === 0; text: (appController.language, appController.trKey("queue.empty")); color: DesignTokens.textTertiary }
        }
    }
}
