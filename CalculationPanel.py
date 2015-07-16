# futures
from __future__ import absolute_import

# standard libraries
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

        line_edit_row = ui.create_row_widget()
        line_edit = ui.create_line_edit_widget()
        line_edit.placeholder_text = _("Data Expression, e.g. ln(a) + b * 2")
        line_edit_row.add_spacing(8)
        line_edit_row.add(line_edit)
        line_edit_row.add_spacing(8)

        calculate_button = ui.create_push_button_widget(_("Calculate"))
        calculate_row = ui.create_row_widget()
        calculate_row.add_stretch()
        calculate_row.add(calculate_button)
        calculate_row.add_spacing(8)

        column = self.ui.create_column_widget()
        column.add_spacing(6)
        column.add(line_edit_row)
        column.add_spacing(6)
        column.add(calculate_row)
        column.add_spacing(6)

        def calculate():
            data_node = Symbolic.calculate(line_edit.text, self.document_controller.data_item_vars)
            if data_node:
                operation_item = Operation.OperationItem("node-operation")
                operation_item.set_property("data_node", data_node.write())
                data_sources = data_node.data_sources
                operation_data_sources = list()
                for data_source in data_sources:
                    data_source = Operation.DataItemDataSource(data_source)
                    operation_data_sources.append(data_source)
                for operation_data_source in operation_data_sources:
                    operation_item.add_data_source(operation_data_source)
                data_item = DataItem.DataItem()
                data_item.title = _("Calculation on ") + data_item.title
                data_item.set_operation(operation_item)
                self.document_controller.document_model.append_data_item(data_item)
                self.document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
            line_edit.text = None

        def clear():
            line_edit.text = None

        line_edit.on_escape_pressed = clear
        line_edit.on_return_pressed = calculate
        calculate_button.on_clicked = calculate

        self.widget = column

    def close(self):
        super(CalculationPanel, self).close()
