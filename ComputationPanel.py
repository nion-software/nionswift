# futures
from __future__ import absolute_import

# standard libraries
import copy
import gettext
import operator
import re
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.swift import Panel
from nion.ui import Binding
from nion.ui import Converter
from nion.ui import Event

_ = gettext.gettext


class ComputationModel(object):
    """Represents a computation. Tracks a display specifier for changes to it and its computation content.

    Provides read/write access to the computation_text via the property.

    Provides a computation_text_changed event, always fired on UI thread.
    """

    def __init__(self, document_controller, display_specifier_binding):
        self.__weak_document_controller = weakref.ref(document_controller)
        self.__display_specifier = DataItem.DisplaySpecifier()
        # thread safe.
        def data_item_changed(data_item):
            def update_display_specifier():
                self.__set_display_specifier(DataItem.DisplaySpecifier.from_data_item(data_item))
            self.document_controller.add_task("update_display_specifier" + str(id(self)), update_display_specifier)
        self.__data_item_changed_event_listener = display_specifier_binding.data_item_changed_event.listen(data_item_changed)
        self.__set_display_specifier(DataItem.DisplaySpecifier())
        self.__computation_changed_or_mutated_event_listener = None
        self.__computation_object_inserted_event_listener = None
        self.__computation_object_removed_event_listener = None
        self.__computation_variable_inserted_event_listener = None
        self.__computation_variable_removed_event_listener = None
        self.__computation_text = None
        self.__error_text = None
        self.__object_property_changed_event_listeners = dict()
        self.__variable_property_changed_event_listeners = dict()
        self.computation_text_changed_event = Event.Event()
        self.error_text_changed_event = Event.Event()
        self.object_inserted_event = Event.Event()
        self.object_removed_event = Event.Event()
        self.variable_inserted_event = Event.Event()
        self.variable_removed_event = Event.Event()

    def close(self):
        self.document_controller.clear_task("update_display_specifier" + str(id(self)))
        self.__data_item_changed_event_listener.close()
        self.__data_item_changed_event_listener = None
        self.__set_display_specifier(DataItem.DisplaySpecifier())

    @property
    def document_controller(self):
        return self.__weak_document_controller()

    @property
    def display_specifier(self):
        return self.__display_specifier

    @property
    def __computation(self):
        buffered_data_source = self.__display_specifier.buffered_data_source
        if buffered_data_source:
            return buffered_data_source.computation
        return None

    def add_object(self, name: str, object=None) -> Symbolic.ComputationObject:
        computation = self.__computation
        if computation:
            object_specifier = self.document_controller.document_model.get_object_specifier(object)
            return computation.create_object(name, object_specifier)
        return None

    def remove_object(self, object: Symbolic.ComputationObject) -> None:
        computation = self.__computation
        if computation:
            computation.remove_object(object)

    def add_variable(self, name: str, value=None) -> Symbolic.ComputationVariable:
        computation = self.__computation
        if computation:
            return computation.create_variable(name, value)
        return None

    def remove_variable(self, variable: Symbolic.ComputationVariable) -> None:
        computation = self.__computation
        if computation:
            computation.remove_variable(variable)

    @property
    def computation_text(self):
        return self.__computation_text

    @computation_text.setter
    def computation_text(self, computation_text):
        buffered_data_source = self.__display_specifier.buffered_data_source
        if buffered_data_source:
            computation = buffered_data_source.computation
            if not computation:
                computation = Symbolic.Computation()
            computation.parse_expression(self.document_controller.document_model, computation_text, self.document_controller.build_variable_map())
            buffered_data_source.computation = computation

    @property
    def error_text(self):
        return self.__error_text

    def __update_computation_text(self, computation_text):
        if self.__computation_text != computation_text:
            self.__computation_text = computation_text
            self.computation_text_changed_event.fire(self.__computation_text)

    def __update_error_text(self, error_text):
        if self.__error_text != error_text:
            self.__error_text = error_text
            self.error_text_changed_event.fire(self.__error_text)

    def clear(self):
        buffered_data_source = self.__display_specifier.buffered_data_source
        if buffered_data_source:
            buffered_data_source.set_computation(None)

    def __computation_changed_or_mutated(self) -> None:
        expression = None
        error_text = None
        computation = self.__computation
        if computation:
            error_text = computation.error_text
            if error_text is not None:
                expression = computation.original_expression
            else:
                expression = computation.reconstruct(self.document_controller.build_variable_map())
        self.__update_computation_text(expression)
        self.__update_error_text(error_text)

    def __object_inserted(self, index: int, object: Symbolic.ComputationObject) -> None:
        self.object_inserted_event.fire(index, object)
        self.__object_property_changed_event_listeners[object.uuid] = object.property_changed_event.listen(lambda k, v: self.__computation_changed_or_mutated())

    def __object_removed(self, index: int, object: Symbolic.ComputationObject) -> None:
        self.object_removed_event.fire(index, object)
        self.__object_property_changed_event_listeners[object.uuid].close()
        del self.__object_property_changed_event_listeners[object.uuid]

    def __variable_inserted(self, index: int, variable: Symbolic.ComputationVariable) -> None:
        self.variable_inserted_event.fire(index, variable)
        self.__variable_property_changed_event_listeners[variable.uuid] = variable.property_changed_event.listen(lambda k, v: self.__computation_changed_or_mutated())

    def __variable_removed(self, index: int, variable: Symbolic.ComputationVariable) -> None:
        self.variable_removed_event.fire(index, variable)
        self.__variable_property_changed_event_listeners[variable.uuid].close()
        del self.__variable_property_changed_event_listeners[variable.uuid]

    # not thread safe
    def __set_display_specifier(self, display_specifier):
        if self.__display_specifier != display_specifier:
            if self.__computation_changed_or_mutated_event_listener:
                self.__computation_changed_or_mutated_event_listener.close()
                self.__computation_changed_or_mutated_event_listener = None
            if self.__computation_object_inserted_event_listener:
                self.__computation_object_inserted_event_listener.close()
                self.__computation_object_inserted_event_listener = None
            if self.__computation_object_removed_event_listener:
                self.__computation_object_removed_event_listener.close()
                self.__computation_object_removed_event_listener = None
            if self.__computation_variable_inserted_event_listener:
                self.__computation_variable_inserted_event_listener.close()
                self.__computation_variable_inserted_event_listener = None
            if self.__computation_variable_removed_event_listener:
                self.__computation_variable_removed_event_listener.close()
                self.__computation_variable_removed_event_listener = None
            computation = self.__computation
            if computation:
                for index, object in enumerate(computation.objects):
                    self.__object_removed(0, object)
                for index, variable in enumerate(computation.variables):
                    self.__variable_removed(0, variable)
            self.__display_specifier = copy.copy(display_specifier)
            computation = self.__computation
            if computation:
                buffered_data_source = self.__display_specifier.buffered_data_source
                self.__computation_changed_or_mutated_event_listener = buffered_data_source.computation_changed_or_mutated_event.listen(self.__computation_changed_or_mutated)
                self.__computation_object_inserted_event_listener = computation.object_inserted_event.listen(self.__object_inserted)
                self.__computation_object_removed_event_listener = computation.object_removed_event.listen(self.__object_removed)
                self.__computation_variable_inserted_event_listener = computation.variable_inserted_event.listen(self.__variable_inserted)
                self.__computation_variable_removed_event_listener = computation.variable_removed_event.listen(self.__variable_removed)
            self.__computation_changed_or_mutated()
            if computation:
                for index, object in enumerate(computation.objects):
                    self.__object_inserted(index, object)
                for index, variable in enumerate(computation.variables):
                    self.__variable_inserted(index, variable)


