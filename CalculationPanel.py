# futures
from __future__ import absolute_import

# standard libraries
import copy
import gettext
import logging
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.swift import Panel
from nion.ui import Observable


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
        def display_specifier_changed(display_specifier):
            def update_display_specifier():
                self.__set_display_specifier(display_specifier)
            self.document_controller.add_task("update_display_specifier" + str(id(self)), update_display_specifier)
        self.__display_specifier_changed_event_listener = display_specifier_binding.display_specifier_changed_event.listen(display_specifier_changed)
        self.__set_display_specifier(DataItem.DisplaySpecifier())
        self.__computation_changed_event_listener = None
        self.__computation_text = None
        self.computation_text_changed_event = Observable.Event()

    def close(self):
        self.document_controller.clear_task("update_display_specifier" + str(id(self)))
        self.__display_specifier_changed_event_listener.close()
        self.__display_specifier_changed_event_listener = None
        self.__set_display_specifier(DataItem.DisplaySpecifier())

    @property
    def document_controller(self):
        return self.__weak_document_controller()

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

    # not thread safe
    def __set_display_specifier(self, display_specifier):
        if self.__display_specifier != display_specifier:
            if self.__computation_changed_event_listener:
                self.__computation_changed_event_listener.close()
                self.__computation_changed_event_listener = None
            self.__display_specifier = copy.copy(display_specifier)
            # update the expression text
            expression = None
            buffered_data_source = self.__display_specifier.buffered_data_source
            if buffered_data_source:
                computation = buffered_data_source.computation
                if computation:
                    def computation_changed():
                        self.__computation_text = computation.reconstruct(self.document_controller.build_variable_map())
                        self.computation_text_changed_event.fire(self.__computation_text)
                    self.__computation_changed_event_listener = computation.computation_changed_event.listen(computation_changed)
                    expression = computation.reconstruct(self.document_controller.build_variable_map())
            self.__computation_text = expression
            self.computation_text_changed_event.fire(self.__computation_text)


class CalculationPanel(Panel.Panel):
    """Provide a panel to edit a computation."""

    def __init__(self, document_controller, panel_id, properties):
        super(CalculationPanel, self).__init__(document_controller, panel_id, _("Calculation"))

        ui = self.ui

        self.__display_binding = document_controller.create_selected_display_binding()
        self.__computation_model = ComputationModel(document_controller, self.__display_binding)

        text_edit_row = ui.create_row_widget()
        text_edit = ui.create_text_edit_widget()
        text_edit.placeholder_text = _("No Computation")
        text_edit_row.add_spacing(8)
        text_edit_row.add(text_edit)
        text_edit_row.add_spacing(8)

        # Need to decide how to watch for changes to the computation...
        # Revisit the ReactOS and other possible UI implementations to see how they do it.

        self.__text_edit = text_edit  # for testing

        new_button = ui.create_push_button_widget(_("New"))
        update_button = ui.create_push_button_widget(_("Update"))
        calculate_row = ui.create_row_widget()
        calculate_row.add_stretch()
        calculate_row.add(new_button)
        calculate_row.add_spacing(8)
        calculate_row.add(update_button)
        calculate_row.add_spacing(8)

        column = self.ui.create_column_widget()
        column.add_spacing(6)
        column.add(text_edit_row)
        column.add_spacing(6)
        column.add(calculate_row)
        column.add_spacing(6)

        def new_pressed():
            document_controller.processing_calculation(text_edit.text)

        def update_pressed():
            self.__computation_model.computation_text = text_edit.text

        def clear():
            text_edit.text = None

        text_edit.on_escape_pressed = clear
        text_edit.on_return_pressed = update_pressed
        new_button.on_clicked = new_pressed
        update_button.on_clicked = update_pressed

        def computation_text_changed(computation_text):
            text_edit.text = computation_text

        self.__computation_text_changed_event_listener = self.__computation_model.computation_text_changed_event.listen(computation_text_changed)

        self.widget = column

    def close(self):
        self.__computation_text_changed_event_listener.close()
        self.__computation_text_changed_event_listener = None
        self.__computation_model.close()
        self.__computation_model = None
        self.__display_binding.close()
        self.__display_binding = None
        super(CalculationPanel, self).close()

    @property
    def _text_edit_for_testing(self):
        return self.__text_edit
