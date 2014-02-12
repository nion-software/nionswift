# standard libraries
import copy
import gettext
import logging
import threading
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import DataItemInspector
from nion.swift import Operation
from nion.swift import Panel
from nion.ui import UserInterfaceUtility

_ = gettext.gettext


class InspectorPanelBase(Panel.Panel):
    def __init__(self, document_controller, panel_id, title, properties):
        super(InspectorPanelBase, self).__init__(document_controller, panel_id, title)

        self.__data_item = None
        self.__data_item_inspector = None

        # these fields facilitate a changing data item from a thread.
        self.__update_data_item_changed = False
        self.__update_data_item_data_item = None
        self.__update_data_item_mutex = threading.RLock()

        # bind to the selected data item.
        # connect self as listener. this will result in calls to data_item_binding_data_item_changed
        # and data_item_binding_data_item_content_changed
        self.data_item_binding = document_controller.create_selected_data_item_binding()
        self.data_item = None
        self.data_item_binding.add_listener(self)

        # top level widget in this inspector is a scroll area.
        # content of the scroll area is the column, to which inspectors
        # can be added.
        scroll_area = self.ui.create_scroll_area_widget(properties)
        scroll_area.set_scrollbar_policies("off", "needed")
        self.column = self.ui.create_column_widget()
        scroll_area.content = self.column
        self.widget = scroll_area

    def close(self):
        # first set the data item to None
        self.data_item_binding_data_item_changed(None)
        # disconnect self as listener
        self.data_item_binding.remove_listener(self)
        # close the data item inspector
        if self.__data_item_inspector:
            self.__data_item_inspector.close()
        # close the property controller
        self.data_item_binding.close()
        self.data_item = None
        # finish closing
        super(InspectorPanelBase, self).close()

    def periodic(self):
        super(InspectorPanelBase, self).periodic()
        if self.__data_item_inspector:
            self.__data_item_inspector.periodic()
        # watch for changes to the data item. changes will be requested by
        # flagging update_data_item_changed. if this happens, set the data_item
        # to the new value.
        with self.__update_data_item_mutex:
            update_data_item_changed = self.__update_data_item_changed
            data_item = self.__update_data_item_data_item
            self.__update_data_item_changed = False
            self.__update_data_item_data_item = None
        if update_data_item_changed:
            if self.data_item != data_item:
                self.data_item = data_item

    # subclasses should implement this to create the data item inspector
    def _create_data_item_inspector(self, data_item):
        raise NotImplementedError()

    # close the old data item inspector, and create a new one
    # not thread safe.
    def __update_data_item_inspector(self):
        if self.__data_item_inspector:
            self.column.remove(self.__data_item_inspector.widget)
            self.__data_item_inspector.close()
            self.__data_item_inspector = None
        if self.__data_item:
            self.__data_item_inspector = self._create_data_item_inspector(self.__data_item)
            self.column.add(self.__data_item_inspector.widget)

    def __get_data_item(self):
        return self.__data_item
    # not thread safe.
    def __set_data_item(self, data_item):
        if self.__data_item != data_item:
            self.__data_item = data_item
            self.__update_data_item_inspector()
    data_item = property(__get_data_item, __set_data_item)

    # this message is received from the data item binding.
    # it is established using add_listener. when it is called
    # mark the data item as needing updating. the actual update
    # will happen in periodic.
    # thread safe.
    def data_item_binding_data_item_changed(self, data_item):
        with self.__update_data_item_mutex:
            self.__update_data_item_changed = True
            self.__update_data_item_data_item = data_item


class InspectorPanel(InspectorPanelBase):
    def __init__(self, document_controller, panel_id, properties):
        super(InspectorPanel, self).__init__(document_controller, panel_id, _("Inspector"), properties)

    def _create_data_item_inspector(self, data_item):
        return DataItemInspector.DataItemInspector(self.ui, data_item)


