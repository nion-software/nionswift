import QtQuick 2.1
import QtQuick.Controls 1.0

Rectangle {

    id: data_list_view

    property alias currentIndex: view.currentIndex
    property variant lastEvent

    color: "white"

    // handle clicks on empty area
    MouseArea {
        anchors.fill: parent
        onClicked: view.currentIndex = -1
    }

    DropArea {
        anchors.fill: parent

        keys: ["text/uri-list", "data_item_uuid"]

        property variant lastItem

        onEntered: {
            lastItem = null
        }
        onPositionChanged: {
            if (lastItem) lastItem.showDropHighlight = false
            if (view.indexAt(drag.x, drag.y) >= 0) {
                lastItem = view.itemAt(drag.x, drag.y)
                lastItem.showDropHighlight = true
            }
        }
        onExited: {
            if (lastItem) lastItem.showDropHighlight = false
            lastItem = null
        }

        onDropped: {
            if (lastItem) lastItem.showDropHighlight = false
            lastItem = null
            var dropIndex = view.indexAt(drag.x, drag.y)
            if (drop.hasUrls) {
                //console.log("dropped " + drop.urls)
                app.invokePyMethod(panel, "receiveUrls", [dropIndex, drop.urls])
                drop.accept(Qt.CopyAction)
            }
            else if (drop.formats.indexOf("data_item_uuid") >= 0) {
                // for some reason, source needs source.source rather than just source. could be a bug in Qt.
                var sourceIndex = drop.source.source.sourceIndex
                drop.accepted = true;
                if (drop.source.source.parent.parent == view) {
                    // moving within a single view (i.e. same window)
                    if (drop.proposedAction == Qt.MoveAction || drop.proposedAction == Qt.CopyAction) {
                        app.invokePyMethod(panel, "copyItem", [drop.getDataAsString("data_item_uuid"), sourceIndex, dropIndex])
                        drop.acceptProposedAction()
                    }
                }
                else {
                    // moving from one view to another (i.e. between windows)
                    console.log("different window")
                }
            }
        }
    }

    Component {
        id: delegate

        Rectangle {
            id: background

            height: background.showDropHighlight ? imageHeight + 16 : imageHeight
            width: view.width
            color: GridView.isCurrentItem ? "green" : "transparent"

            property int sourceIndex
            property bool showDropHighlight: false
            property real imageHeight: 72

            Behavior on anchors.leftMargin { NumberAnimation { duration: 100 } }

            MouseArea {
                id: mouseArea
                anchors.fill: parent
                onClicked: view.currentIndex = index
                drag.target: draggable
            }

            Row {
                anchors.left: background.left
                anchors.bottom: background.bottom
                height: background.imageHeight
                anchors.leftMargin: level * 16
                spacing: 8
                Image {
                    height: background.imageHeight
                    width: background.imageHeight
                    fillMode: Image.PreserveAspectFit
                    source: graphic_url
                    smooth: true
                }
                Item {
                    height: background.imageHeight
                    width: background.width - level * 16  - background.imageHeight - 8
                    Column {
                        anchors.topMargin: 6
                        anchors.fill: parent
                        Text {
                            text: display
                        } // Text
                        Text {
                            text: display2
                            font.italic: true
                        } // Text
                    } // Column
                }
            }

            Item {
                id: draggable
                Drag.active: mouseArea.drag.active
                Drag.hotSpot.x: 0
                Drag.hotSpot.y: 0
                // DND: Drag.mimeData: { "data_item_uuid": uuid }
                Drag.source: background  // use in onDropped
                x: background.x
                y: background.y
                z: 1
                width: background.width
                height: background.imageHeight
                opacity: 0.5
                visible: false
                Drag.onActiveChanged: {
                    if (draggable.Drag.active) {
                        var uuid_to_drag = uuid
                        background.sourceIndex = index  // lock this down rather than binding
                        var result = Qt.IgnoreAction // DND: draggable.Drag.startExternal()
                        if (result == Qt.MoveAction) {
                            app.invokePyMethod(panel, "deleteItemByUuid", [uuid_to_drag])
                        }
                    }
                }
            } // Item

        } // Rectangle
    } // Component

    ScrollView {
        anchors.fill: parent
        flickableItem.interactive: true
        focus: true
        ListView {
            id: view
            anchors.fill: parent
            model: browser_model
            delegate: delegate
            highlight: Rectangle { color: "lightsteelblue"; radius: 5 }
            spacing: 4
            focus: true
            highlightMoveVelocity: 10000
            highlightMoveDuration: 5
            onCurrentIndexChanged:
                app.invokePyMethod(panel, "dataListCurrentIndexChanged", [currentIndex])
            Component.onCompleted:
                currentIndex = -1
            Keys.onPressed:
                event.accepted = app.invokePyMethod(panel, "keyPressed", [event.text, event.key, event.modifiers])
        } // ListView
    } // ScrollView

} // Rectangle(data_list_view)
