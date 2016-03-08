# futures
from __future__ import absolute_import

# standard libraries
import copy
import gettext
import operator
import random
import re
import string
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.swift import Panel
from nion.ui import Binding
from nion.ui import CanvasItem
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
        self.__computation_variable_inserted_event_listener = None
        self.__computation_variable_removed_event_listener = None
        self.__computation_label = None
        self.__computation_text = None
        self.__error_text = None
        self.__object_property_changed_event_listeners = dict()
        self.__variable_property_changed_event_listeners = dict()
        self.computation_label_changed_event = Event.Event()
        self.computation_text_changed_event = Event.Event()
        self.error_text_changed_event = Event.Event()
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

    def add_variable(self, name: str=None, value_type: str=None, value=None, value_default=None, value_min=None, value_max=None, control_type: str=None, specifier: dict=None) -> Symbolic.ComputationVariable:
        computation = self.__computation
        if computation:
            return computation.create_variable(name, value_type, value, value_default, value_min, value_max, control_type, specifier)
        return None

    def remove_variable(self, variable: Symbolic.ComputationVariable) -> None:
        computation = self.__computation
        if computation:
            computation.remove_variable(variable)

    @property
    def computation_label(self):
        return self.__computation_label

    @computation_label.setter
    def computation_label(self, label):
        buffered_data_source = self.__display_specifier.buffered_data_source
        if buffered_data_source:
            computation = buffered_data_source.computation
            if not computation:
                computation = Symbolic.Computation()
            computation.label = label
            buffered_data_source.computation = computation

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

    def __update_computation_label(self, computation_label):
        if self.__computation_label != computation_label:
            self.__computation_label = computation_label
            self.computation_label_changed_event.fire(self.__computation_label)

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
        label = None
        expression = None
        error_text = None
        computation = self.__computation
        if computation:
            error_text = computation.error_text
            expression = computation.original_expression
            label = computation.label
        self.__update_computation_label(label)
        self.__update_computation_text(expression)
        self.__update_error_text(error_text)

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
            if self.__computation_variable_inserted_event_listener:
                self.__computation_variable_inserted_event_listener.close()
                self.__computation_variable_inserted_event_listener = None
            if self.__computation_variable_removed_event_listener:
                self.__computation_variable_removed_event_listener.close()
                self.__computation_variable_removed_event_listener = None
            computation = self.__computation
            if computation:
                for index, variable in enumerate(computation.variables):
                    self.__variable_removed(0, variable)
            self.__display_specifier = copy.copy(display_specifier)
            computation = self.__computation
            if computation:
                buffered_data_source = self.__display_specifier.buffered_data_source
                self.__computation_changed_or_mutated_event_listener = buffered_data_source.computation_changed_or_mutated_event.listen(self.__computation_changed_or_mutated)
                self.__computation_variable_inserted_event_listener = computation.variable_inserted_event.listen(self.__variable_inserted)
                self.__computation_variable_removed_event_listener = computation.variable_removed_event.listen(self.__variable_removed)
            self.__computation_changed_or_mutated()
            if computation:
                for index, variable in enumerate(computation.variables):
                    self.__variable_inserted(index, variable)


