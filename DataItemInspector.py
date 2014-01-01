# standard libraries
import gettext
import logging

# third party libraries
# None

# local libraries
from nion.swift import DataItem
from nion.swift import Decorators
from nion.swift import Graphics
from nion.swift import Storage
from nion.swift import UserInterfaceUtility

_ = gettext.gettext


class InspectorSection(object):

    """
        Represent a section in the inspector. The section is composed of a
        title in bold and then content. Subclasses should use add_widget_to_content
        to add item to the content portion of the section.
    """

    def __init__(self, ui, section_title):
        self.ui = ui
        self.__task_set = Decorators.TaskSet()
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


class InfoInspector(InspectorSection):

    """
        Subclass InspectorSection to implement info inspector.
    """

    def __init__(self, ui, data_item_binding_source):
        super(InfoInspector, self).__init__(ui, _("Info"))
        # title
        self.info_section_title_row = self.ui.create_row_widget()
        self.info_section_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width": 60}))
        self.info_title_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_title_label.bind_text(UserInterfaceUtility.PropertyBinding(data_item_binding_source, "title"))
        self.info_section_title_row.add(self.info_title_label)
        self.info_section_title_row.add_stretch()
        # session
        self.info_section_session_row = self.ui.create_row_widget()
        self.info_section_session_row.add(self.ui.create_label_widget(_("Session"), properties={"width": 60}))
        self.info_session_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_session_label.bind_text(UserInterfaceUtility.PropertyBinding(data_item_binding_source, "session_id"))
        self.info_section_session_row.add(self.info_session_label)
        self.info_section_session_row.add_stretch()
        # date
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width": 60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_datetime_label.bind_text(UserInterfaceUtility.PropertyBinding(data_item_binding_source, "datetime_original_as_string"))
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()
        # format (size, datatype)
        self.info_section_format_row = self.ui.create_row_widget()
        self.info_section_format_row.add(self.ui.create_label_widget(_("Data"), properties={"width": 60}))
        self.info_format_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_format_label.bind_text(UserInterfaceUtility.PropertyBinding(data_item_binding_source, "size_and_data_format_as_string"))
        self.info_section_format_row.add(self.info_format_label)
        self.info_section_format_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.info_section_title_row)
        self.add_widget_to_content(self.info_section_session_row)
        self.add_widget_to_content(self.info_section_datetime_row)
        self.add_widget_to_content(self.info_section_format_row)


class ParamInspector(InspectorSection):

    """
        Subclass InspectorSection to implement param inspector.
        Used for testing / example code.
    """

    def __init__(self, ui, data_item_binding_source):
        super(ParamInspector, self).__init__(ui, _("Param"))
        # ui
        self.param_row = self.ui.create_row_widget()
        param_label = self.ui.create_label_widget(_("Parameter"))
        self.param_slider = self.ui.create_slider_widget()
        self.param_slider.maximum = 100
        self.param_slider.bind_value(UserInterfaceUtility.PropertyBinding(data_item_binding_source, "param", converter=UserInterfaceUtility.FloatTo100Converter()))
        self.param_field = self.ui.create_line_edit_widget()
        self.param_field.bind_text(UserInterfaceUtility.PropertyBinding(data_item_binding_source, "param", converter=UserInterfaceUtility.FloatToPercentStringConverter()))
        self.param_row.add(param_label)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_slider)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_field)
        self.param_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.param_row)


