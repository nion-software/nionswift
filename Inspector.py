# standard libraries
import copy
import gettext
import logging
import weakref

# third party libraries
# None

# local libraries
from nion.swift.Decorators import queue_main_thread
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
    def __init__(self, ui, document_controller, object, name, property):
        self.ui = ui
        self.document_controller = document_controller
        self.object = object
        self.property = property

        self.widget = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.slider = self.ui.create_slider_widget()
        self.slider.maximum = 100
        self.slider.on_value_changed = lambda value: self.slider_value_changed(value)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.field_formatter = FloatFormatter(self.field)
        self.widget.add(label)
        self.widget.add(self.slider)
        self.widget.add(self.field)
        self.widget.add_stretch()
        self.update()
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
    def __init__(self, ui, document_controller, object, name, property):
        self.ui = ui
        self.document_controller = document_controller
        self.object = object
        self.property = property
        self.widget = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.field_formatter = IntegerFormatter(self.field)
        self.widget.add(label)
        self.widget.add(self.field)
        self.widget.add_stretch()
        self.update()
    def update(self):
        self.field_formatter.value = getattr(self.object, self.property)
    def editing_finished(self, text):
        setattr(self.object, self.property, self.field_formatter.value)
        if self.field.focused:
            self.field.select_all()


class FloatFieldController(object):
    def __init__(self, ui, document_controller, object, name, property):
        self.ui = ui
        self.document_controller = document_controller
        self.object = object
        self.property = property
        self.widget = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.field_formatter = FloatFormatter(self.field)
        self.widget.add(label)
        self.widget.add(self.field)
        self.widget.add_stretch()
        self.update()
    def update(self):
        self.field_formatter.value = getattr(self.object, self.property)
    def editing_finished(self, text):
        setattr(self.object, self.property, self.field_formatter.value)
        if self.field.focused:
            self.field.select_all()


class StringFieldController(object):
    def __init__(self, ui, document_controller, object, name, property):
        self.ui = ui
        self.document_controller = document_controller
        self.object = object
        self.property = property
        self.widget = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.widget.add(label)
        self.widget.add(self.field)
        self.widget.add_stretch()
        self.update()
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
    def __init__(self, ui, document_controller, object, name, property):
        self.ui = ui
        self.document_controller = document_controller
        self.object = object
        self.property = property
        self.widget = self.ui.create_column_widget()
        self.__columns = []
        array = getattr(self.object, property)
        for item in array:
            column_widget = self.ui.create_column_widget()
            controller = PropertyEditorController(self.ui, self.document_controller, item)
            column_widget.add(controller.widget)
            self.__columns.append(controller)
            self.widget.add(column_widget)
    def close(self):
        for controller in self.__columns:
            if hasattr(controller, 'close'):
                controller.close()
    def update(self):
        for controller in self.__columns:
            controller.update()


# fixed array means the user cannot add/remove items; but it still tracks additions/removals
# from its object.
class ItemController(object):
    def __init__(self, ui, document_controller, object, name, property):
        self.ui = ui
        self.document_controller = document_controller
        self.object = object
        self.property = property
        self.widget = self.ui.create_column_widget()
        item = getattr(self.object, property)
        self.controller = PropertyEditorController(self.ui, self.document_controller, item)
        self.widget.add(self.controller.widget)
    def close(self):
        if hasattr(self.controller, 'close'):
            self.controller.close()
    def update(self):
        self.controller.update()


def construct_controller(ui, document_controller, object, type, name, property):
    controller = None
    if type == "scalar":
        controller = ScalarController(ui, document_controller, object, name, property)
    elif type == "integer-field":
        controller = IntegerFieldController(ui, document_controller, object, name, property)
    elif type == "float-field":
        controller = FloatFieldController(ui, document_controller, object, name, property)
    elif type == "string-field":
        controller = StringFieldController(ui, document_controller, object, name, property)
    elif type == "fixed-array":
        controller = FixedArrayController(ui, document_controller, object, name, property)
    elif type == "item":
        controller = ItemController(ui, document_controller, object, name, property)
    return controller


