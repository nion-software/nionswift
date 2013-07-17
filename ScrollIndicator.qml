// Based on https://projects.forum.nokia.com/qmluiexamples/browser/qml/qmluiexamples/Scrollable/ScrollBar.qml
import QtQuick 2.1

Rectangle {
    // The flickable to which the scrollbar is attached to, must be set
    property variant flickable

    // True for vertical ScrollBar, false for horizontal
    property bool vertical: true

    property int scrollbarWidth: 8

    property real baseOpacityOff: 1.0
    property real baseOpacityOn: 1.0

    radius: vertical ? width/2 : height/2

    function sbOpacity()
    {
        if (vertical ? (height >= parent.height) : (width >= parent.width)) {
            return 0;
        } else {
            return (flickable.flicking || flickable.moving) ? baseOpacityOn : baseOpacityOff;
        }
    }

    // Scrollbar appears automatically when content is bigger than the Flickable
    opacity: sbOpacity()
    color: "darkgray"

    // Calculate width/height and position based on the content size and position of
    // the Flickable
    width: vertical ? scrollbarWidth : flickable.visibleArea.widthRatio * parent.width
    height: vertical ? flickable.visibleArea.heightRatio * parent.height : scrollbarWidth
    x: vertical ? parent.width - width : flickable.visibleArea.xPosition * parent.width
    y: vertical ? flickable.visibleArea.yPosition * parent.height : parent.height - height

    // Animate scrollbar appearing/disappearing
    Behavior on opacity { NumberAnimation { duration: 200 }}
}
