 import QtQuick 2.1

 Item {
     id: stackWidget
     anchors.fill: parent

     // Setting the default property to stack.children means any child items
     // of the StackWidget are actually added to the 'stack' item's children.
     // See the "Property Binding" documentation for details on default properties.
     default property alias content: stack.children

     property int current: 0

     onCurrentChanged: setOpacities()
     Component.onCompleted: setOpacities()

     function setOpacities() {
         for (var i = 0; i < stack.children.length; ++i) {
             stack.children[i].opacity = (i == current ? 1 : 0)
         }
     }

     Item {
         id: stack
         anchors.fill: parent
     }
 }
