import QtQuick 2.1
import QtQuick.Controls 1.0

Window {

    title: "About Imaging"
    id: aboutBox
    visible: true

    width: 360
    height: 200

    Rectangle {

        width: aboutBox.width

        Column {

            width: aboutBox.width
            
            Text {
                id: title
                text: "Imaging 0.1"
                horizontalAlignment: Text.AlignCenter
                anchors.horizontalCenter: parent.horizontalCenter
                font.pointSize: 24; font.bold: true
            }

            Button {
                text:"Ok"
                anchors.horizontalCenter: parent.horizontalCenter
                onClicked: aboutBox.destroy()
            }
        }
    }
}
