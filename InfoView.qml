import QtQuick 2.1
import QtQuick.Controls 1.0

Rectangle {

    id: root

    color: "#EEEEEE"

    Column {

        anchors.fill: parent
        
        Row {
            Text {
                renderType: Text.NativeRendering
                text: "Position: "
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                renderType: Text.NativeRendering
                text: typeof(position_text) !== 'undefined' ? position_text : ""
                anchors.verticalCenter: parent.verticalCenter
            }
        } // Row
        Row {
            Text {
                renderType: Text.NativeRendering
                text: "Value: "
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                renderType: Text.NativeRendering
                text: typeof(value_text) !== 'undefined' ? value_text : ""
                anchors.verticalCenter: parent.verticalCenter
            }
        } // Row
        Row {
            Text {
                renderType: Text.NativeRendering
                text: typeof(graphic_text) !== 'undefined' ? graphic_text : ""
                anchors.verticalCenter: parent.verticalCenter
            }
        } // Row

    } // Column

} // Rectangle