class ComputationPanelSection:

    def __init__(self, ui, variable, on_remove):

        section_widget = ui.create_column_widget()
        section_title_row = ui.create_row_widget()

        twist_down_canvas_item = CanvasItem.TwistDownCanvasItem()
        twist_down_canvas_widget = ui.create_canvas_widget(properties={"height": 20, "width": 20})
        twist_down_canvas_widget.canvas_item.add_canvas_item(twist_down_canvas_item)
        section_title_row.add(twist_down_canvas_widget)
        twist_down_label_widget = ui.create_label_widget(variable.name, properties={"stylesheet": "font-weight: bold"})
        twist_down_label_widget.bind_text(Binding.PropertyBinding(variable, "name"))
        section_title_row.add(twist_down_label_widget)
        section_title_row.add_stretch()
        section_widget.add(section_title_row)

        # boolean, integral, real, data item, region

        def make_label_row(ui, label):
            label_row = ui.create_row_widget()
            label_row.add_spacing(8)
            label_row.add(ui.create_label_widget(label))
            label_row.add_stretch()
            return label_row

        def make_name_type_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            name_text_edit = ui.create_line_edit_widget()
            name_text_edit.bind_text(Binding.PropertyBinding(variable, "name"))

            type_items = [("boolean", _("Boolean")), ("integral", _("Integer")), ("real", _("Real")), ("data_item", _("Data Item")), ("region", _("Region"))]
            type_combo_box = ui.create_combo_box_widget(items=type_items, item_getter=operator.itemgetter(1))

            remove_button = ui.create_push_button_widget(_("X"))

            name_type_row = ui.create_row_widget()
            name_type_row.add_spacing(8)
            name_type_row.add(name_text_edit)
            name_type_row.add_spacing(8)
            name_type_row.add(type_combo_box)
            name_type_row.add_spacing(8)
            name_type_row.add(remove_button)
            name_type_row.add_stretch()

            variable_type = variable.variable_type
            type_combo_box.current_item = next((i for i in type_items if i[0] == variable_type), None)
            type_combo_box.on_current_item_changed = lambda item: on_change_type_fn(item[0])
            remove_button.on_clicked = on_remove_fn

            return name_type_row

        def make_boolean_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            value_check_box = ui.create_check_box_widget(_("Value"))

            value_row = ui.create_row_widget()
            value_row.add_spacing(8)
            value_row.add(value_check_box)
            value_row.add_stretch()

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(Binding.PropertyBinding(variable, "label"))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(ui.create_label_widget(_("Label")))
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            display_row.add_stretch()

            column = ui.create_column_widget()
            column.add(make_label_row(ui, _("Variable Name / Type")))
            column.add(name_type_row)
            column.add(value_row)
            column.add(display_row)

            value_check_box.bind_checked(Binding.PropertyBinding(variable, "value"))

            return column

        def make_number_row(ui, variable: Symbolic.ComputationVariable, converter, on_change_type_fn, on_remove_fn):
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            value_text_edit = ui.create_line_edit_widget()

            value_default_text_edit = ui.create_line_edit_widget()

            value_min_text_edit = ui.create_line_edit_widget()

            value_max_text_edit = ui.create_line_edit_widget()

            value_row = ui.create_row_widget()
            value_row.add_spacing(8)
            value_row.add(value_text_edit)
            value_row.add_spacing(4)
            value_row.add(value_default_text_edit)
            value_row.add_spacing(4)
            value_row.add(value_min_text_edit)
            value_row.add_spacing(4)
            value_row.add(value_max_text_edit)
            value_row.add_stretch()

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(Binding.PropertyBinding(variable, "label"))

            display_items = [("field", _("Field")), ("slider", _("Slider"))]
            display_combo_box = ui.create_combo_box_widget(items=display_items, item_getter=operator.itemgetter(1))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            display_row.add_spacing(4)
            display_row.add(display_combo_box)
            display_row.add_stretch()

            column = ui.create_column_widget()
            column.add(make_label_row(ui, _("Variable Name / Type")))
            column.add(name_type_row)
            column.add(make_label_row(ui, _("Value / Default / Min / Max")))
            column.add(value_row)
            column.add(make_label_row(ui, _("Label / Display Type")))
            column.add(display_row)

            value_text_edit.bind_text(Binding.PropertyBinding(variable, "value", converter=converter))
            value_default_text_edit.bind_text(Binding.PropertyBinding(variable, "value_default", converter=converter))
            value_min_text_edit.bind_text(Binding.PropertyBinding(variable, "value_min", converter=converter))
            value_max_text_edit.bind_text(Binding.PropertyBinding(variable, "value_max", converter=converter))
            display_combo_box.current_item = display_items[1]

            return column

        def make_specifier_row(ui, variable: Symbolic.ComputationVariable, specifier_type, on_change_type_fn, on_remove_fn):
            column = ui.create_column_widget()

            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)

            uuid_text_edit = ui.create_line_edit_widget()

            uuid_row = ui.create_row_widget()
            uuid_row.add_spacing(8)
            uuid_row.add(ui.create_label_widget(_("UUID")))
            uuid_row.add_spacing(8)
            uuid_row.add(uuid_text_edit)
            uuid_row.add_spacing(8)

            label_text_edit = ui.create_line_edit_widget()
            label_text_edit.bind_text(Binding.PropertyBinding(variable, "label"))

            display_row = ui.create_row_widget()
            display_row.add_spacing(8)
            display_row.add(ui.create_label_widget(_("Label")))
            display_row.add_spacing(8)
            display_row.add(label_text_edit)
            display_row.add_stretch()

            column.add(name_type_row)
            column.add(uuid_row)
            column.add(display_row)

            class UuidToStringConverter(object):
                def convert(self, value):
                    return str(value) if value else None
                def convert_back(self, value):
                    if re.fullmatch("[0-9A-F]{8}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9A-F]{12}",
                                    value.strip(), re.IGNORECASE) is not None:
                        return uuid.UUID(value.strip())
                    return None

            class SpecifierToStringConverter(object):
                def __init__(self, specifier_type):
                    self.__specifier_type = specifier_type
                def convert(self, value):
                    return UuidToStringConverter().convert(value.get("uuid")) if value else None
                def convert_back(self, value):
                    uuid_ = UuidToStringConverter().convert_back(value)
                    return {"type": self.__specifier_type, "version": 1, "uuid": str(uuid_)}

            uuid_text_edit.bind_text(Binding.PropertyBinding(variable, "specifier", converter=SpecifierToStringConverter(specifier_type)))

            return column

        def make_data_item_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            return make_specifier_row(ui, variable, "data_item", on_change_type_fn, on_remove_fn)

        def make_region_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            return make_specifier_row(ui, variable, "region", on_change_type_fn, on_remove_fn)

        def make_empty_row(ui, variable: Symbolic.ComputationVariable, on_change_type_fn, on_remove_fn):
            column = ui.create_column_widget()
            name_type_row = make_name_type_row(ui, variable, on_change_type_fn, on_remove_fn)
            column.add(name_type_row)
            return column

        stack = ui.create_column_widget()

        section_widget.add(stack)
        section_widget.add_spacing(4)

        def toggle():
            twist_down_canvas_item.checked = not twist_down_canvas_item.checked
            stack.visible = twist_down_canvas_item.checked
        section_open = False
        twist_down_canvas_item.checked = section_open
        stack.visible = section_open
        twist_down_canvas_item.on_button_clicked = toggle

        def change_type(variable_type):
            variable.variable_type = variable_type

        def select_stack(stack, variable, specifier):
            stack.remove_all()
            variable_type = variable.variable_type
            if variable_type == "boolean":
                stack.add(make_boolean_row(ui, variable, change_type, on_remove))
            elif variable_type == "integral":
                stack.add(make_number_row(ui, variable, Converter.IntegerToStringConverter(), change_type, on_remove))
            elif variable_type == "real":
                stack.add(make_number_row(ui, variable, Converter.FloatToStringConverter(), change_type, on_remove))
            elif variable_type == "data_item":
                stack.add(make_data_item_row(ui, variable, change_type, on_remove))
            elif variable_type == "region":
                stack.add(make_region_row(ui, variable, change_type, on_remove))
            else:
                stack.add(make_empty_row(ui, variable, change_type, on_remove))

        def do_select_stack():
            select_stack(stack, variable, variable.specifier)

        self.__variable_type_changed_event_listener = variable.variable_type_changed_event.listen(do_select_stack)

        select_stack(stack, variable, variable.specifier)

        self.widget = section_widget

    def close(self):
        self.__variable_type_changed_event_listener.close()
        self.__variable_type_changed_event_listener = None


