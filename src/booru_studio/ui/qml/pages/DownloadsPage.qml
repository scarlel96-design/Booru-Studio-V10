import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

Item {
    ColumnLayout {
        anchors.fill: parent
        spacing: 12
        Label { text: (appController.language, appController.trKey("downloads.title")); color: DesignTokens.navigationText; font.pixelSize: DesignTokens.titleLarge; font.weight: Font.Bold }
        Label { text: (appController.language, appController.trKey("downloads.subtitle")); color: DesignTokens.textSecondary; font.pixelSize: DesignTokens.body }
        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 10
            clip: true
            model: downloadsModel
            reuseItems: true
            delegate: JobCard {
                width: ListView.view.width
                jobTitle: model.title || model.display_input || model.job_id
                kindText: model.kind || "UNKNOWN"
                lifecycleText: model.lifecycle || "QUEUED"
                outcomeText: model.outcome || ""
                activityText: model.primary_activity || ""
                waitingText: model.waiting_reason || ""
                subtitleText: model.display_input || ""
                progressValue: model.progress === null || model.progress === undefined ? -1 : model.progress
                artifactDone: model.artifact_committed || 0
                artifactTotal: model.artifact_total || 0
                committedBytes: model.committed_bytes || 0
                expectedBytes: model.expected_bytes || 0
                filePath: model.primary_file_path || ""
                errorCode: model.latest_error_code || ""
                nativeCode: model.latest_native_code || ""
                cancellable: model.control_intent !== "CANCEL_REQUESTED" && appController.canJobAction(model.lifecycle, "cancel")
                pausable: model.control_intent !== "PAUSE_REQUESTED" && appController.canJobAction(model.lifecycle, "pause")
                resumable: appController.canJobAction(model.lifecycle, "resume")
                onCancelRequested: appController.cancelJob(model.job_id)
                onPauseRequested: appController.pauseJob(model.job_id)
                onResumeRequested: appController.resumeJob(model.job_id)
                onOpenRequested: appController.openDownloadedFile(filePath)
                onRevealRequested: appController.revealDownloadedFile(filePath)
            }
            Label { anchors.centerIn: parent; visible: parent.count === 0; text: (appController.language, appController.trKey("downloads.empty")); color: DesignTokens.textTertiary }
        }
    }
}
