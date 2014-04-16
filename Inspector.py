# standard libraries
import gettext
import logging
import threading

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import Operation
from nion.ui import Binding
from nion.ui import Converter
from nion.ui import Process

_ = gettext.gettext


class InspectorPanel(Panel.Panel):
    def __init__(self, document_controller, panel_id, properties):
        super(InspectorPanel, self).__init__(document_controller, panel_id, _("Inspector"))

        self.__display = None
        self.__display_inspector = None

        # bind to the selected data item.
        # connect self as listener. this will result in calls to data_item_binding_data_item_changed
        # and data_item_binding_data_item_content_changed
        self.__display_binding = document_controller.create_selected_data_item_binding()
        self.__set_display(None)
        self.__display_binding.add_listener(self)

        # top level widget in this inspector is a scroll area.
        # content of the scroll area is the column, to which inspectors
        # can be added.
        scroll_area = self.ui.create_scroll_area_widget(properties)
        scroll_area.set_scrollbar_policies("off", "needed")
        self.column = self.ui.create_column_widget()
        scroll_area.content = self.column
        self.widget = scroll_area

    def close(self):
        # disconnect self as listener
        self.__display_binding.remove_listener(self)
        # close the property controller. note: this will close and create
        # a new data item inspector; so it should go before the final
        # data item inspector close, which is below.
        self.__display_binding.close()
        self.__set_display(None)
        # close the data item inspector
        if self.__display_inspector:
            self.__display_inspector.close()
        # finish closing
        super(InspectorPanel, self).close()

    def periodic(self):
        super(InspectorPanel, self).periodic()
        if self.__display_inspector:
            self.__display_inspector.periodic()

    # close the old data item inspector, and create a new one
    # not thread safe.
    def __update_display_inspector(self):
        if self.__display_inspector:
            self.column.remove(self.__display_inspector.widget)
            self.__display_inspector.close()
            self.__display_inspector = None
        if self.__display:
            self.__display_inspector = DataItemInspector(self.ui, self.__display)
            self.column.add(self.__display_inspector.widget)

    def __set_display(self, display):
        if self.__display != display:
            self.__display = display
            self.__update_display_inspector()

    # this message is received from the data item binding.
    # it is established using add_listener. when it is called
    # mark the data item as needing updating.
    # thread safe.
    def data_item_binding_display_changed(self, display):
        def update_display():
            self.__set_display(display)
        self.add_task("update_display", update_display)


class InspectorSection(object):

    """
        Represent a section in the inspector. The section is composed of a
        title in bold and then content. Subclasses should use add_widget_to_content
        to add item to the content portion of the section.
    """

    def __init__(self, ui, section_title):
        self.ui = ui
        self.__task_set = Process.TaskSet()
        self.__section_widget = self.ui.create_column_widget()
        section_title_row = self.ui.create_row_widget()
        #section_title_row.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        section_title_row.add(self.ui.create_label_widget(section_title, properties={"stylesheet": "font-weight: bold"}))
        section_title_row.add_stretch()
        self.__section_widget.add(section_title_row)
        section_content_row = self.ui.create_row_widget()
        self.__section_content_column = self.ui.create_column_widget()
        section_content_row.add_spacing(20)
        section_content_row.add(self.__section_content_column)
        self.__section_widget.add(section_content_row)
        self.__section_widget.add_spacing(4)
        self.widget = self.__section_widget

    def close(self):
        pass

    def periodic(self):
        self.__task_set.perform_tasks()

    def add_task(self, key, task):
        self.__task_set.add_task(key, task)

    def add_widget_to_content(self, widget):
        self.__section_content_column.add_spacing(4)
        self.__section_content_column.add(widget)


class InfoInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement info inspector.
    """

    def __init__(self, ui, data_item):
        super(InfoInspectorSection, self).__init__(ui, _("Info"))
        # title
        self.info_section_title_row = self.ui.create_row_widget()
        self.info_section_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width": 60}))
        self.info_title_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_title_label.bind_text(Binding.PropertyBinding(data_item, "title"))
        self.info_section_title_row.add(self.info_title_label)
        self.info_section_title_row.add_stretch()
        # session
        self.info_section_session_row = self.ui.create_row_widget()
        self.info_section_session_row.add(self.ui.create_label_widget(_("Session"), properties={"width": 60}))
        self.info_session_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_session_label.bind_text(Binding.PropertyBinding(data_item, "session_id"))
        self.info_section_session_row.add(self.info_session_label)
        self.info_section_session_row.add_stretch()
        # date
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width": 60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_datetime_label.bind_text(Binding.PropertyBinding(data_item, "datetime_original_as_string"))
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()
        # format (size, datatype)
        self.info_section_format_row = self.ui.create_row_widget()
        self.info_section_format_row.add(self.ui.create_label_widget(_("Data"), properties={"width": 60}))
        self.info_format_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_format_label.bind_text(Binding.PropertyBinding(data_item, "size_and_data_format_as_string"))
        self.info_section_format_row.add(self.info_format_label)
        self.info_section_format_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.info_section_title_row)
        self.add_widget_to_content(self.info_section_session_row)
        self.add_widget_to_content(self.info_section_datetime_row)
        self.add_widget_to_content(self.info_section_format_row)


class ParamInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement param inspector.
        Used for testing / example code.
    """

    def __init__(self, ui, data_item):
        super(ParamInspectorSection, self).__init__(ui, _("Param"))
        # ui
        self.param_row = self.ui.create_row_widget()
        param_label = self.ui.create_label_widget(_("Parameter"))
        self.param_slider = self.ui.create_slider_widget()
        self.param_slider.maximum = 100
        self.param_slider.bind_value(Binding.PropertyBinding(data_item, "param", converter=Converter.FloatTo100Converter()))
        self.param_field = self.ui.create_line_edit_widget()
        self.param_field.bind_text(Binding.PropertyBinding(data_item, "param", converter=Converter.FloatToPercentStringConverter()))
        self.param_row.add(param_label)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_slider)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_field)
        self.param_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.param_row)


class CalibrationsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement calibrations inspector.
    """

    def __init__(self, ui, display):
        super(CalibrationsInspectorSection, self).__init__(ui, _("Calibrations"))
        data_item = display.data_item
        self.__calibrations = data_item.intrinsic_calibrations
        # ui. create the spatial calibrations list.
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        list_widget.bind_items(Binding.ListBinding(data_item, "intrinsic_calibrations"))
        self.add_widget_to_content(list_widget)
        # create the intensity row
        intensity_calibration = data_item.intrinsic_intensity_calibration
        if intensity_calibration is not None:
            intensity_row = self.ui.create_row_widget()
            row_label = self.ui.create_label_widget(_("Intensity"), properties={"width": 60})
            origin_field = self.ui.create_line_edit_widget(properties={"width": 60})
            scale_field = self.ui.create_line_edit_widget(properties={"width": 60})
            units_field = self.ui.create_line_edit_widget(properties={"width": 60})
            float_point_2_converter = Converter.FloatToStringConverter(format="{0:.2f}")
            origin_field.bind_text(Binding.PropertyBinding(intensity_calibration, "origin", converter=float_point_2_converter))
            scale_field.bind_text(Binding.PropertyBinding(intensity_calibration, "scale", float_point_2_converter))
            units_field.bind_text(Binding.PropertyBinding(intensity_calibration, "units"))
            intensity_row.add(row_label)
            intensity_row.add_spacing(12)
            intensity_row.add(origin_field)
            intensity_row.add_spacing(12)
            intensity_row.add(scale_field)
            intensity_row.add_spacing(12)
            intensity_row.add(units_field)
            intensity_row.add_stretch()
            self.add_widget_to_content(intensity_row)
        # create the display calibrations check box row
        self.display_calibrations_row = self.ui.create_row_widget()
        self.display_calibrations_checkbox = self.ui.create_check_box_widget(_("Displayed"))
        self.display_calibrations_checkbox.bind_check_state(Binding.PropertyBinding(display, "display_calibrated_values", converter=Converter.CheckedToCheckStateConverter()))
        self.display_calibrations_row.add(self.display_calibrations_checkbox)
        self.display_calibrations_row.add_stretch()
        self.add_widget_to_content(self.display_calibrations_row)

    # not thread safe
    def __create_header_widget(self):
        header_row = self.ui.create_row_widget()
        axis_header_label = self.ui.create_label_widget("Axis", properties={"width": 60})
        origin_header_label = self.ui.create_label_widget(_("Origin"), properties={"width": 60})
        scale_header_label = self.ui.create_label_widget(_("Scale"), properties={"width": 60})
        units_header_label = self.ui.create_label_widget(_("Units"), properties={"width": 60})
        header_row.add(axis_header_label)
        header_row.add_spacing(12)
        header_row.add(origin_header_label)
        header_row.add_spacing(12)
        header_row.add(scale_header_label)
        header_row.add_spacing(12)
        header_row.add(units_header_label)
        header_row.add_stretch()
        return header_row

    # not thread safe
    def __create_header_for_empty_list_widget(self):
        header_for_empty_list_row = self.ui.create_row_widget()
        header_for_empty_list_row.add(self.ui.create_label_widget("None", properties={"stylesheet": "font: italic"}))
        return header_for_empty_list_row

    # not thread safe.
    def __create_list_item_widget(self, calibration):
        calibration_row = self.ui.create_row_widget()
        row_label = self.ui.create_label_widget(properties={"width": 60})
        origin_field = self.ui.create_line_edit_widget(properties={"width": 60})
        scale_field = self.ui.create_line_edit_widget(properties={"width": 60})
        units_field = self.ui.create_line_edit_widget(properties={"width": 60})
        # convert list item to index string
        class CalibrationToIndexStringConverter(object):
            """
                Convert from calibration to index within calibration list.
                Back conversion is not implemented.
                """
            def __init__(self, calibrations):
                self.__calibrations = calibrations
            def convert(self, value):
                return str(self.__calibrations.index(value))
            def convert_back(self, str):
                raise NotImplementedError()
        # binding
        row_label.bind_text(Binding.ObjectBinding(calibration, converter=CalibrationToIndexStringConverter(self.__calibrations)))
        float_point_2_converter = Converter.FloatToStringConverter(format="{0:.2f}")
        origin_field.bind_text(Binding.PropertyBinding(calibration, "origin", converter=float_point_2_converter))
        scale_field.bind_text(Binding.PropertyBinding(calibration, "scale", float_point_2_converter))
        units_field.bind_text(Binding.PropertyBinding(calibration, "units"))
        # notice the binding of calibration_index below.
        calibration_row.add(row_label)
        calibration_row.add_spacing(12)
        calibration_row.add(origin_field)
        calibration_row.add_spacing(12)
        calibration_row.add(scale_field)
        calibration_row.add_spacing(12)
        calibration_row.add(units_field)
        calibration_row.add_stretch()
        column = self.ui.create_column_widget()
        column.add_spacing(4)
        column.add(calibration_row)
        return column


class DisplayLimitsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, ui, display):
        super(DisplayLimitsInspectorSection, self).__init__(ui, _("Display Limits"))
        # configure the display limit editor
        self.display_limits_range_row = self.ui.create_row_widget()
        self.display_limits_range_low = self.ui.create_label_widget(properties={"width": 80})
        self.display_limits_range_high = self.ui.create_label_widget(properties={"width": 80})
        float_point_2_converter = Converter.FloatToStringConverter(format="{0:.2f}")
        self.display_limits_range_low.bind_text(Binding.TuplePropertyBinding(display, "data_range", 0, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_high.bind_text(Binding.TuplePropertyBinding(display, "data_range", 1, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_row.add(self.ui.create_label_widget(_("Data Range:"), properties={"width": 120}))
        self.display_limits_range_row.add(self.display_limits_range_low)
        self.display_limits_range_row.add_spacing(8)
        self.display_limits_range_row.add(self.display_limits_range_high)
        self.display_limits_range_row.add_stretch()
        self.display_limits_limit_row = self.ui.create_row_widget()
        self.display_limits_limit_low = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_high = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_low.bind_text(Binding.TuplePropertyBinding(display, "display_range", 0, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_limit_high.bind_text(Binding.TuplePropertyBinding(display, "display_range", 1, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_limit_row.add(self.ui.create_label_widget(_("Display:"), properties={"width": 120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()
        self.add_widget_to_content(self.display_limits_range_row)
        self.add_widget_to_content(self.display_limits_limit_row)


class CalibratedValueFloatToStringConverter(object):
    """
        Converter object to convert from calibrated value to string and back.
    """
    def __init__(self, display, index, data_size):
        self.__display = display
        self.__index = index
        self.__data_size = data_size
    def convert(self, value):
        calibration = self.__display.data_item.calculated_calibrations[self.__index]
        return calibration.convert_to_calibrated_value_str(self.__data_size * value)
    def convert_back(self, str):
        calibration = self.__display.data_item.calculated_calibrations[self.__index]
        return calibration.convert_from_calibrated_value(float(str)) / self.__data_size


class CalibratedSizeFloatToStringConverter(object):
    """
        Converter object to convert from calibrated size to string and back.
        """
    def __init__(self, display, index, data_size):
        self.__display = display
        self.__index = index
        self.__data_size = data_size
    def convert(self, size):
        calibration = self.__display.data_item.calculated_calibrations[self.__index]
        return calibration.convert_to_calibrated_size_str(self.__data_size * size)
    def convert_back(self, str):
        calibration = self.__display.data_item.calculated_calibrations[self.__index]
        return calibration.convert_from_calibrated_value(float(str)) / self.__data_size


# combine the display calibrated values binding with the calibration values themselves.
# this allows the text to reflect calibrated or uncalibrated data.
# display_calibrated_values_binding should have a target value type of boolean.
class CalibratedValueBinding(Binding.Binding):
    def __init__(self, value_binding, display_calibrated_values_binding, converter):
        super(CalibratedValueBinding, self).__init__(None, converter)
        self.__value_binding = value_binding
        self.__display_calibrated_values_binding = display_calibrated_values_binding
        def update_target(value):
            self.update_target_direct(self.get_target_value())
        self.__value_binding.target_setter = update_target
        self.__display_calibrated_values_binding.target_setter = update_target
    def close(self):
        self.__value_binding.close()
        self.__display_calibrated_values_binding.close()
        super(CalibratedValueBinding, self).close()
    # set the model value from the target ui element text.
    def update_source(self, target_value):
        display_calibrated_values = self.__display_calibrated_values_binding.get_target_value()
        if display_calibrated_values:
            converted_value = self.converter.convert_back(target_value)
        else:
            converted_value = float(target_value)
        self.__value_binding.update_source(converted_value)
    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self):
        display_calibrated_values = self.__display_calibrated_values_binding.get_target_value()
        value = self.__value_binding.get_target_value()
        return self.converter.convert(value) if display_calibrated_values else "{0:g}".format(value)


def make_line_type_inspector(ui, graphic_widget, display, image_size, graphic):
    def new_display_calibrated_values_binding():
        return Binding.PropertyBinding(display, "display_calibrated_values")
    # configure the bindings
    x_converter = CalibratedValueFloatToStringConverter(display, 1, image_size[1])
    y_converter = CalibratedValueFloatToStringConverter(display, 0, image_size[0])
    start_x_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "start", 1), new_display_calibrated_values_binding(), x_converter)
    start_y_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "start", 0), new_display_calibrated_values_binding(), y_converter)
    end_x_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "end", 1), new_display_calibrated_values_binding(), x_converter)
    end_y_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "end", 0), new_display_calibrated_values_binding(), y_converter)
    # create the ui
    graphic_start_row = ui.create_row_widget()
    graphic_start_row.add_spacing(20)
    graphic_start_row.add(ui.create_label_widget(_("Start"), properties={"width": 40}))
    graphic_start_x_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_start_y_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_start_x_line_edit.bind_text(start_x_binding)
    graphic_start_y_line_edit.bind_text(start_y_binding)
    graphic_start_row.add(graphic_start_x_line_edit)
    graphic_start_row.add_spacing(8)
    graphic_start_row.add(graphic_start_y_line_edit)
    graphic_start_row.add_stretch()
    graphic_end_row = ui.create_row_widget()
    graphic_end_row.add_spacing(20)
    graphic_end_row.add(ui.create_label_widget(_("End"), properties={"width": 40}))
    graphic_end_x_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_end_y_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_end_x_line_edit.bind_text(end_x_binding)
    graphic_end_y_line_edit.bind_text(end_y_binding)
    graphic_end_row.add(graphic_end_x_line_edit)
    graphic_end_row.add_spacing(8)
    graphic_end_row.add(graphic_end_y_line_edit)
    graphic_end_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_start_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_end_row)
    graphic_widget.add_spacing(4)


def make_rectangle_type_inspector(ui, graphic_widget, display, image_size, graphic):
    def new_display_calibrated_values_binding():
        return Binding.PropertyBinding(display, "display_calibrated_values")
    # calculate values from rectangle type graphic
    x_converter = CalibratedValueFloatToStringConverter(display, 1, image_size[1])
    y_converter = CalibratedValueFloatToStringConverter(display, 0, image_size[0])
    width_converter = CalibratedSizeFloatToStringConverter(display, 1, image_size[1])
    height_converter = CalibratedSizeFloatToStringConverter(display, 0, image_size[0])
    center_x_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "center", 1), new_display_calibrated_values_binding(), x_converter)
    center_y_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "center", 0), new_display_calibrated_values_binding(), y_converter)
    size_width_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "size", 1), new_display_calibrated_values_binding(), width_converter)
    size_height_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "size", 0), new_display_calibrated_values_binding(), height_converter)
    # create the ui
    graphic_center_row = ui.create_row_widget()
    graphic_center_row.add_spacing(20)
    graphic_center_row.add(ui.create_label_widget(_("Center"), properties={"width": 40}))
    graphic_center_x_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_center_y_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_center_x_line_edit.bind_text(center_x_binding)
    graphic_center_y_line_edit.bind_text(center_y_binding)
    graphic_center_row.add(graphic_center_x_line_edit)
    graphic_center_row.add_spacing(8)
    graphic_center_row.add(graphic_center_y_line_edit)
    graphic_center_row.add_stretch()
    graphic_size_row = ui.create_row_widget()
    graphic_size_row.add_spacing(20)
    graphic_size_row.add(ui.create_label_widget(_("Size"), properties={"width": 40}))
    graphic_size_width_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_size_height_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_size_width_line_edit.bind_text(size_width_binding)
    graphic_size_height_line_edit.bind_text(size_height_binding)
    graphic_size_row.add(graphic_size_width_line_edit)
    graphic_size_row.add_spacing(8)
    graphic_size_row.add(graphic_size_height_line_edit)
    graphic_size_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_center_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_size_row)
    graphic_widget.add_spacing(4)


class GraphicsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement graphics inspector.
        """

    def __init__(self, ui, data_item, display):
        super(GraphicsInspectorSection, self).__init__(ui, _("Graphics"))
        self.__image_size = data_item.spatial_shape
        self.__calibrations = data_item.calculated_calibrations
        self.__graphics = display.drawn_graphics
        self.__display = display
        # ui
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        list_widget.bind_items(Binding.ListBinding(display, "drawn_graphics"))
        self.add_widget_to_content(list_widget)

    def __create_header_widget(self):
        return self.ui.create_row_widget()

    def __create_header_for_empty_list_widget(self):
        return self.ui.create_row_widget()

    # not thread safe
    def __create_list_item_widget(self, graphic):
        graphic_section_index = self.__graphics.index(graphic)
        image_size = self.__image_size
        calibrations = self.__calibrations
        graphic_title_row = self.ui.create_row_widget()
        graphic_title_index_label = self.ui.create_label_widget(str(graphic_section_index), properties={"width": 20})
        graphic_title_type_label = self.ui.create_label_widget()
        graphic_title_row.add(graphic_title_index_label)
        graphic_title_row.add(graphic_title_type_label)
        graphic_title_row.add_stretch()
        graphic_widget = self.ui.create_column_widget()
        graphic_widget.add(graphic_title_row)
        if isinstance(graphic, Graphics.LineGraphic):
            graphic_title_type_label.text = _("Line")
            make_line_type_inspector(self.ui, graphic_widget, self.__display, image_size, graphic)
        if isinstance(graphic, Operation.LineProfileGraphic):
            graphic_title_type_label.text = _("Line Profile")
            make_line_type_inspector(self.ui, graphic_widget, self.__display, image_size, graphic)
        if isinstance(graphic, Graphics.RectangleGraphic):
            graphic_title_type_label.text = _("Rectangle")
            make_rectangle_type_inspector(self.ui, graphic_widget, self.__display, image_size, graphic)
        if isinstance(graphic, Graphics.EllipseGraphic):
            graphic_title_type_label.text = _("Ellipse")
            make_rectangle_type_inspector(self.ui, graphic_widget, self.__display, image_size, graphic)
        column = self.ui.create_column_widget()
        column.add_spacing(4)
        column.add(graphic_widget)
        return column


class OperationsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement operations inspector.
    """

    def __init__(self, ui, data_item):
        super(OperationsInspectorSection, self).__init__(ui, _("Operations"))
        self.__operations = data_item.operations
        # ui. create the spatial operations list.
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), None, header_for_empty_list_widget)
        list_widget.bind_items(Binding.ListBinding(data_item, "operations"))
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
                slider_widget.bind_value(Operation.OperationPropertyBinding(operation, property, converter=Converter.FloatTo100Converter()))
                line_edit_widget = self.ui.create_line_edit_widget()
                line_edit_widget.bind_text(Operation.OperationPropertyBinding(operation, property, converter=Converter.FloatToPercentStringConverter()))
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
                line_edit_widget.bind_text(Operation.OperationPropertyBinding(operation, property, converter=Converter.IntegerToStringConverter()))
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


class DataItemInspector(object):

    def __init__(self, ui, display):
        self.ui = ui

        data_item = display.data_item

        self.__inspectors = list()
        content_widget = self.ui.create_column_widget()
        content_widget.add_spacing(6)

        self.__inspectors.append(InfoInspectorSection(self.ui, data_item))
#       self.__inspectors.append(ParamInspectorSection(self.ui, data_item))
        self.__inspectors.append(CalibrationsInspectorSection(self.ui, display))
        if data_item.is_data_1d:
            self.__inspectors.append(DisplayLimitsInspectorSection(self.ui, display))
        elif data_item.is_data_2d or data_item.is_data_3d:
            self.__inspectors.append(DisplayLimitsInspectorSection(self.ui, display))
            self.__inspectors.append(GraphicsInspectorSection(self.ui, data_item, display))
        self.__inspectors.append(OperationsInspectorSection(self.ui, data_item))

        for inspector in self.__inspectors:
            content_widget.add(inspector.widget)

        content_widget.add_stretch()

        self.widget = content_widget

    def close(self):
        # close inspectors
        for inspector in self.__inspectors:
            inspector.close()

    # update the values if needed
    def periodic(self):
        for inspector in self.__inspectors:
            inspector.periodic()