class ComputationPanel(Panel.Panel):
    """Provide a panel to edit a computation."""

    def __init__(self, document_controller, panel_id, properties):
        super(ComputationPanel, self).__init__(document_controller, panel_id, _("Computation"))

        ui = self.ui

        self.__selected_data_item_binding = document_controller.create_selected_data_item_binding()
        self.__computation_model = ComputationModel(document_controller, self.__selected_data_item_binding)

        self.__sections = list()

        label_edit_widget = ui.create_line_edit_widget()
        label_edit_widget.placeholder_text = _("Computation Label")

        label_row = ui.create_row_widget()
        label_row.add_spacing(8)
        label_row.add(ui.create_label_widget(_("Description")))
        label_row.add_spacing(8)
        label_row.add(label_edit_widget)
        label_row.add_spacing(8)

        buttons_row = ui.create_row_widget()
        add_variable_button = ui.create_push_button_widget(_("Add Variable"))
        add_object_button = ui.create_push_button_widget(_("Add Object"))
        buttons_row.add(add_variable_button)
        buttons_row.add_spacing(8)
        buttons_row.add(add_object_button)
        buttons_row.add_stretch()

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

        self.__variable_column = ui.create_column_widget()

        column = self.ui.create_column_widget()
        column.add_spacing(6)
        column.add(label_row)
        column.add(self.__variable_column)
        column.add(buttons_row)
        column.add_spacing(6)
        column.add(text_edit_row)
        column.add_spacing(6)
        column.add(error_row)
        column.add_spacing(6)
        column.add(button_row)
        column.add_spacing(6)

        def add_object_pressed():
            document_model = document_controller.document_model
            object_specifier = document_model.get_object_specifier(document_model.data_items[0])
            self.__computation_model.add_variable("".join([random.choice(string.ascii_lowercase) for _ in range(4)]), specifier=object_specifier)

        add_object_button.on_clicked = add_object_pressed

        def add_variable_pressed():
            self.__computation_model.add_variable("".join([random.choice(string.ascii_lowercase) for _ in range(4)]), value_type="integral", value=0)

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
        label_edit_widget.on_editing_finished = lambda text: setattr(self.__computation_model, "computation_label", text)

        def computation_label_changed(text):
            label_edit_widget.text = text
            if label_edit_widget.focused:
                label_edit_widget.select_all()

        self.__computation_label_changed_event_listener = self.__computation_model.computation_label_changed_event.listen(computation_label_changed)

        def computation_text_changed(computation_text):
            text_edit.text = computation_text

        self.__computation_text_changed_event_listener = self.__computation_model.computation_text_changed_event.listen(computation_text_changed)

        def error_text_changed(error_text):
            error_label.text = error_text

        self.__error_text_changed_event_listener = self.__computation_model.error_text_changed_event.listen(error_text_changed)

        def variable_inserted(index: int, variable: Symbolic.ComputationVariable) -> None:
            def remove_variable():
                self.__computation_model.remove_variable(variable)
            section = ComputationPanelSection(ui, variable, remove_variable)
            self.__variable_column.insert(section.widget, index)
            self.__sections.insert(index, section)

        def variable_removed(index: int, variable: Symbolic.ComputationVariable) -> None:
            self.__variable_column.remove(self.__variable_column.children[index])
            if self.__sections[index]:
                self.__sections[index].close()
            del self.__sections[index]

        self.__variable_inserted_event_listener = self.__computation_model.variable_inserted_event.listen(variable_inserted)
        self.__variable_removed_event_listener = self.__computation_model.variable_removed_event.listen(variable_removed)

        self.widget = column

    def close(self):
        self.__computation_label_changed_event_listener.close()
        self.__computation_label_changed_event_listener = None
        self.__computation_text_changed_event_listener.close()
        self.__computation_text_changed_event_listener = None
        self.__error_text_changed_event_listener.close()
        self.__error_text_changed_event_listener = None
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
    def _sections_for_testing(self):
        return self.__sections

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