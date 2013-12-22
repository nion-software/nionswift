# standard libraries
import gettext
import logging

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Decorators
from nion.swift import Storage
from nion.swift import UserInterfaceUtility

_ = gettext.gettext



class DisplayLimitsInspector(object):

    """
        Display limits binding is composed of a few fields:
            display limits (read write): user specified display limits
            data range (read only): the range of data, when converted to real numbers
            display range (read only): display limits if present, otherwise data range
    """

    def __init__(self, ui, display_limits_binding):
        self.ui = ui
        self.display_limits_binding = display_limits_binding
        self.display_limits_binding.add_listener(self)
        self.__task_set = Decorators.TaskSet()
        self.__block = False
        # display limit editor
        self.display_limits_section = self.ui.create_column_widget()
        self.display_limits_section_title = self.ui.create_row_widget()
        #self.display_limits_section_title.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        self.display_limits_section_title.add(self.ui.create_label_widget(_("Display Limits"), properties={"stylesheet": "font-weight: bold"}))
        self.display_limits_section_title.add_stretch()
        self.display_limits_section.add(self.display_limits_section_title)
        self.display_limits_section_table = self.ui.create_row_widget()
        self.display_limits_section_rows = self.ui.create_column_widget()
        self.display_limits_section_table.add_spacing(20)
        self.display_limits_section_table.add(self.display_limits_section_rows)
        self.display_limits_range_row = self.ui.create_row_widget()
        self.display_limits_range_low = self.ui.create_label_widget(properties={"width": 60})
        self.display_limits_range_high = self.ui.create_label_widget(properties={"width": 60})
        self.display_limits_range_row.add(self.ui.create_label_widget(_("Data Range:"), properties={"width": 120}))
        self.display_limits_range_row.add(self.display_limits_range_low)
        self.display_limits_range_row.add_spacing(8)
        self.display_limits_range_row.add(self.display_limits_range_high)
        self.display_limits_range_row.add_stretch()
        self.display_limits_limit_row = self.ui.create_row_widget()
        self.display_limits_limit_low = self.ui.create_line_edit_widget(properties={"width": 60})
        self.display_limits_limit_high = self.ui.create_line_edit_widget(properties={"width": 60})
        self.display_limits_limit_low.on_editing_finished = lambda text: self.display_limit_low_editing_finished(text)
        self.display_limits_limit_high.on_editing_finished = lambda text: self.display_limit_high_editing_finished(text)
        self.display_limits_limit_row.add(self.ui.create_label_widget(_("Display:"), properties={"width": 120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()
        self.display_limits_section_rows.add_spacing(4)
        self.display_limits_section_rows.add(self.display_limits_range_row)
        self.display_limits_section_rows.add_spacing(4)
        self.display_limits_section_rows.add(self.display_limits_limit_row)
        self.display_limits_section.add(self.display_limits_section_table)
        self.widget = self.display_limits_section

    def close(self):
        self.display_limits_binding.remove_listener(self)

    def periodic(self):
        self.__task_set.perform_tasks()

    # this gets called from the display_limits_binding
    def display_limits_changed(self):
        if not self.__block:
            self.__task_set.add_task("update", lambda: self.update())

    def update(self):
        # display limits
        data_range = self.display_limits_binding.data_range
        if data_range:
            self.display_limits_range_low.text = "{0:.2f}".format(data_range[0])
            self.display_limits_range_high.text = "{0:.2f}".format(data_range[1])
        else:
            self.display_limits_range_low.text = _("N/A")
            self.display_limits_range_high.text = _("N/A")
        display_range = self.display_limits_binding.display_range
        if display_range:
            self.display_limits_limit_low.text = "{0:.2f}".format(display_range[0])
            self.display_limits_limit_high.text = "{0:.2f}".format(display_range[1])
        else:
            self.display_limits_limit_low.text = _("N/A")
            self.display_limits_limit_high.text = _("N/A")
        if self.display_limits_limit_low.focused:
            self.display_limits_limit_low.select_all()
        if self.display_limits_limit_high.focused:
            self.display_limits_limit_high.select_all()

    # handle display limit editing
    def display_limit_low_editing_finished(self, text):
        if self.display_limits_range_low.text != text:
            display_limit_low = float(text)
            block = self.__block
            self.__block = True
            self.display_limits_binding.display_limits = (display_limit_low, self.display_limits_binding.display_range[1])
            self.__block = block
            self.update()  # clean up displayed values

    def display_limit_high_editing_finished(self, text):
        if self.display_limits_range_high.text != text:
            display_limit_high = float(text)
            block = self.__block
            self.__block = True
            self.display_limits_binding.display_limits = (self.display_limits_binding.display_range[0], display_limit_high)
            self.__block = block
            self.update()  # clean up displayed values


class DisplayLimitsBinding(Storage.Broadcaster):

    def __init__(self, data_item):
        super(DisplayLimitsBinding, self).__init__()
        self.__data_item = data_item
        # make sure we're listening to changes of the data item
        self.__data_item.add_listener(self)

    def close(self):
        # unlisten to data item
        self.__data_item.remove_listener(self)

    # this will typically happen on a thread
    def data_item_content_changed(self, data_item, changes):
        if any (k in changes for k in (DataItem.DISPLAY, )):
            self.notify_listeners("display_limits_changed")

    def __get_data_range(self):
        return self.__data_item.data_range
    data_range = property(__get_data_range)

    def __get_display_range(self):
        return self.__data_item.display_range
    display_range = property(__get_display_range)

    def __get_display_limits(self):
        return self.__data_item.display_limits
    def __set_display_limits(self, display_limits):
        self.__data_item.display_limits = display_limits
    display_limits = property(__get_display_limits, __set_display_limits)


class DataItemEditor(object):

    def __init_info_editor(self):
        # info editor
        self.info_section = self.ui.create_column_widget()
        self.info_section_title = self.ui.create_row_widget()
        #self.info_section_title.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        self.info_section_title.add(self.ui.create_label_widget(_("Info"), properties={"stylesheet": "font-weight: bold"}))
        self.info_section_title.add_stretch()
        self.info_section.add(self.info_section_title)
        # title
        self.info_section_title_row = self.ui.create_row_widget()
        self.info_section_title_row.add_spacing(20)
        self.info_section_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width": 60}))
        self.info_title_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_title_row.add(self.info_title_label)
        self.info_section_title_row.add_stretch()
        self.info_section.add(self.info_section_title_row)
        # session
        self.info_section.add_spacing(2)
        self.info_section_session_row = self.ui.create_row_widget()
        self.info_section_session_row.add_spacing(20)
        self.info_section_session_row.add(self.ui.create_label_widget(_("Session"), properties={"width": 60}))
        self.info_session_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_session_row.add(self.info_session_label)
        self.info_section_session_row.add_stretch()
        self.info_section.add(self.info_section_session_row)
        # date
        self.info_section.add_spacing(2)
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add_spacing(20)
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width": 60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()
        self.info_section.add(self.info_section_datetime_row)
        # format (size, datatype)
        self.info_section.add_spacing(2)
        self.info_section_format_row = self.ui.create_row_widget()
        self.info_section_format_row.add_spacing(20)
        self.info_section_format_row.add(self.ui.create_label_widget(_("Data"), properties={"width": 60}))
        self.info_format_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_format_row.add(self.info_format_label)
        self.info_section_format_row.add_stretch()
        self.info_section.add(self.info_section_format_row)
        # extra space
        self.info_section.add_spacing(8)
        # add to enclosing widget
        self.widget.add(self.info_section)

    def __init_param_editor(self):
        # param editor
        self.param_row = self.ui.create_row_widget()
        param_label = self.ui.create_label_widget(_("Parameter"))
        self.param_slider = self.ui.create_slider_widget()
        self.param_slider.maximum = 100
        self.param_slider.on_value_changed = lambda value: self.param_slider_value_changed(value)
        self.param_field = self.ui.create_line_edit_widget()
        self.param_field.on_editing_finished = lambda text: self.param_editing_finished(text)
        self.param_field_formatter = UserInterfaceUtility.FloatFormatter(self.param_field)
        self.param_row.add(param_label)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_slider)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_field)
        self.param_row.add_stretch()
        self.param_row.visible = False
        self.widget.add(self.param_row)

    def __init_calibration_editor(self):
        # calibrations editor
        self.calibrations_section = self.ui.create_column_widget()
        self.calibrations_section_title = self.ui.create_row_widget()
        #self.calibrations_section_title.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        self.calibrations_section_title.add(self.ui.create_label_widget(_("Calibrations"), properties={"stylesheet": "font-weight: bold"}))
        self.calibrations_section_title.add_stretch()
        self.calibrations_section.add(self.calibrations_section_title)
        self.calibrations_table = self.ui.create_column_widget()
        self.calibrations_labels = self.ui.create_column_widget()
        self.calibrations_column = self.ui.create_column_widget(properties={"spacing": 2})
        self.calibrations_table.add(self.calibrations_labels)
        self.calibrations_column_row = self.ui.create_row_widget()
        self.calibrations_column_row.add_spacing(20)
        self.calibrations_column_row.add(self.calibrations_column)
        self.calibrations_table.add(self.calibrations_column_row)
        self.calibrations_section.add(self.calibrations_table)
        self.widget.add(self.calibrations_section)

    def __init__(self, ui, data_item):
        self.ui = ui
        self.data_item = data_item
        self.widget = self.ui.create_column_widget()

        self.widget.add_spacing(6)

        self.__init_info_editor()

        self.__init_param_editor()

        self.__init_calibration_editor()

        self.__display_limits_binding = DisplayLimitsBinding(self.data_item)
        self.__display_limits_inspector = DisplayLimitsInspector(self.ui, self.__display_limits_binding)

        self.widget.add(self.__display_limits_inspector.widget)

        # first update to get the values right
        self.__block = False
        self.needs_update = False
        self.update()

        # make sure we're listening to changes of the data item
        self.data_item.add_listener(self)

    def close(self):
        # unlisten to the data item
        self.data_item.remove_listener(self)
        # close individual inspectors
        self.__display_limits_inspector.close()
        # close the bindings
        self.__display_limits_binding.close()

    # update the values if needed
    def periodic(self):
        if self.needs_update:
            self.update()
        self.__display_limits_inspector.periodic()

    # this will typically happen on a thread
    def data_item_content_changed(self, data_source, changes):
        if not self.__block:
            # TODO: this is pretty weak!
            if any (k in changes for k in (DataItem.DISPLAY, )):
                self.needs_update = True

    def __update_info_editor(self):
        # info
        self.info_title_label.text = self.data_item.title
        self.info_session_label.text = self.data_item.session_id
        self.info_datetime_label.text = self.data_item.datetime_original_as_string
        self.info_format_label.text = self.data_item.size_and_data_format_as_string

    def __update_param_editor(self):
        # param
        value = self.data_item.param
        self.param_field_formatter.value = float(value)
        self.param_slider.value = int(value * 100)

    def __update_calibrations_editor(self):
        # calibrations
        # first match the number of rows to the number of calibrations
        # then populate
        calibrations = self.data_item.calibrations
        if len(calibrations) > 0:
            while self.calibrations_labels.count() > 0:
                self.calibrations_labels.remove(self.calibrations_labels.count() - 1)
            calibration_row = self.ui.create_row_widget()
            row_label = self.ui.create_label_widget("Axis", properties={"width": 60})
            origin_field = self.ui.create_label_widget("Origin", properties={"width": 60})
            scale_field = self.ui.create_label_widget("Scale", properties={"width": 60})
            units_field = self.ui.create_label_widget("Units", properties={"width": 60})
            calibration_row.add_spacing(20)
            calibration_row.add(row_label)
            calibration_row.add_spacing(12)
            calibration_row.add(origin_field)
            calibration_row.add_spacing(12)
            calibration_row.add(scale_field)
            calibration_row.add_spacing(12)
            calibration_row.add(units_field)
            calibration_row.add_stretch()
            calibration_header_column = self.ui.create_column_widget()
            calibration_header_column.add(calibration_row)
            calibration_header_column.add_spacing(4)
            self.calibrations_labels.add(calibration_header_column)
        else:
            while self.calibrations_labels.count() > 0:
                self.calibrations_labels.remove(self.calibrations_labels.count() - 1)
            self.calibrations_none_column = self.ui.create_column_widget()
            self.calibrations_none_column.add_spacing(4)
            self.calibrations_none_row = self.ui.create_row_widget()
            self.calibrations_none_row.add_spacing(20)
            self.calibrations_none_row.add(self.ui.create_label_widget("None", properties={"stylesheet": "font: italic"}))
            self.calibrations_none_column.add(self.calibrations_none_row)
            self.calibrations_labels.add(self.calibrations_none_column)
        while self.calibrations_column.count() < len(calibrations):
            calibration_index = self.calibrations_column.count()
            calibration_row = self.ui.create_row_widget()
            row_label = self.ui.create_label_widget(properties={"width": 60})
            origin_field = self.ui.create_line_edit_widget(properties={"width": 60})
            scale_field = self.ui.create_line_edit_widget(properties={"width": 60})
            units_field = self.ui.create_line_edit_widget(properties={"width": 60})
            # notice the binding of calibration_index below.
            origin_field.on_editing_finished = lambda text, i=calibration_index: self.calibration_origin_editing_finished(i, text)
            scale_field.on_editing_finished = lambda text, i=calibration_index: self.calibration_scale_editing_finished(i, text)
            units_field.on_editing_finished = lambda text, i=calibration_index: self.calibration_units_editing_finished(i, text)
            calibration_row.add(row_label)
            calibration_row.add_spacing(12)
            calibration_row.add(origin_field)
            calibration_row.add_spacing(12)
            calibration_row.add(scale_field)
            calibration_row.add_spacing(12)
            calibration_row.add(units_field)
            calibration_row.add_stretch()
            self.calibrations_column.add(calibration_row)
        while self.calibrations_column.count() > len(calibrations):
            self.calibrations_column.remove(len(calibrations) - 1)
        for calibration_index, calibration in enumerate(calibrations):
            calibration_row = self.calibrations_column.children[calibration_index]
            calibration_row.children[0].text = "{0:d}".format(calibration_index)
            calibration_row.children[1].text = "{0:.2f}".format(calibration.origin)
            calibration_row.children[2].text = "{0:.2f}".format(calibration.scale)
            calibration_row.children[3].text = calibration.units

    # update will NEVER be called on a thread
    def update(self):
        self.__update_info_editor()
        self.__update_param_editor()
        self.__update_calibrations_editor()
        self.__display_limits_inspector.update()
        self.needs_update = False

    # handle param editing
    def param_slider_value_changed(self, value):
        self.data_item.param = self.param_slider.value/100.0
        self.update()  # clean up displayed values
    def param_editing_finished(self, text):
        self.data_item.param = self.param_field_formatter.value
        self.update()  # clean up displayed values
        if self.param_field.focused:
            self.param_field.select_all()

    # handle calibration editing
    def calibration_origin_editing_finished(self, calibration_index, text):
        block = self.__block
        self.__block = True
        self.data_item.calibrations[calibration_index].origin = float(text)
        self.__block = block
        self.update()  # clean up displayed values
        line_edit_widget = self.calibrations_column.children[calibration_index].children[1]
        if line_edit_widget.focused:
            line_edit_widget.select_all()
    def calibration_scale_editing_finished(self, calibration_index, text):
        block = self.__block
        self.__block = True
        self.data_item.calibrations[calibration_index].scale = float(text)
        self.__block = block
        self.update()  # clean up displayed values
        line_edit_widget = self.calibrations_column.children[calibration_index].children[2]
        if line_edit_widget.focused:
            line_edit_widget.select_all()
    def calibration_units_editing_finished(self, calibration_index, text):
        block = self.__block
        self.__block = True
        self.data_item.calibrations[calibration_index].units = text
        self.__block = block
        self.update()  # clean up displayed values
        line_edit_widget = self.calibrations_column.children[calibration_index].children[3]
        if line_edit_widget.focused:
            line_edit_widget.select_all()