class PropertyEditorController(object):

    def __init__(self, ui, document_controller, object):
        self.ui = ui
        self.document_controller = document_controller
        self.object = object
        self.__controllers = {}
        self.widget = self.ui.create_column_widget()
        # add self as observer. this will result in property_changed messages.
        self.object.add_observer(self)
        for dict in object.description:
            name = dict["name"]
            type = dict["type"]
            property = dict["property"]
            controller = construct_controller(self.ui, document_controller, self.object, type, name, property)
            if controller:
                self.widget.add(controller.widget)
                self.__controllers[property] = controller
            else:
                logging.debug("Unknown controller type %s", type)
        self.widget.add_stretch()

    def close(self):
        # stop observing
        self.object.remove_observer(self)
        # delete widgets
        for controller in self.__controllers.values():
            if hasattr(controller, 'close'):
                controller.close()
        self.__controllers = {}

    # used for queue_main_thread decorator
    delay_queue = property(lambda self: self.document_controller.delay_queue)

    @queue_main_thread
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

    def __init__(self, document_controller, panel_id, properties):
        super(ProcessingPanel, self).__init__(document_controller, panel_id, _("Processing"))

        # the main column widget contains a stack group for each operation
        self.column = self.ui.create_column_widget(properties)  # TODO: put this in scroll area
        self.column.add_stretch()
        self.__stack_groups = []

        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)

        self.widget = self.column

    def close(self):
        # first set the data item to None
        # this has the side effect of closing the stack groups.
        self.selected_data_item_changed(None, {"property": "source"})
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        super(ProcessingPanel, self).close()

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
            self.widget = self.ui.create_column_widget()
            self.control_row = self.ui.create_row_widget()
            label = self.ui.create_label_widget(operation.name)
            remove_button = self.ui.create_push_button_widget(_("Remove"))
            remove_button.on_clicked = lambda: self.remove_pressed()
            self.control_row.add(label)
            self.control_row.add_stretch()
            self.control_row.add(remove_button)
            self.container_widget = self.ui.create_column_widget()
            self.widget.add(self.control_row)
            self.widget.add(self.container_widget)
            self.widget.add_stretch()
            self.property_editor_controller = PropertyEditorController(self.ui, self.document_controller, operation)
            self.container_widget.add(self.property_editor_controller.widget)
        def __get_document_controller(self):
            return self.__document_controller_weakref()
        document_controller = property(__get_document_controller)
        def __get_ui(self):
            return self.document_controller.ui
        ui = property(__get_ui)
        def close(self):
            self.property_editor_controller.close()
            self.operation.remove_observer(self)
        # receive change notifications from the operation. this connection is established
        # using add_observer/remove_observer.
        def property_changed(self, sender, property, value):
            if property == "enabled":
                pass  # TODO: allow enabled/disabled operations?
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
        def remove_pressed(self):
            self.document_controller.remove_operation(self.operation)

    def rebuild_panel(self, operations):
        if self.column:
            for stack_group in copy.copy(self.__stack_groups):
                stack_group.close()
                self.column.remove(stack_group.widget)
            self.__stack_groups = []
            for operation in reversed(operations):
                stack_group = self.StackGroup(self, operation)
                self.column.insert(stack_group.widget, 0)
                self.__stack_groups.append(stack_group)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, info):
        operations = data_item.operations if data_item and data_item else []
        if info["property"] != "data":
            self.rebuild_panel(operations)


class InspectorPanel(Panel.Panel):
    def __init__(self, document_controller, panel_id, properties):
        super(InspectorPanel, self).__init__(document_controller, panel_id, _("Inspector"))

        self.column = self.ui.create_column_widget(properties)

        self.__data_item = None
        self.__pec = None

        self.data_item = None

        # connect self as listener. this will result in calls to selected_data_item_changed
        self.document_controller.add_listener(self)

        self.widget = self.column

    def close(self):
        # close the property controller
        self.data_item = None
        # first set the data item to None
        self.selected_data_item_changed(None, {"property": "source"})
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        # finish closing
        super(InspectorPanel, self).close()

    def __update_property_editor_controller(self):
        if self.__pec:
            self.column.remove(self.__pec.widget)
            self.__pec.close()
            self.__pec = None
        if self.__data_item:
            self.__pec = PropertyEditorController(self.ui, self.document_controller, self.__data_item)
            self.column.add(self.__pec.widget)

    def __get_data_item(self):
        return self.__data_item
    def __set_data_item(self, data_item):
        if self.__data_item != data_item:
            self.__data_item = data_item
            self.__update_property_editor_controller()
            self.image_canvas_zoom = 1.0
    data_item = property(__get_data_item, __set_data_item)

    # this message is received from the document controller.
    # it is established using add_listener
    def selected_data_item_changed(self, data_item, info):
        if self.data_item != data_item:
            self.data_item = data_item
