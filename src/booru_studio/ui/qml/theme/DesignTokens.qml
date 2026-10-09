pragma Singleton
import QtQuick

QtObject {
    // Booru Studio language: Apple hierarchy/craft + One UI reachability + Windows familiarity.
    // Feature QML consumes semantic roles only; palette values live in this one layer.
    readonly property color windowBackground: "#0E1117"
    readonly property color navigationSurface: "#121821"
    readonly property color contentSurface: "#171D27"
    readonly property color elevatedSurface: "#1C2430"
    readonly property color hairline: "#2A3442"

    readonly property color textPrimary: "#F5F7FB"
    readonly property color textSecondary: "#99A6B8"
    readonly property color textTertiary: "#7D8999"
    readonly property color navigationText: "#F6F8FC"

    readonly property color accent: "#7EAEFF"
    readonly property color accentText: "#AFCBFF"
    readonly property color accentSurface: "#23324A"
    readonly property color kindText: "#A9BDD9"
    readonly property color kindSurface: "#202A38"
    readonly property color phaseAccent: "#B8A5FF"

    readonly property color positive: "#7FD6A6"
    readonly property color positiveText: "#8DE3B5"
    readonly property color positiveSurface: "#183A2A"
    readonly property color warning: "#E4BE69"
    readonly property color warningText: "#E7C36B"
    readonly property color warningSurface: "#44391E"
    readonly property color negative: "#F09AA6"
    readonly property color negativeText: "#F2A5AE"
    readonly property color negativeSurface: "#2B2025"
    readonly property color negativeBorder: "#6A3D45"

    readonly property int radiusSmall: 8
    readonly property int radiusMedium: 14
    readonly property int radiusLarge: 20
    readonly property int space1: 4
    readonly property int space2: 8
    readonly property int space3: 12
    readonly property int space4: 16
    readonly property int space6: 24
    readonly property int navWidth: 232
    readonly property int minimumHitTarget: 40
    readonly property int titleLarge: 28
    readonly property int titleMedium: 20
    readonly property int body: 14
    readonly property int caption: 11
    readonly property int motionFast: 100
    readonly property int motionNormal: 180
}
