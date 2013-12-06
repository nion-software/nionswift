# standard libraries
import copy
import gettext
import logging
import threading
import weakref

# third party libraries
# None

# local libraries
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


class PropertyBinding(object):
    def __init__(self, object, property):
        self.object = object
        self.property = property
    def __get_value(self):
        return getattr(self.object, self.property)
    def __set_value(self, value):
        setattr(self.object, self.property, value)
    value = property(__get_value, __set_value)


class ArrayBinding(object):
    def __init__(self, object, property, index):
        self.object = object
        self.property = property
        self.index = index
    def __get_value(self):
        return getattr(self.object, self.property)[self.index]
    def __set_value(self, value):
        getattr(self.object, self.property)[self.index] = value
    value = property(__get_value, __set_value)


class ScalarController(object):
    def __init__(self, ui, name, binding):
        self.ui = ui
        self.binding = binding
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
        value = self.binding.value
        self.field_formatter.value = float(value)
        self.slider.value = int(value * 100)
    def slider_value_changed(self, value):
        self.binding.value = self.slider.value/100.0
        self.update()
    def editing_finished(self, text):
        self.binding.value = self.field_formatter.value
        self.update()
        if self.field.focused:
            self.field.select_all()


class IntegerFieldController(object):
    def __init__(self, ui, name, binding):
        self.ui = ui
        self.binding = binding
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
        self.field_formatter.value = self.binding.value
    def editing_finished(self, text):
        self.binding.value = self.field_formatter.value
        if self.field.focused:
            self.field.select_all()


class FloatFieldController(object):
    def __init__(self, ui, name, binding):
        self.ui = ui
        self.binding = binding
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
        self.field_formatter.value = self.binding.value
    def editing_finished(self, text):
        self.binding.value = self.field_formatter.value
        if self.field.focused:
            self.field.select_all()


class StringFieldController(object):
    def __init__(self, ui, name, binding):
        self.ui = ui
        self.binding = binding
        self.widget = self.ui.create_row_widget()
        label = self.ui.create_label_widget(name)
        self.field = self.ui.create_line_edit_widget()
        self.field.on_editing_finished = lambda text: self.editing_finished(text)
        self.widget.add(label)
        self.widget.add(self.field)
        self.widget.add_stretch()
        self.update()
    def update(self):
        value = self.binding.value
        self.field.text = unicode(value) if value else unicode()
    def editing_finished(self, text):
        self.binding.value = text
        if self.field.focused:
            self.field.select_all()


# fixed array means the user cannot add/remove items; but it still tracks additions/removals
# from its object.
class FixedArrayController(object):
    def __init__(self, ui, object, name, property):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.create_column_widget()
        self.__columns = []
        array = getattr(self.object, property)
        for item in array:
            column_widget = self.ui.create_column_widget()
            controller = PropertyEditorController(self.ui, item)
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
class FloatArrayController(object):
    def __init__(self, ui, object, name, property):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.create_column_widget()
        self.__columns = []
        array = getattr(self.object, self.property)
        if array:
            for index, item in enumerate(array):
                column_widget = self.ui.create_column_widget()
                name = str(index)
                binding = ArrayBinding(object, property, index)
                controller = FloatFieldController(self.ui, name, binding)
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
    def __init__(self, ui, object, name, property):
        self.ui = ui
        self.object = object
        self.property = property
        self.widget = self.ui.create_column_widget()
        item = getattr(self.object, property)
        self.controller = PropertyEditorController(self.ui, item)
        self.widget.add(self.controller.widget)
    def close(self):
        if hasattr(self.controller, 'close'):
            self.controller.close()
    def update(self):
        self.controller.update()


def construct_controller(ui, object, type, name, property):
    controller = None
    if type == "scalar":
        controller = ScalarController(ui, name, PropertyBinding(object, property))
    elif type == "integer-field":
        controller = IntegerFieldController(ui, name, PropertyBinding(object, property))
    elif type == "float-field":
        controller = FloatFieldController(ui, name, PropertyBinding(object, property))
    elif type == "string-field":
        controller = StringFieldController(ui, name, PropertyBinding(object, property))
    elif type == "fixed-array":
        controller = FixedArrayController(ui, object, name, property)
    elif type == "float-array":
        controller = FloatArrayController(ui, object, name, property)
    elif type == "item":
        controller = ItemController(ui, object, name, property)
    return controller


