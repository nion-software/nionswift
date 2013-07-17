import QtQuick 2.1
import QtQuick.Controls 1.0

Item {

    id: root

    property string title
    property bool itemFocused: typeof(focused) !== 'undefined' ? focused : false
    property real zoom: 1.0
    property real translateX: 0
    property real translateY: 0
    property real imageWidth: 0
    property real imageHeight: 0
    property string overlay

    Item {
        id: item

        anchors.fill: parent

        Column {
            anchors.fill: parent
            anchors.top: parent.top
            spacing: 0

            Item {
                id: body
                height: parent.height
                width: parent.width

        Column {
            anchors.fill: parent
            anchors.top: parent.top
            spacing: 0
            clip:true

            Item {
                id: viewer
                height: parent.height
                width: parent.width
                clip:true

                // image area background
                Rectangle {
                    anchors.fill: parent
                    color: "transparent"
                } // Rectangle

                Image {
                    // the size of the image is image.sourceSize.width, image.sourceSize.height
                    id: image
                    fillMode: Image.PreserveAspectFit
                    //smooth: true
                    transform: [
                        Translate {
                            x: translateX; y: translateY
                            Behavior on x { PropertyAnimation { duration: 35 } }
                            Behavior on y { PropertyAnimation { duration: 35 } }
                        },
                        Scale {
                            xScale: zoom; yScale: zoom;
                            origin.x: viewer.x + viewer.width*0.5; origin.y: viewer.y + viewer.height*0.5
                            Behavior on xScale { PropertyAnimation { duration: 35 } }
                            Behavior on yScale { PropertyAnimation { duration: 35 } }
                        }
                    ]
                    anchors.fill: parent
                    MouseArea {
                        id: mouseArea
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        hoverEnabled: true
                        onClicked: {
                            app.invokePyMethod(panel, "mouseClicked", [mouse.y, mouse.x, mouse.modifiers]) // use c-indexing
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
                    focus: true
                    Keys.onPressed: {
                        event.accepted = app.invokePyMethod(panel, "keyPressed", [event.text, event.key, event.modifiers])
                    }
                    onXChanged: app.invokePyMethod(panel, "resized", [image.x, image.y, image.width, image.height])
                    onYChanged: app.invokePyMethod(panel, "resized", [image.x, image.y, image.width, image.height])
                    onHeightChanged: { imageHeight = image.height; app.invokePyMethod(panel, "resized", [image.x, image.y, image.width, image.height]) }
                    onWidthChanged: { imageWidth = image.width; app.invokePyMethod(panel, "resized", [image.x, image.y, image.width, image.height]) }
                } // Image

                Canvas {
                    id:canvas
                    anchors.fill: parent
                    onPaint: {
                        var ctx = canvas.getContext('2d');
                        ctx.save();
                        ctx.clearRect(0, 0, canvas.width, canvas.height);
                        eval(overlay);
                        ctx.restore();
                    }
                } // Canvas

                // image area selection
                Rectangle {
                    anchors.fill: parent
                    color: "transparent"
                    border.width: root.itemFocused ? 3 : 0
                    border.color: "blue"
                    opacity: 0.5
                } // Rectangle

            } // Item(viewer)

            } // Column

            } // Item(body)

        } // Column

    } // Item

    Component.onCompleted: {
        app.idc.imageUpdated.connect(updateImage)
    }

    onZoomChanged: app.invokePyMethod(panel, "display_changed", [])
    onTranslateXChanged: app.invokePyMethod(panel, "display_changed", [])
    onTranslateYChanged: app.invokePyMethod(panel, "display_changed", [])

    onOverlayChanged: canvas.requestPaint()

    function updateImage(controller_id, url) {
        // Compare the controller_id to the uuid from the Python view object to see if this
        // message is coming from the display controller associated with this Qml item.
        var uuid_str = app.invokePyMethod(panel, "get_uuid_str", [])
        if (controller_id == uuid_str) {
            image.source = url
        }
    }

} // Item