class CalibrationsInspector(InspectorSection):

    """
        Subclass InspectorSection to implement calibrations inspector.
    """

    def __init__(self, ui, data_item_binding_source):
        super(CalibrationsInspector, self).__init__(ui, _("Calibrations"))
        self.__calibrations = data_item_binding_source.calibrations
        # ui
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        list_widget.bind_items(UserInterfaceUtility.ListBinding(data_item_binding_source, "calibrations"))
        self.add_widget_to_content(list_widget)
        self.display_calibrations_row = self.ui.create_row_widget()
        self.display_calibrations_checkbox = self.ui.create_check_box_button_widget(_("Displayed"))
        self.display_calibrations_checkbox.bind_check_state(UserInterfaceUtility.PropertyBinding(data_item_binding_source, "display_calibrated_values", converter=UserInterfaceUtility.CheckedToCheckStateConverter()))
        self.display_calibrations_row.add(self.display_calibrations_checkbox)
        self.display_calibrations_row.add_stretch()
        self.add_widget_to_content(self.display_calibrations_row)

    # not thead safe
    def __create_header_widget(self):
        header_row = self.ui.create_row_widget()
        axis_header_label = self.ui.create_label_widget("Axis", properties={"width": 60})
        origin_header_label = self.ui.create_label_widget("Origin", properties={"width": 60})
        scale_header_label = self.ui.create_label_widget("Scale", properties={"width": 60})
        units_header_label = self.ui.create_label_widget("Units", properties={"width": 60})
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
        row_label.bind_text(UserInterfaceUtility.ObjectBinding(calibration, converter=CalibrationToIndexStringConverter(self.__calibrations)))
        float_point_2_converter = converter=UserInterfaceUtility.FloatToStringConverter(format="{0:.2f}")
        origin_field.bind_text(UserInterfaceUtility.PropertyBinding(calibration, "origin", converter=float_point_2_converter))
        scale_field.bind_text(UserInterfaceUtility.PropertyBinding(calibration, "scale", float_point_2_converter))
        units_field.bind_text(UserInterfaceUtility.PropertyBinding(calibration, "units"))
        # notice the binding of calibration_index below.
        calibration_row.add(row_label)
        calibration_row.add_spacing(12)
        calibration_row.add(origin_field)
        calibration_row.add_spacing(12)
        calibration_row.add(scale_field)
        calibration_row.add_spacing(12)
        calibration_row.add(units_field)
        calibration_row.add_stretch()
        return calibration_row


