# standard libraries
import gettext
import logging
import weakref

# third party libraries
# None

# local libraries
from nion.swift.Decorators import queue_main_thread
from nion.swift.Decorators import queue_main_thread_sync
from nion.swift import Panel

_ = gettext.gettext


# Connect a user interface to an observable object, based on the description of the object.
# Changes to the object's properties will result in changes to the UI.
# Changes to the UI will result in changes to the object's properties.


class ScalarController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pyscalar")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, property)))
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, self.property)))


class IntegerFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pyintegerfield")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        self.ui.PyControl_setIntegerValue(self.widget, int(getattr(self.object, property)))
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setIntegerValue(self.widget, int(getattr(self.object, self.property)))


class FloatFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pyfloatfield")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, property)))
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setFloatValue(self.widget, float(getattr(self.object, self.property)))


class StringFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("pystringfield")
        self.ui.PyControl_connect(self.widget, self.object, property)
        self.ui.PyControl_setTitle(self.widget, name)
        value = getattr(self.object, property)
        self.ui.PyControl_setStringValue(self.widget, str(value) if value else "")
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.ui.PyControl_setStringValue(self.widget, str(getattr(self.object, self.property)))


# fixed array means the user cannot add/remove items; but it still tracks additions/removals
# from its object.
class FixedArrayController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("column")
        self.__columns = []
        array = getattr(self.object, property)
        for item in array:
            column_widget = self.ui.Widget_loadIntrinsicWidget("column")
            controller = PropertyEditorController(self.ui, item, column_widget)
            self.__columns.append((controller, column_widget))
            self.ui.Widget_addWidget(self.widget, column_widget)
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        for column in self.__columns:
            column[0].close()
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        for controller, column_widget in self.__columns:
            controller.update()


# fixed array means the user cannot add/remove items; but it still tracks additions/removals
# from its object.
class ItemController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.Widget_loadIntrinsicWidget("column")
        self.columns = None
        item = getattr(self.object, property)
        self.controller = PropertyEditorController(self.ui, item, self.widget)
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.controller.close()
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.controller.update()


def construct_controller(ui, object, type, name, property, container_widget):
    controller = None
    if type == "scalar":
        controller = ScalarController(ui, object, name, property, container_widget)
    elif type == "integer-field":
        controller = IntegerFieldController(ui, object, name, property, container_widget)
    elif type == "float-field":
        controller = FloatFieldController(ui, object, name, property, container_widget)
    elif type == "string-field":
        controller = StringFieldController(ui, object, name, property, container_widget)
    elif type == "fixed-array":
        controller = FixedArrayController(ui, object, name, property, container_widget)
    elif type == "item":
        controller = ItemController(ui, object, name, property, container_widget)
    return controller

class PropertyEditorController(object):

    def __init__(self, ui, object, container_widget):
        self.ui = ui
        self.object = object
        self.__controllers = {}
        # add self as observer. this will result in property_changed messages.
        self.object.add_observer(self)
        for dict in object.description:
            name = dict["name"]
            type = dict["type"]
            property = dict["property"]
            controller = construct_controller(self.ui, self.object, type, name, property, container_widget)
            if controller:
                self.__controllers[property] = controller
            else:
                logging.debug("Unknown controller type %s", type)

    def close(self):
        # stop observing
        self.object.remove_observer(self)
        # delete widgets
        for controller in self.__controllers.values():
            controller.close()
        self.__controllers = {}

    def property_changed(self, sender, property, value):
        if property in self.__controllers:
            self.__controllers[property].update()

    def update(self):
        for controller in self.__controllers.values():
            controller.update()


class ProcessingPanel(Panel.Panel):

    """
        The processing panel watches for changes to the selected image panel,
        changes to the data item of the image panel, and changes to the
        data item itself.
        """

    def __init__(self, document_controller, panel_id):
        Panel.Panel.__init__(self, document_controller, panel_id, _("Processing"))

        # load the Qml and associate it with this panel.
        self.widget = self.loadIntrinsicWidget("pystack")
        self.__stack_groups = []

        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)

    def close(self):
        # first set the data item to None
        self.selected_data_item_changed(None, {"property": "source"})
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        Panel.Panel.close(self)

    # represents the UI for a specific data item (operation) in the image
    # source chain. for instance, an data item chain might have a structure
    # like display -> fft -> invert -> data. this class might represent the
    # controls for the invert step.
    class StackGroup(object):
        def __init__(self, panel, operation):
            self.__document_controller_weakref = weakref.ref(panel.document_controller)
            self.operation = operation
            # add self as observer. this will result in property_changed messages.
            # needed to handle 'enabled'
            self.operation.add_observer(self)
            self.stack_group_widget = panel.loadIntrinsicWidget("pystackgroup")
            self.ui.PyStackGroup_connect(self.stack_group_widget, self, "enabled", "add_pressed", "remove_pressed")
            self.ui.PyStackGroup_setTitle(self.stack_group_widget, operation.name)
            self.ui.PyStackGroup_setEnabled(self.stack_group_widget, self.operation.enabled)
            self.property_editor_controller = PropertyEditorController(self.ui, operation, self.ui.PyStackGroup_content(self.stack_group_widget))
        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)
        def __get_ui(self):
            return self.document_controller.ui
        ui = property(__get_ui)
        def close(self):
            self.property_editor_controller.close()
            self.operation.remove_observer(self)
            self.ui.Widget_removeWidget(self.stack_group_widget)
        # receive change notifications from the operation. this connection is established
        # using add_observer/remove_observer.
        def property_changed(self, sender, property, value):
            if property == "enabled":
                self.ui.PyStackGroup_setEnabled(self.stack_group_widget, value)
        def __get_enabled(self):
            return self.operation.enabled
        def __set_enabled(self, enabled):
            try:  # try/except is for testing
                self.operation.enabled = enabled
            except Exception, e:
                import traceback
                traceback.print_exc()
                raise
        enabled = property(__get_enabled, __set_enabled)
        def add_pressed(self):
            logging.debug("add")
        def remove_pressed(self):
            self.document_controller.remove_operation(self.operation)

    # used for queue_main_thread decorator
    delay_queue = property(lambda self: self.document_controller.delay_queue)

    @queue_main_thread
    def rebuild_panel(self, operations):
        if self.widget:
            for stack_group in self.__stack_groups:
                stack_group.close()
            self.ui.Widget_removeAll(self.ui.PyStack_content(self.widget))
            self.__stack_groups = []
            for operation in operations:
                stack_group = self.StackGroup(self, operation)
                self.ui.Widget_addWidget(self.ui.PyStack_content(self.widget), stack_group.stack_group_widget)
                self.__stack_groups.append(stack_group)
            self.ui.Widget_addStretch(self.ui.PyStack_content(self.widget))

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, info):
        operations = data_item.operations if data_item and data_item else []
        if info["property"] != "data":
            self.rebuild_panel(operations)
