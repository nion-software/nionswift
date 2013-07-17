import QtQuick 2.1
import QtQuick.Controls 1.0

Item {

    id: header

    property string title
	property string platform

    Rectangle {
		visible: platform == "darwin"
        anchors.fill: parent
        gradient: Gradient {
            GradientStop {
                position: 0
                color: "#ededed"
            }
           
            GradientStop {
                position: 1
                color: "#cacaca"
            }
        }
    } // Rectangle
    Rectangle {
		visible: platform == "darwin"
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: "white"
    }
    Rectangle {
		visible: platform == "darwin"
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: "#B0B0B0"
    }
    Text {
		visible: platform == "darwin"
        anchors.fill: parent
        text: title
        font.pointSize: 11
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    Rectangle {
		visible: platform == "win32"
		transform: [ Translate { x: 0; y: 1 } ]
        anchors.fill: parent
        color: "#DCDCDC"
		border.color: "#BABABA"
		border.width: 1
    }
    Rectangle {
		visible: platform == "win32"
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: "#BABABA"
    }
    Rectangle {
		visible: platform == "win32"
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 1
        height: parent.height-1
        color: "#BABABA"
    }
	Text {
        renderType: Text.NativeRendering
		visible: platform == "win32"
		transform: [ Translate { x: 2; y: 1 } ]
	    anchors.fill: parent
		text: title
        horizontalAlignment: Text.AlignLeft
        verticalAlignment: Text.AlignVCenter
	}

} // Item