class DisplayLimitsInspector(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, ui, data_item_binding_source):
        super(DisplayLimitsInspector, self).__init__(ui, _("Display Limits"))
        # configure the display limit editor
        self.display_limits_range_row = self.ui.create_row_widget()
        self.display_limits_range_low = self.ui.create_label_widget(properties={"width": 80})
        self.display_limits_range_high = self.ui.create_label_widget(properties={"width": 80})
        float_point_2_converter = converter=UserInterfaceUtility.FloatToStringConverter(format="{0:.2f}")
        self.display_limits_range_low.bind_text(UserInterfaceUtility.TuplePropertyBinding(data_item_binding_source, "data_range", 0, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_high.bind_text(UserInterfaceUtility.TuplePropertyBinding(data_item_binding_source, "data_range", 1, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_row.add(self.ui.create_label_widget(_("Data Range:"), properties={"width": 120}))
        self.display_limits_range_row.add(self.display_limits_range_low)
        self.display_limits_range_row.add_spacing(8)
        self.display_limits_range_row.add(self.display_limits_range_high)
        self.display_limits_range_row.add_stretch()
        self.display_limits_limit_row = self.ui.create_row_widget()
        self.display_limits_limit_low = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_high = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_low.bind_text(UserInterfaceUtility.TuplePropertyBinding(data_item_binding_source, "display_range", 0, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_limit_high.bind_text(UserInterfaceUtility.TuplePropertyBinding(data_item_binding_source, "display_range", 1, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_limit_row.add(self.ui.create_label_widget(_("Display:"), properties={"width": 120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()
        self.add_widget_to_content(self.display_limits_range_row)
        self.add_widget_to_content(self.display_limits_limit_row)


class GraphicsInspector(InspectorSection):

    """
        Subclass InspectorSection to implement graphics inspector.
        """

    def __init__(self, ui, data_item_binding_source):
        super(GraphicsInspector, self).__init__(ui, _("Graphics"))
        self.__image_size = data_item_binding_source.spatial_shape
        self.__calibrations = data_item_binding_source.calculated_calibrations
        self.__graphics = data_item_binding_source.graphics
        self.__data_item_binding_source = data_item_binding_source
        # ui
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        list_widget.bind_items(UserInterfaceUtility.ListBinding(data_item_binding_source, "graphics"))
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
        graphic_widget = self.ui.create_column_widget()
        graphic_title_row = self.ui.create_row_widget()
        graphic_title_index_label = self.ui.create_label_widget(str(graphic_section_index), properties={"width": 20})
        graphic_title_type_label = self.ui.create_label_widget()
        graphic_title_row.add(graphic_title_index_label)
        graphic_title_row.add(graphic_title_type_label)
        graphic_title_row.add_stretch()
        graphic_widget.add(graphic_title_row)
        class CalibratedValueBinding(UserInterfaceUtility.Binding):
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
            def periodic(self):
                super(CalibratedValueBinding, self).periodic()
                self.__value_binding.periodic()
                self.__display_calibrated_values_binding.periodic()
            def update_source(self, target_value):
                display_calibrated_values = self.__display_calibrated_values_binding.get_target_value()
                if display_calibrated_values:
                    converted_value = self.converter.convert_back(target_value)
                else:
                    converted_value = float(target_value)
                self.__value_binding.update_source(converted_value)
            def get_target_value(self):
                display_calibrated_values = self.__display_calibrated_values_binding.get_target_value()
                value = self.__value_binding.get_target_value()
                return self.converter.convert(value) if display_calibrated_values else "{0:g}".format(value)
        def new_display_calibrated_values_binding():
            return UserInterfaceUtility.PropertyBinding(self.__data_item_binding_source, "display_calibrated_values")
        if isinstance(graphic, Graphics.LineGraphic):
            # configure the bindings
            x_converter = DataItem.CalibratedValueFloatToStringConverter(calibrations[1], image_size[1])
            y_converter = DataItem.CalibratedValueFloatToStringConverter(calibrations[0], image_size[0])
            start_x_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "start", 1), new_display_calibrated_values_binding(), x_converter)
            start_y_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "start", 0), new_display_calibrated_values_binding(), y_converter)
            end_x_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "end", 1), new_display_calibrated_values_binding(), x_converter)
            end_y_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "end", 0), new_display_calibrated_values_binding(), y_converter)
            # create the ui
            graphic_title_type_label.text = _("Line")
            graphic_start_row = self.ui.create_row_widget()
            graphic_start_row.add_spacing(20)
            graphic_start_row.add(self.ui.create_label_widget(_("Start"), properties={"width": 40}))
            graphic_start_x_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_start_y_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_start_x_line_edit.bind_text(start_x_binding)
            graphic_start_y_line_edit.bind_text(start_y_binding)
            graphic_start_row.add(graphic_start_x_line_edit)
            graphic_start_row.add_spacing(8)
            graphic_start_row.add(graphic_start_y_line_edit)
            graphic_start_row.add_stretch()
            graphic_end_row = self.ui.create_row_widget()
            graphic_end_row.add_spacing(20)
            graphic_end_row.add(self.ui.create_label_widget(_("End"), properties={"width": 40}))
            graphic_end_x_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_end_y_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
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
        if isinstance(graphic, Graphics.RectangleGraphic):
            # calculate values from rectangle graphic
            x_converter = DataItem.CalibratedValueFloatToStringConverter(calibrations[1], image_size[1])
            y_converter = DataItem.CalibratedValueFloatToStringConverter(calibrations[0], image_size[0])
            width_converter = DataItem.CalibratedSizeFloatToStringConverter(calibrations[1], image_size[1])
            height_converter = DataItem.CalibratedSizeFloatToStringConverter(calibrations[0], image_size[0])
            origin_x_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "origin", 1), new_display_calibrated_values_binding(), x_converter)
            origin_y_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "origin", 0), new_display_calibrated_values_binding(), y_converter)
            size_width_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "size", 1), new_display_calibrated_values_binding(), width_converter)
            size_height_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "size", 0), new_display_calibrated_values_binding(), height_converter)
            # create the ui
            graphic_title_type_label.text = _("Rectangle")
            graphic_origin_row = self.ui.create_row_widget()
            graphic_origin_row.add_spacing(20)
            graphic_origin_row.add(self.ui.create_label_widget(_("Origin"), properties={"width": 40}))
            graphic_origin_x_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_origin_y_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_origin_x_line_edit.bind_text(origin_x_binding)
            graphic_origin_y_line_edit.bind_text(origin_y_binding)
            graphic_origin_row.add(graphic_origin_x_line_edit)
            graphic_origin_row.add_spacing(8)
            graphic_origin_row.add(graphic_origin_y_line_edit)
            graphic_origin_row.add_stretch()
            graphic_size_row = self.ui.create_row_widget()
            graphic_size_row.add_spacing(20)
            graphic_size_row.add(self.ui.create_label_widget(_("Size"), properties={"width": 40}))
            graphic_size_width_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_size_height_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_size_width_line_edit.bind_text(size_width_binding)
            graphic_size_height_line_edit.bind_text(size_height_binding)
            graphic_size_row.add(graphic_size_width_line_edit)
            graphic_size_row.add_spacing(8)
            graphic_size_row.add(graphic_size_height_line_edit)
            graphic_size_row.add_stretch()
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_origin_row)
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_size_row)
            graphic_widget.add_spacing(4)
        if isinstance(graphic, Graphics.EllipseGraphic):
            # calculate values from ellipse graphic
            x_converter = DataItem.CalibratedValueFloatToStringConverter(calibrations[1], image_size[1])
            y_converter = DataItem.CalibratedValueFloatToStringConverter(calibrations[0], image_size[0])
            width_converter = DataItem.CalibratedSizeFloatToStringConverter(calibrations[1], image_size[1])
            height_converter = DataItem.CalibratedSizeFloatToStringConverter(calibrations[0], image_size[0])
            origin_x_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "origin", 1), new_display_calibrated_values_binding(), x_converter)
            origin_y_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "origin", 0), new_display_calibrated_values_binding(), y_converter)
            size_width_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "size", 1), new_display_calibrated_values_binding(), width_converter)
            size_height_binding = CalibratedValueBinding(UserInterfaceUtility.TuplePropertyBinding(graphic, "size", 0), new_display_calibrated_values_binding(), height_converter)
            # create the ui
            graphic_title_type_label.text = _("Ellipse")
            graphic_origin_row = self.ui.create_row_widget()
            graphic_origin_row.add_spacing(20)
            graphic_origin_row.add(self.ui.create_label_widget(_("Origin"), properties={"width": 40}))
            graphic_origin_x_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_origin_y_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_origin_x_line_edit.bind_text(origin_x_binding)
            graphic_origin_y_line_edit.bind_text(origin_y_binding)
            graphic_origin_row.add(graphic_origin_x_line_edit)
            graphic_origin_row.add_spacing(8)
            graphic_origin_row.add(graphic_origin_y_line_edit)
            graphic_origin_row.add_stretch()
            graphic_size_row = self.ui.create_row_widget()
            graphic_size_row.add_spacing(20)
            graphic_size_row.add(self.ui.create_label_widget(_("Size"), properties={"width": 40}))
            graphic_size_width_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_size_height_line_edit = self.ui.create_line_edit_widget(properties={"width": 80})
            graphic_size_width_line_edit.bind_text(size_width_binding)
            graphic_size_height_line_edit.bind_text(size_height_binding)
            graphic_size_row.add(graphic_size_width_line_edit)
            graphic_size_row.add_spacing(8)
            graphic_size_row.add(graphic_size_height_line_edit)
            graphic_size_row.add_stretch()
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_origin_row)
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_size_row)
            graphic_widget.add_spacing(4)
        return graphic_widget


class DataItemInspector(object):

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
        self.widget = self.ui.create_column_widget()
        self.widget.add_spacing(6)

        self.__inspectors.append(InfoInspector(self.ui, self.__data_item_binding_source))
        # self.__inspectors.append(ParamInspector(self.ui, self.__data_item_binding_source))
        self.__inspectors.append(CalibrationsInspector(self.ui, self.__data_item_binding_source))
        self.__inspectors.append(DisplayLimitsInspector(self.ui, self.__data_item_binding_source))
        self.__inspectors.append(GraphicsInspector(self.ui, self.__data_item_binding_source))

        for inspector in self.__inspectors:
            self.widget.add(inspector.widget)

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
