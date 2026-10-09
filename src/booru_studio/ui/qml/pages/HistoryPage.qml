import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: (appController.language, appController.trKey("history.title")); color: DesignTokens.navigationText; font.pixelSize: DesignTokens.titleLarge; font.weight: Font.Bold }
        Label { text: (appController.language, appController.trKey("history.subtitle")); color: DesignTokens.textSecondary; font.pixelSize: DesignTokens.body }
        Label { visible: appController.historyHasMore; text: (appController.language, appController.trKey("history.more_bounded")); color: DesignTokens.warning; font.pixelSize: DesignTokens.caption }
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10
            model: historyModel
            reuseItems: true
            clip: true
            delegate: JobCard {
                width: ListView.view.width
                jobTitle: model.title || model.job_id
                kindText: model.kind || "UNKNOWN"
                lifecycleText: model.lifecycle || "SETTLED"
                outcomeText: model.outcome || ""
                subtitleText: model.display_input || ""
                progressValue: model.progress === null || model.progress === undefined ? -1 : model.progress
                artifactDone: model.artifact_committed || 0
                artifactTotal: model.artifact_total || 0
                committedBytes: model.committed_bytes || 0
                expectedBytes: model.expected_bytes || 0
                filePath: model.primary_file_path || ""
                errorCode: model.latest_error_code || ""
                nativeCode: model.latest_native_code || ""
                onOpenRequested: appController.openDownloadedFile(filePath)
                onRevealRequested: appController.revealDownloadedFile(filePath)
            }
            Label { anchors.centerIn: parent; visible: parent.count === 0; text: (appController.language, appController.trKey("history.empty")); color: DesignTokens.textTertiary }
        }
    }
}
