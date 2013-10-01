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


class IntegerFormatter(object):

    def __init__(self, line_edit):
        self.line_edit = line_edit

    def format(self, text):
        self.value = int(text)

    def __get_value(self):
        return int(self.line_edit.text)
    def __set_value(self, value):
        self.line_edit.text = str(value)
    value = property(__get_value, __set_value)


class FloatFormatter(object):

    def __init__(self, line_edit):
        self.line_edit = line_edit

    def format(self, text):
        self.value = float(text)

    def __get_value(self):
        return float(self.line_edit.text)
    def __set_value(self, value):
        self.line_edit.text = "%g" % float(value)
    value = property(__get_value, __set_value)


class ScalarController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property

        row = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.slider = self.ui.create_slider_widget()
        self.slider.maximum = 100
        self.slider.on_value_changed = lambda value: self.slider_value_changed(value)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.field_formatter = FloatFormatter(self.field)
        row.add(label)
        row.add(self.slider)
        row.add(self.field)
        row.add_stretch()
        self.widget = row.widget
        self.update()
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        value = getattr(self.object, self.property)
        self.field_formatter.value = float(value)
        self.slider.value = int(value * 100)
    def slider_value_changed(self, value):
        setattr(self.object, self.property, self.slider.value/100.0)
        self.update()
    def editing_finished(self, text):
        setattr(self.object, self.property, self.field_formatter.value)
        self.update()
        if self.field.focused:
            self.field.select_all()


class IntegerFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        row = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.field_formatter = IntegerFormatter(self.field)
        row.add(label)
        row.add(self.field)
        row.add_stretch()
        self.widget = row.widget
        self.update()
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.field_formatter.value = getattr(self.object, self.property)
    def editing_finished(self, text):
        setattr(self.object, self.property, self.field_formatter.value)
        if self.field.focused:
            self.field.select_all()


class FloatFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        row = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.field_formatter = FloatFormatter(self.field)
        row.add(label)
        row.add(self.field)
        row.add_stretch()
        self.widget = row.widget
        self.update()
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        self.field_formatter.value = getattr(self.object, self.property)
    def editing_finished(self, text):
        setattr(self.object, self.property, self.field_formatter.value)
        if self.field.focused:
            self.field.select_all()


class StringFieldController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        row = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        row.add(label)
        row.add(self.field)
        row.add_stretch()
        self.widget = row.widget
        self.update()
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        self.ui.Widget_removeWidget(self.widget)
    def update(self):
        value = getattr(self.object, self.property)
        self.field.text = str(value) if value else ""
    def editing_finished(self, text):
        setattr(self.object, self.property, text)
        if self.field.focused:
            self.field.select_all()


# fixed array means the user cannot add/remove items; but it still tracks additions/removals
# from its object.
class FixedArrayController(object):
    def __init__(self, ui, object, name, property, container_widget):
        self.ui = ui
        self.object = object
        self.property = property
        self.column = self.ui.create_column_widget()
        self.__columns = []
        array = getattr(self.object, property)
        for item in array:
            column_widget = self.ui.create_column_widget()
            controller = PropertyEditorController(self.ui, item, column_widget.widget)
            self.__columns.append((controller, column_widget.widget))
            self.column.add(column_widget)
        self.widget = self.column.widget
        self.ui.Widget_addWidget(container_widget, self.widget)
    def close(self):
        for controller, column_widget in self.__columns:
            controller.close()
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
        self.column = self.ui.create_column_widget()
        self.widget = self.column.widget
        item = getattr(self.object, property)
        self.controller = PropertyEditorController(self.ui, item, self.column.widget)
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

        # load the widget and associate it with this panel.
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