class PropertyEditorController(object):

    def __init__(self, ui, object):
        self.ui = ui
        self.object = object
        self.__controllers = dict()
        self.__editor = None
        self.__updated_properties = set()
        self.__updated_properties_mutex = threading.RLock()
        self.widget = self.ui.create_column_widget()
        # add self as observer. this will result in property_changed messages.
        self.object.add_observer(self)
        self.__editor = object.create_editor(self.ui)
        if self.__editor:
            self.widget.add(self.__editor.widget)
        for description in object.description:
            name = description["name"]
            type = description["type"]
            property = description["property"]
            controller = construct_controller(self.ui, self.object, type, name, property)
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
        if self.__editor:
            self.__editor.close()
        self.__controllers = {}

    def periodic(self):
        with self.__updated_properties_mutex:
            updated_properties = self.__updated_properties
            self.__updated_properties = set()
        for updated_property in updated_properties:
            if updated_property in self.__controllers:
                self.__controllers[updated_property].update()
        if self.__editor:
            self.__editor.periodic()

    def property_changed(self, sender, property, value):
        with self.__updated_properties_mutex:
            self.__updated_properties.add(property)

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

        self.__rebuild = False
        self.__rebuild_data_item = None
        self.__rebuild_mutex = threading.RLock()

        self.data_item_binding = document_controller.create_selected_data_item_binding()

        # connect self as listener. this will result in calls to data_item_changed
        self.data_item_binding.add_listener(self)

        self.widget = self.column

    def close(self):
        # first set the data item to None
        # this has the side effect of closing the stack groups.
        self.data_item_changed(None)
        # disconnect self as listener
        self.data_item_binding.remove_listener(self)
        # close the property controller
        self.data_item_binding.close()
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
            self.property_editor_controller = PropertyEditorController(self.ui, operation)
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

    def periodic(self):
        super(ProcessingPanel, self).periodic()
        with self.__rebuild_mutex:
            rebuild = self.__rebuild
            data_item = self.__rebuild_data_item
            self.__rebuild = False
            self.__rebuild_data_item = None
        if rebuild:
            operations = data_item.operations if data_item and data_item else []
            self.rebuild_panel(operations)

    # this message is received from the document controller.
    # it is established using add_listener
    def data_item_changed(self, data_item):
        # TODO: THIS IS WRONG. WE NEED TO KNOW WHETHER IT WAS JUST DATA.
        # IF JUST DATA, DO NOT REBUILD HERE. ALSO, WHAT IF IT'S JUST A
        # THUMBNAIL?
        with self.__rebuild_mutex:
            self.__rebuild = True
            self.__rebuild_data_item = data_item


class InspectorPanel(Panel.Panel):
    def __init__(self, document_controller, panel_id, properties):
        super(InspectorPanel, self).__init__(document_controller, panel_id, _("Inspector"))

        self.column = self.ui.create_column_widget(properties)

        self.__data_item = None
        self.__pec = None

        self.__update_data_item = False
        self.__update_data_item_data_item = None
        self.__update_data_item_mutex = threading.RLock()

        self.data_item_binding = document_controller.create_selected_data_item_binding()
        self.data_item = None

        # connect self as listener. this will result in calls to data_item_changed
        self.data_item_binding.add_listener(self)

        self.widget = self.column

    def close(self):
        # first set the data item to None
        self.data_item_changed(None)
        # disconnect self as listener
        self.data_item_binding.remove_listener(self)
        # close the property controller
        self.data_item_binding.close()
        self.data_item = None
        # finish closing
        super(InspectorPanel, self).close()

    def periodic(self):
        super(InspectorPanel, self).periodic()
        if self.__pec:
            self.__pec.periodic()
        with self.__update_data_item_mutex:
            update_data_item = self.__update_data_item
            data_item = self.__update_data_item_data_item
            self.__update_data_item = False
            self.__update_data_item_data_item = None
        if update_data_item:
            if self.data_item != data_item:
                self.data_item = data_item

    def __update_property_editor_controller(self):
        if self.__pec:
            self.column.remove(self.__pec.widget)
            self.__pec.close()
            self.__pec = None
        if self.__data_item:
            self.__pec = PropertyEditorController(self.ui, self.__data_item)
            self.column.add(self.__pec.widget)

    def __get_data_item(self):
        return self.__data_item
    def __set_data_item(self, data_item):
        if self.__data_item != data_item:
            self.__data_item = data_item
            self.__update_property_editor_controller()
            self.image_canvas_zoom = 1.0
    data_item = property(__get_data_item, __set_data_item)

    # this message is received from the data item binding.
    # it is established using add_listener
    def data_item_changed(self, data_item):
        with self.__update_data_item_mutex:
            self.__update_data_item = True
            self.__update_data_item_data_item = data_item
