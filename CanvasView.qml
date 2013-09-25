import QtQuick 2.1

Rectangle {

    id: root

    color: "#EEEEEE"

    property string js
    property int canvas_width: canvas.width
    property int canvas_height: canvas.height

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            var ctx = canvas.getContext('2d');
            ctx.save();
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            eval(js);
            ctx.restore();
        }
    } // Canvas

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        onClicked: {
            app.invokePyMethod(panel, "mouseClicked", [mouse.y, mouse.x, mouse.modifiers]) // use c-indexing
        }
        onDoubleClicked: {
            app.invokePyMethod(panel, "mouseDoubleClicked", [mouse.y, mouse.x, mouse.modifiers]) // use c-indexing
        }
        onPressed: {
            app.invokePyMethod(panel, "mousePressed", [mouse.y, mouse.x, mouse.modifiers]) // use c-indexing
        }
        onReleased: {
            app.invokePyMethod(panel, "mouseReleased", [mouse.y, mouse.x, mouse.modifiers]) // use c-indexing
        }
        onEntered: {
            app.invokePyMethod(panel, "mouseEntered", [])
        }
        onExited: {
            app.invokePyMethod(panel, "mouseExited", [])
        }
        onPositionChanged: {
            app.invokePyMethod(panel, "mousePositionChanged", [mouse.y, mouse.x, mouse.modifiers]) // use c-indexing
        }
    }

    onJsChanged: canvas.requestPaint()

    onWidthChanged: app.invokePyMethod(panel, "widthChanged", [root.width])
    onHeightChanged: app.invokePyMethod(panel, "heightChanged", [root.height])

} // Item
