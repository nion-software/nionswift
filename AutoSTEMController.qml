import QtQuick 1.0
import QtDesktop 0.1

Rectangle {

    id: simulator

    width: Math.max(childrenRect.width, 199)
    height: childrenRect.height

    color: Qt.rgba(0.87,0.89,0.91,1)
    
    Column {

        Button {
            text: "Measure"
            onClicked: {
                app.invokePyMethod(view, "measure", [])
            }
        }

        Button {
            text: "Correct"
            onClicked: {
                app.invokePyMethod(view, "correct", [])
            }
        }

       
    }

    Component.onCompleted: {
    }

} // Item