class ComputationPanel(Panel.Panel):
    """Provide a panel to edit a computation."""

    def __init__(self, document_controller, panel_id, properties):
        super(ComputationPanel, self).__init__(document_controller, panel_id, _("Computation"))

        ui = self.ui

        self.__selected_data_item_binding = document_controller.create_selected_data_item_binding()
        self.__computation_model = ComputationModel(document_controller, self.__selected_data_item_binding)

        self.__object_column = ui.create_column_widget()
        object_buttons_row = ui.create_row_widget()
        add_object_button = ui.create_push_button_widget(_("Add"))
        object_buttons_row.add(add_object_button)
        object_buttons_row.add_stretch()
        self.__object_column.add(object_buttons_row)

        self.__variable_column = ui.create_column_widget()
        variable_buttons_row = ui.create_row_widget()
        add_variable_button = ui.create_push_button_widget(_("Add"))
        variable_buttons_row.add(add_variable_button)
        variable_buttons_row.add_stretch()
        self.__variable_column.add(variable_buttons_row)

        text_edit_row = ui.create_row_widget()
        text_edit = ui.create_text_edit_widget()
        text_edit.placeholder_text = _("No Computation")
        text_edit_row.add_spacing(8)
        text_edit_row.add(text_edit)
        text_edit_row.add_spacing(8)

        error_row = ui.create_row_widget()
        error_label = ui.create_label_widget("", properties={"stylesheet": "color: red"})
        error_row.add_spacing(8)
        error_row.add(error_label)
        error_row.add_spacing(8)

        # Need to decide how to watch for changes to the computation...
        # Revisit the ReactOS and other possible UI implementations to see how they do it.

        self.__text_edit = text_edit  # for testing
        self.__error_label = error_label  # for testing

        new_button = ui.create_push_button_widget(_("New"))
        update_button = ui.create_push_button_widget(_("Update"))
        button_row = ui.create_row_widget()
        button_row.add_stretch()
        button_row.add(new_button)
        button_row.add_spacing(8)
        button_row.add(update_button)
        button_row.add_spacing(8)

        column = self.ui.create_column_widget()
        column.add_spacing(6)
        column.add(self.__object_column)
        column.add(self.__variable_column)
        column.add_spacing(6)
        column.add(text_edit_row)
        column.add_spacing(6)
        column.add(error_row)
        column.add_spacing(6)
        column.add(button_row)
        column.add_spacing(6)

        def add_object_pressed():
            self.__computation_model.add_object("d", document_controller.document_model.data_items[0])

        add_object_button.on_clicked = add_object_pressed

        def add_variable_pressed():
            self.__computation_model.add_variable("x", 0)

        add_variable_button.on_clicked = add_variable_pressed

        def new_pressed():
            document_controller.processing_computation(text_edit.text)

        def update_pressed():
            if text_edit.text:
                self.__computation_model.computation_text = text_edit.text
            else:
                self.__computation_model.clear()

        def clear():
            text_edit.text = None

        text_edit.on_escape_pressed = clear
        text_edit.on_return_pressed = update_pressed
        new_button.on_clicked = new_pressed
        update_button.on_clicked = update_pressed

        def computation_text_changed(computation_text):
            text_edit.text = computation_text

        self.__computation_text_changed_event_listener = self.__computation_model.computation_text_changed_event.listen(computation_text_changed)

        def error_text_changed(error_text):
            error_label.text = error_text

        self.__error_text_changed_event_listener = self.__computation_model.error_text_changed_event.listen(error_text_changed)

        def object_inserted(index: int, object: Symbolic.ComputationObject) -> None:
            object_row = ui.create_row_widget()
            name_text_edit = ui.create_line_edit_widget()
            name_text_edit.bind_text(Binding.PropertyBinding(object, "name"))
            items = [(None, _("N/A")), ("data_item", _("Data Item")), ("region", _("Region"))]
            type_combo_box = ui.create_combo_box_widget(items=items, item_getter=operator.itemgetter(1))
            item_key = object.specifier["type"] if object else None
            for item in items:
                key, text = item
                if key == item_key:
                    type_combo_box.current_item = item

            def update_object_type(item):
                object_specifier = object.specifier
                object_specifier["type"] = item[0]
                object.specifier = object_specifier

            type_combo_box.on_current_item_changed = update_object_type
            uuid_text_edit = ui.create_line_edit_widget()
            uuid_text_edit.text = object.specifier["uuid"] if object else None

            def update_object_uuid(text):
                if re.fullmatch("[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}",
                                text.strip(), re.IGNORECASE) is not None:
                    object_specifier = object.specifier
                    object_specifier["uuid"] = str(uuid.UUID(text.strip()))
                    object.specifier = object_specifier

            uuid_text_edit.on_editing_finished = update_object_uuid
            remove_button = ui.create_push_button_widget(_("X"))

            def remove_object():
                self.__computation_model.remove_object(object)

            remove_button.on_clicked = remove_object
            object_row.add_spacing(8)
            object_row.add(name_text_edit)
            object_row.add_spacing(4)
            object_row.add(type_combo_box)
            object_row.add_spacing(4)
            object_row.add(uuid_text_edit)
            object_row.add_spacing(8)
            object_row.add(remove_button)
            object_row.add_spacing(8)
            self.__object_column.insert(object_row, index)

        def object_removed(index: int, object: Symbolic.ComputationObject) -> None:
            self.__object_column.remove(self.__object_column.children[index])

        self.__object_inserted_event_listener = self.__computation_model.object_inserted_event.listen(object_inserted)
        self.__object_removed_event_listener = self.__computation_model.object_removed_event.listen(object_removed)

        def variable_inserted(index: int, variable: Symbolic.ComputationVariable) -> None:
            variable_row = ui.create_row_widget()
            name_text_edit = ui.create_line_edit_widget()
            name_text_edit.bind_text(Binding.PropertyBinding(variable, "name"))
            value_text_edit = ui.create_line_edit_widget()
            value_text_edit.bind_text(Binding.PropertyBinding(variable, "value", converter=Converter.IntegerToStringConverter()))
            remove_button = ui.create_push_button_widget(_("X"))
            def remove_variable():
                self.__computation_model.remove_variable(variable)
            remove_button.on_clicked = remove_variable
            variable_row.add_spacing(8)
            variable_row.add(name_text_edit)
            variable_row.add_spacing(4)
            variable_row.add(value_text_edit)
            variable_row.add_spacing(8)
            variable_row.add(remove_button)
            variable_row.add_spacing(8)
            self.__variable_column.insert(variable_row, index)

        def variable_removed(index: int, variable: Symbolic.ComputationVariable) -> None:
            self.__variable_column.remove(self.__variable_column.children[index])

        self.__variable_inserted_event_listener = self.__computation_model.variable_inserted_event.listen(variable_inserted)
        self.__variable_removed_event_listener = self.__computation_model.variable_removed_event.listen(variable_removed)

        self.widget = column

    def close(self):
        self.__computation_text_changed_event_listener.close()
        self.__computation_text_changed_event_listener = None
        self.__error_text_changed_event_listener.close()
        self.__error_text_changed_event_listener = None
        self.__object_inserted_event_listener.close()
        self.__object_inserted_event_listener = None
        self.__object_removed_event_listener.close()
        self.__object_removed_event_listener = None
        self.__variable_inserted_event_listener.close()
        self.__variable_inserted_event_listener = None
        self.__variable_removed_event_listener.close()
        self.__variable_removed_event_listener = None
        self.__computation_model.close()
        self.__computation_model = None
        self.__selected_data_item_binding.close()
        self.__selected_data_item_binding = None
        super(ComputationPanel, self).close()

    @property
    def _object_column_for_testing(self):
        return self.__object_column

    @property
    def _variable_column_for_testing(self):
        return self.__variable_column

    @property
    def _text_edit_for_testing(self):
        return self.__text_edit

    @property
    def _error_label_for_testing(self):
        return self.__error_label

    @property
    def _computation_model_for_testing(self):
        return self.__computation_model