class OperationsInspector(DataItemInspector.InspectorSection):

    """
        Subclass InspectorSection to implement operations inspector.
    """

    def __init__(self, ui, data_item_binding_source):
        super(OperationsInspector, self).__init__(ui, _("Operations"))
        self.__operations = data_item_binding_source.operations
        # ui. create the spatial operations list.
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), None, header_for_empty_list_widget)
        list_widget.bind_items(UserInterfaceUtility.ListBinding(data_item_binding_source, "operations"))
        self.add_widget_to_content(list_widget)

    # not thread safe
    def __create_header_for_empty_list_widget(self):
        header_for_empty_list_row = self.ui.create_row_widget()
        header_for_empty_list_row.add(self.ui.create_label_widget("None", properties={"stylesheet": "font: italic"}))
        return header_for_empty_list_row

    # not thread safe.
    def __create_list_item_widget(self, operation):

        operation_widget = self.ui.create_column_widget()

        operation_title_row = self.ui.create_row_widget()
        operation_title_row.add(self.ui.create_label_widget(operation.name))
        operation_title_row.add_stretch()
        operation_widget.add(operation_title_row)

        for item in operation.description:
            name = item["name"]
            type = item["type"]
            property = item["property"]
            if type == "scalar":
                row_widget = self.ui.create_row_widget()
                label_widget = self.ui.create_label_widget(name)
                slider_widget = self.ui.create_slider_widget()
                slider_widget.maximum = 100
                slider_widget.bind_value(Operation.OperationPropertyBinding(operation, property, converter=UserInterfaceUtility.FloatTo100Converter()))
                line_edit_widget = self.ui.create_line_edit_widget()
                line_edit_widget.bind_text(Operation.OperationPropertyBinding(operation, property, converter=UserInterfaceUtility.FloatToPercentStringConverter()))
                row_widget.add(label_widget)
                row_widget.add_spacing(8)
                row_widget.add(slider_widget)
                row_widget.add_spacing(8)
                row_widget.add(line_edit_widget)
                row_widget.add_stretch()
                operation_widget.add_spacing(4)
                operation_widget.add(row_widget)
            elif type == "integer-field":
                row_widget = self.ui.create_row_widget()
                label_widget = self.ui.create_label_widget(name)
                line_edit_widget = self.ui.create_line_edit_widget()
                line_edit_widget.bind_text(Operation.OperationPropertyBinding(operation, property, converter=UserInterfaceUtility.IntegerToStringConverter()))
                row_widget.add(label_widget)
                row_widget.add_spacing(8)
                row_widget.add(line_edit_widget)
                row_widget.add_stretch()
                operation_widget.add_spacing(4)
                operation_widget.add(row_widget)

        column = self.ui.create_column_widget()
        column.add_spacing(4)
        column.add(operation_widget)
        column.add_stretch()
        return column


class ProcessingInspector(object):

    def __init__(self, ui, data_item):
        self.ui = ui

        # bindings

        self.__data_item_binding_source = DataItem.DataItemBindingSource(data_item)
        def update_data_item(data_item):
            self.__data_item_binding_source.data_item = data_item
        self.__data_item_binding = UserInterfaceUtility.PropertyBinding(self.__data_item_binding_source, "data_item")
        self.__data_item_binding.target_setter = update_data_item

        # ui

        self.__inspectors = list()
        content_widget = self.ui.create_column_widget()
        content_widget.add_spacing(6)

        # a section for each operation

        self.__inspectors.append(OperationsInspector(self.ui, self.__data_item_binding_source))

        for inspector in self.__inspectors:
            content_widget.add(inspector.widget)

        content_widget.add_stretch()

        self.widget = content_widget

    def close(self):
        # close inspectors
        for inspector in self.__inspectors:
            inspector.close()
        # close the data item content binding
        self.__data_item_binding.close()
        self.__data_item_binding_source.close()

    # update the values if needed
    def periodic(self):
        for inspector in self.__inspectors:
            inspector.periodic()
        self.__data_item_binding.periodic()


class ProcessingPanel(InspectorPanelBase):
    def __init__(self, document_controller, panel_id, properties):
        super(ProcessingPanel, self).__init__(document_controller, panel_id, _("Processing"), properties)

    def _create_data_item_inspector(self, data_item):
        return ProcessingInspector(self.ui, data_item)
