import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Frame {
    id: card
    required property string jobTitle
    required property string lifecycleText
    property string kindText: "UNKNOWN"
    property string outcomeText: ""
    property string activityText: ""
    property string waitingText: ""
    property string subtitleText: ""
    property string filePath: ""
    property string errorCode: ""
    property string nativeCode: ""
    property real progressValue: -1
    property int artifactDone: 0
    property int artifactTotal: 0
    property double committedBytes: 0
    property double expectedBytes: 0
    property bool cancellable: false
    property bool pausable: false
    property bool resumable: false
    property bool settled: lifecycleText === "SETTLED"
    signal cancelRequested()
    signal pauseRequested()
    signal resumeRequested()
    signal openRequested()
    signal revealRequested()

    function t(key) { appController.language; return appController.trKey(key) }
    function kindLabel() {
        var key = "kind." + kindText.toLowerCase()
        var value = t(key)
        return value === key ? kindText : value
    }
    function phaseLabel() {
        var code = activityText.length ? activityText : waitingText
        if (!code.length) return ""
        var prefix = activityText.length ? "phase." : "waiting."
        var key = prefix + code.toLowerCase()
        var value = t(key)
        return value === key ? code : value
    }
    function formatBytes(value) {
        if (!value || value <= 0) return ""
        var units = ["B", "KiB", "MiB", "GiB", "TiB"]
        var number = value
        var index = 0
        while (number >= 1024 && index < units.length - 1) { number /= 1024; index++ }
        return (index === 0 ? Math.round(number) : number.toFixed(number >= 10 ? 1 : 2)) + " " + units[index]
    }

    implicitHeight: content.implicitHeight + 30
    padding: 15
    background: Rectangle {
        radius: DesignTokens.radiusMedium
        color: hoverHandler.hovered ? DesignTokens.elevatedSurface : DesignTokens.contentSurface
        border.color: card.errorCode.length ? DesignTokens.negativeBorder : DesignTokens.hairline
        border.width: 1
        Behavior on color { ColorAnimation { duration: DesignTokens.motionFast } }
    }

    HoverHandler { id: hoverHandler }
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: if (card.filePath.length) fileMenu.popup()
    }
    Menu {
        id: fileMenu
        MenuItem { text: card.t("action.open_file"); enabled: card.filePath.length > 0; onTriggered: card.openRequested() }
        MenuItem { text: card.t("action.reveal_file"); enabled: card.filePath.length > 0; onTriggered: card.revealRequested() }
    }

    ColumnLayout {
        id: content
        anchors.fill: parent
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Rectangle {
                implicitWidth: kindLabel.implicitWidth + 14
                implicitHeight: 24
                radius: 7
                color: DesignTokens.kindSurface
                Text { id: kindLabel; anchors.centerIn: parent; text: card.kindLabel(); color: DesignTokens.kindText; font.pixelSize: 10; font.weight: Font.DemiBold }
            }
            Text {
                Layout.fillWidth: true
                text: card.jobTitle
                color: DesignTokens.textPrimary
                font.pixelSize: 15
                font.weight: Font.DemiBold
                elide: Text.ElideMiddle
                textFormat: Text.PlainText
            }
            Rectangle {
                implicitWidth: statusText.implicitWidth + 16
                implicitHeight: 26
                radius: 8
                color: card.settled ? (card.outcomeText === "SUCCESS" ? DesignTokens.positiveSurface : DesignTokens.negativeSurface) : (card.lifecycleText === "PAUSED" ? DesignTokens.warningSurface : DesignTokens.accentSurface)
                Text {
                    id: statusText
                    anchors.centerIn: parent
                    text: card.outcomeText.length ? card.outcomeText : card.lifecycleText
                    color: card.settled ? (card.outcomeText === "SUCCESS" ? DesignTokens.positiveText : DesignTokens.negativeText) : (card.lifecycleText === "PAUSED" ? DesignTokens.warningText : DesignTokens.accentText)
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }
            }
        }

        Text {
            Layout.fillWidth: true
            text: card.phaseLabel().length ? card.phaseLabel() : card.subtitleText
            color: card.activityText === "POSTPROCESSING" || card.activityText === "VERIFYING" ? DesignTokens.phaseAccent : DesignTokens.textSecondary
            font.pixelSize: 12
            elide: Text.ElideMiddle
            textFormat: Text.PlainText
        }

        ProgressBar {
            Layout.fillWidth: true
            from: 0
            to: 1
            value: card.progressValue >= 0 ? card.progressValue : 0
            indeterminate: !card.settled && (card.progressValue < 0 || card.activityText === "POSTPROCESSING" || card.activityText === "VERIFYING" || card.activityText === "RECONCILING")
            visible: !card.settled || card.artifactTotal > 0
            Accessible.name: card.t("progress.job")
        }

        RowLayout {
            Layout.fillWidth: true
            Text {
                visible: card.artifactTotal > 0
                text: card.artifactDone + " / " + card.artifactTotal + " " + card.t("progress.files")
                color: DesignTokens.textTertiary
                font.pixelSize: 11
            }
            Text {
                visible: card.expectedBytes > 0 || card.committedBytes > 0
                text: card.expectedBytes > 0 ? card.formatBytes(card.committedBytes) + " / " + card.formatBytes(card.expectedBytes) : card.formatBytes(card.committedBytes)
                color: DesignTokens.textTertiary
                font.pixelSize: 11
            }
            Item { Layout.fillWidth: true }
            ToolButton { visible: card.pausable; text: card.t("action.pause"); onClicked: card.pauseRequested(); Accessible.name: text }
            ToolButton { visible: card.resumable; text: card.t("action.resume"); onClicked: card.resumeRequested(); Accessible.name: text }
            ToolButton { visible: card.filePath.length > 0; text: card.t("action.open_file"); onClicked: card.openRequested(); Accessible.name: text }
            ToolButton { visible: card.filePath.length > 0; text: card.t("action.reveal_file"); onClicked: card.revealRequested(); Accessible.name: text }
            ToolButton { visible: card.cancellable; text: card.t("action.cancel"); onClicked: card.cancelRequested(); Accessible.name: text }
        }

        Rectangle {
            visible: card.errorCode.length > 0
            Layout.fillWidth: true
            implicitHeight: errorText.implicitHeight + 14
            radius: 8
            color: DesignTokens.negativeSurface
            Text {
                id: errorText
                anchors.fill: parent
                anchors.margins: 7
                text: card.t("error.label") + ": " + card.errorCode + (card.nativeCode.length ? " · " + card.nativeCode : "")
                color: DesignTokens.negativeText
                font.pixelSize: 11
                wrapMode: Text.WrapAnywhere
                textFormat: Text.PlainText
            }
        }
    }
}
