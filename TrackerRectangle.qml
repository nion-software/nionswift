Rectangle {
    id: rect
    width: 100
    height: 100
    color: "red"
    opacity: 0.5
    transform: Translate { id: rect_translation }
    MouseArea {
        state: "PRESSED"
        states: [
            State {
                name: "NOT PRESSED"
            },
            State {
                name: "PRESSED"
            }
        ]
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        property variant mouseStart: Qt.point(0, 0)
        onPressed: {
            state = "PRESSED";
            mouseStart = Qt.point(mouse.x, mouse.y);
        }
        onReleased: state = "NOT PRESSED"
        onPositionChanged: {
            if (state == "PRESSED") {
                rect_translation.x += mouse.x - mouseStart.x
                rect_translation.y += mouse.y - mouseStart.y
            }
        }
    } // MouseArea
} // Rectangle
