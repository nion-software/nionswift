# futures
from __future__ import absolute_import

# standard libraries
import copy
import gettext
import logging

# third party libraries
# None

# local libraries
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.swift.model import Operation
from nion.swift import Panel


_ = gettext.gettext


class CalculationPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(CalculationPanel, self).__init__(document_controller, panel_id, _("Calculation"))

        ui = self.ui

        # the currently selected display
        self.__display_specifier = DataItem.DisplaySpecifier()

        text_edit_row = ui.create_row_widget()
        text_edit = ui.create_text_edit_widget()
        text_edit.placeholder_text = _("No Computation")
        text_edit_row.add_spacing(8)
        text_edit_row.add(text_edit)
        text_edit_row.add_spacing(8)

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
            buffered_data_source = self.__display_specifier.buffered_data_source
            if buffered_data_source:
                computation = buffered_data_source.computation
                if not computation:
                    computation = Symbolic.Computation()
                computation.parse_expression(document_controller.document_model, text_edit.text, document_controller.build_variable_map())
                buffered_data_source.computation = computation

        def clear():
            text_edit.text = None

        text_edit.on_escape_pressed = clear
        text_edit.on_return_pressed = update_pressed
        new_button.on_clicked = new_pressed
        update_button.on_clicked = update_pressed

        # this message is received from the data item binding.
        # it is established using add_listener. when it is called
        # mark the data item as needing updating.
        # thread safe.
        def selected_display_binding_changed(display_specifier):
            def update_display():
                self.__set_display_specifier(text_edit, display_specifier)
            self.document_controller.add_task("update_display" + str(id(self)), update_display)

        # listen for selected display binding changes
        self.__display_binding = document_controller.create_selected_display_binding()
        self.__selected_display_binding_changed_event_listener = self.__display_binding.selected_display_binding_changed_event.listen(selected_display_binding_changed)
        self.__set_display_specifier(text_edit, DataItem.DisplaySpecifier())

        self.widget = column

    def close(self):
        # disconnect self as listener
        self.__selected_display_binding_changed_event_listener.close()
        self.__selected_display_binding_changed_event_listener = None
        # close the property controller. note: this will close and create
        # a new data item inspector; so it should go before the final
        # data item inspector close, which is below.
        self.__display_binding.close()
        self.__display_binding = None
        self.__set_display_specifier(None, DataItem.DisplaySpecifier())
        super(CalculationPanel, self).close()

    # not thread safe
    def __set_display_specifier(self, text_edit, display_specifier):
        if self.__display_specifier != display_specifier:
            self.__display_specifier = copy.copy(display_specifier)
            # update the expression text
            expression = None
            buffered_data_source = self.__display_specifier.buffered_data_source
            if buffered_data_source:
                computation = buffered_data_source.computation
                if computation:
                    expression = computation.reconstruct(self.document_controller.build_variable_map())
            if text_edit:
                text_edit.text = expression
