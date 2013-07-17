import QtQuick 2.1

Item {

    Component {

        id: buttonDelegate
        Rectangle {
            id: buttonRect
            height: 22
            width: 150
            gradient: grad1
            border.color: "grey"
            radius: 8
            smooth: true
            Text {
                anchors.centerIn: parent
                text: buttonTitle
            } // Text
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    app.invokePyMethod(panel, "buttonClicked", [index])
                }
                onEntered: { buttonRect.state = "hover"; }
                onExited: { buttonRect.state = "normal" }
                onPressed: { buttonRect.state = "pressed" }
                onReleased: { buttonRect.state = "normal" }
            }
            states: [
                State {
                    name: "normal"
                    PropertyChanges {
                        target: buttonRect;
                        gradient: grad1
                    }
                },
                State {
                    name: "hover"
                    PropertyChanges {
                        target: buttonRect;
                        gradient: grad2
                    }
                },
                State {
                    name: "pressed"
                    PropertyChanges {
                        target: buttonRect;
                        gradient: grad3
                    }
                }
            ]
            state: "normal"
        }

    } // Component

    ListView {

        anchors.fill: parent
        model: buttonListModel
        delegate: buttonDelegate
        orientation: ListView.Horizontal
        spacing: 12

    } // ListView

}
