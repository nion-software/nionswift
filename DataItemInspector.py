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

    def __init__(self, ui, data_item_content_binding):
        super(InfoInspector, self).__init__(ui, _("Info"))
        # initialize the binding. this will result in calls to data_item_info_changed.
        self.data_item_content_binding = data_item_content_binding
        self.data_item_content_binding.add_listener(self)
        # title
        self.info_section_title_row = self.ui.create_row_widget()
        self.info_section_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width": 60}))
        self.info_title_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_title_row.add(self.info_title_label)
        self.info_section_title_row.add_stretch()
        # session
        self.info_section_session_row = self.ui.create_row_widget()
        self.info_section_session_row.add(self.ui.create_label_widget(_("Session"), properties={"width": 60}))
        self.info_session_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_session_row.add(self.info_session_label)
        self.info_section_session_row.add_stretch()
        # date
        self.info_section_datetime_row = self.ui.create_row_widget()
        self.info_section_datetime_row.add(self.ui.create_label_widget(_("Date"), properties={"width": 60}))
        self.info_datetime_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_datetime_row.add(self.info_datetime_label)
        self.info_section_datetime_row.add_stretch()
        # format (size, datatype)
        self.info_section_format_row = self.ui.create_row_widget()
        self.info_section_format_row.add(self.ui.create_label_widget(_("Data"), properties={"width": 60}))
        self.info_format_label = self.ui.create_label_widget(properties={"width": 240})
        self.info_section_format_row.add(self.info_format_label)
        self.info_section_format_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.info_section_title_row)
        self.add_widget_to_content(self.info_section_session_row)
        self.add_widget_to_content(self.info_section_datetime_row)
        self.add_widget_to_content(self.info_section_format_row)
        # initial update
        self.update()

    def close(self):
        self.data_item_content_binding.remove_listener(self)
        super(InfoInspector, self).close()

    # this gets called from the data_item_content_binding.
    # thread safe
    def data_item_display_content_changed(self):
        self.add_task("update", lambda: self.update())

    # not thread safe
    def update(self):
        self.info_title_label.text = self.data_item_content_binding.title
        self.info_session_label.text = self.data_item_content_binding.session_id
        self.info_datetime_label.text = self.data_item_content_binding.datetime_original_as_string
        self.info_format_label.text = self.data_item_content_binding.size_and_data_format_as_string


class ParamInspector(InspectorSection):

    """
        Subclass InspectorSection to implement param inspector.
        Used for testing / example code.
    """

    def __init__(self, ui, data_item_binding_source):
        super(ParamInspector, self).__init__(ui, _("Param"))
        # initialize the binding. this will result in calls to data_item_info_changed.
        self.data_item_binding_source = data_item_binding_source
        # binding
        def update_param_field(text):
            self.param_field.text = text
            if self.param_field.focused:
                self.param_field.select_all()
        def update_param_slider(value):
            self.param_slider.value = value
        def update_data_item(data_item):
            self.data_item_binding_source.data_item = data_item
        class FloatTo100Converter(object):
            def convert(self, value):
                return int(value * 100)
            def convert_back(self, value100):
                return value100 / 100.0
        self.param_field_binding = UserInterfaceUtility.PropertyTwoWayBinding(data_item_binding_source, "param", update_param_field, converter=UserInterfaceUtility.FloatToStringConverter())
        self.param_slider_binding = UserInterfaceUtility.PropertyTwoWayBinding(data_item_binding_source, "param", update_param_slider, converter=FloatTo100Converter())
        self.data_item_binding = UserInterfaceUtility.PropertyTwoWayBinding(data_item_binding_source, "data_item", update_data_item)
        # ui
        self.param_row = self.ui.create_row_widget()
        param_label = self.ui.create_label_widget(_("Parameter"))
        self.param_slider = self.ui.create_slider_widget()
        self.param_slider.maximum = 100
        self.param_slider.on_value_changed = lambda value: self.param_slider_binding.update_source(value)
        self.param_slider.value = self.param_slider_binding.get_target_value()
        self.param_field = self.ui.create_line_edit_widget()
        self.param_field.on_editing_finished = lambda text: self.param_field_binding.update_source(text)
        self.param_field.text = self.param_field_binding.get_target_value()
        self.param_row.add(param_label)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_slider)
        self.param_row.add_spacing(8)
        self.param_row.add(self.param_field)
        self.param_row.add_stretch()
        # add all of the rows to the section content
        self.add_widget_to_content(self.param_row)

    def close(self):
        self.param_field_binding.close()
        self.param_slider_binding.close()
        self.data_item_binding.close()
        super(ParamInspector, self).close()

    def periodic(self):
        super(ParamInspector, self).periodic()
        self.param_field_binding.periodic()
        self.param_slider_binding.periodic()
        self.data_item_binding.periodic()


class CalibrationsInspector(InspectorSection):

    """
        Subclass InspectorSection to implement calibrations inspector.
    """

    def __init__(self, ui, data_item_content_binding):
        super(CalibrationsInspector, self).__init__(ui, _("Calibrations"))
        # initialize the binding. this will result in calls to display_limits_changed.
        self.data_item_content_binding = data_item_content_binding
        self.data_item_content_binding.add_listener(self)
        # ui
        self.calibrations_table = self.ui.create_column_widget()
        self.calibrations_labels = self.ui.create_column_widget()
        self.calibrations_column = self.ui.create_column_widget(properties={"spacing": 4, "margin-top": 4})
        self.calibrations_column_row = self.ui.create_row_widget()
        self.calibrations_column_row.add(self.calibrations_column)
        self.calibrations_table.add(self.calibrations_labels)
        self.calibrations_table.add(self.calibrations_column_row)
        self.add_widget_to_content(self.calibrations_table)
        self.display_calibrations_row = self.ui.create_row_widget()
        self.display_calibrations_checkbox = self.ui.create_check_box_button_widget(_("Displayed"))
        self.display_calibrations_checkbox.on_state_changed = lambda state: self.display_calibrations_changed(state)
        self.display_calibrations_row.add(self.display_calibrations_checkbox)
        self.display_calibrations_row.add_stretch()
        self.add_widget_to_content(self.display_calibrations_row)
        # initial update
        self.update()

    def close(self):
        self.data_item_content_binding.remove_listener(self)
        super(CalibrationsInspector, self).close()

    # this gets called from the data_item_content_binding
    # thread safe
    def data_item_display_content_changed(self):
        self.add_task("update", lambda: self.update())

    # not thread safe
    def update(self):
        self.display_calibrations_checkbox.check_state = "checked" if self.data_item_content_binding.display_calibrated_values else "unchecked"
        # calibrations
        # first match the number of rows to the number of calibrations
        # then populate
        calibrations = self.data_item_content_binding.calibrations
        if len(calibrations) > 0:
            while self.calibrations_labels.count() > 0:
                self.calibrations_labels.remove(self.calibrations_labels.count() - 1)
            calibration_row = self.ui.create_row_widget()
            row_label = self.ui.create_label_widget("Axis", properties={"width": 60})
            origin_field = self.ui.create_label_widget("Origin", properties={"width": 60})
            scale_field = self.ui.create_label_widget("Scale", properties={"width": 60})
            units_field = self.ui.create_label_widget("Units", properties={"width": 60})
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
            calibration_header_column.add_spacing(2)
            self.calibrations_labels.add(calibration_header_column)
        else:
            while self.calibrations_labels.count() > 0:
                self.calibrations_labels.remove(self.calibrations_labels.count() - 1)
            self.calibrations_none_column = self.ui.create_column_widget()
            self.calibrations_none_column.add_spacing(2)
            self.calibrations_none_row = self.ui.create_row_widget()
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
            for child_index in xrange(1, 4):
                if calibration_row.children[child_index].focused:
                    calibration_row.children[child_index].select_all()

    # handle calibration editing
    def calibration_origin_editing_finished(self, calibration_index, text):
        self.data_item_content_binding.calibrations[calibration_index].origin = float(text)
        self.update()  # clean up displayed values

    def calibration_scale_editing_finished(self, calibration_index, text):
        self.data_item_content_binding.calibrations[calibration_index].scale = float(text)
        self.update()  # clean up displayed values

    def calibration_units_editing_finished(self, calibration_index, text):
        self.data_item_content_binding.calibrations[calibration_index].units = text
        self.update()  # clean up displayed values

    def display_calibrations_changed(self, state):
        self.data_item_content_binding.display_calibrated_values = state == "checked"
        self.update()  # clean up displayed values


class DisplayLimitsInspector(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, ui, data_item_content_binding):
        super(DisplayLimitsInspector, self).__init__(ui, _("Display Limits"))
        # initialize the binding. this will result in calls to display_limits_changed.
        self.data_item_content_binding = data_item_content_binding
        self.data_item_content_binding.add_listener(self)
        # configure the display limit editor
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
        self.add_widget_to_content(self.display_limits_range_row)
        self.add_widget_to_content(self.display_limits_limit_row)
        # initial update
        self.update()

    def close(self):
        self.data_item_content_binding.remove_listener(self)
        super(DisplayLimitsInspector, self).close()

    # this gets called from the data_item_content_binding
    # thread safe
    def data_item_display_content_changed(self):
        self.add_task("update", lambda: self.update())

    # not thread safe
    def update(self):
        # display limits
        data_range = self.data_item_content_binding.data_range
        if data_range:
            self.display_limits_range_low.text = "{0:.2f}".format(data_range[0])
            self.display_limits_range_high.text = "{0:.2f}".format(data_range[1])
        else:
            self.display_limits_range_low.text = _("N/A")
            self.display_limits_range_high.text = _("N/A")
        display_range = self.data_item_content_binding.display_range
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
            self.data_item_content_binding.display_limits = (display_limit_low, self.data_item_content_binding.display_range[1])
            self.update()  # clean up displayed values

    def display_limit_high_editing_finished(self, text):
        if self.display_limits_range_high.text != text:
            display_limit_high = float(text)
            self.data_item_content_binding.display_limits = (self.data_item_content_binding.display_range[0], display_limit_high)
            self.update()  # clean up displayed values


class GraphicsInspector(InspectorSection):

    """
        Subclass InspectorSection to implement graphics inspector.
        """

    def __init__(self, ui, data_item_content_binding):
        super(GraphicsInspector, self).__init__(ui, _("Graphics"))
        # initialize the binding. this will result in calls to display_limits_changed.
        self.data_item_content_binding = data_item_content_binding
        self.data_item_content_binding.add_listener(self)
        # ui
        self.graphic_sections = self.ui.create_column_widget()
        self.add_widget_to_content(self.graphic_sections)
        # initial update
        self.update()

    def close(self):
        self.data_item_content_binding.remove_listener(self)
        super(GraphicsInspector, self).close()

    # this gets called from the data_item_content_binding
    # thread safe
    def data_item_display_content_changed(self):
        self.add_task("update", lambda: self.update())

    # not thread safe
    def __create_graphic_widget(self, graphic_section_index, graphic, image_size, calibrations):
        graphic_widget = self.ui.create_column_widget()
        graphic_title_row = self.ui.create_row_widget()
        graphic_title_index_label = self.ui.create_label_widget(str(graphic_section_index), properties={"width": 20})
        graphic_title_type_label = self.ui.create_label_widget()
        graphic_title_row.add(graphic_title_index_label)
        graphic_title_row.add(graphic_title_type_label)
        graphic_title_row.add_stretch()
        graphic_widget.add(graphic_title_row)
        if isinstance(graphic, Graphics.LineGraphic):
            # configure the bindings
            x_converter = DataItem.CalibratedFloatToStringConverter(calibrations[1], image_size[1])
            y_converter = DataItem.CalibratedFloatToStringConverter(calibrations[0], image_size[0])
            start_x_binding = UserInterfaceUtility.TupleOneWayToSourceBinding(graphic, "start", 1, converter=x_converter)
            start_y_binding = UserInterfaceUtility.TupleOneWayToSourceBinding(graphic, "start", 0, converter=y_converter)
            end_x_binding = UserInterfaceUtility.TupleOneWayToSourceBinding(graphic, "end", 1, converter=x_converter)
            end_y_binding = UserInterfaceUtility.TupleOneWayToSourceBinding(graphic, "end", 0, converter=y_converter)
            # create the ui
            graphic_title_type_label.text = _("Line")
            graphic_start_row = self.ui.create_row_widget()
            graphic_start_row.add_spacing(20)
            graphic_start_row.add(self.ui.create_label_widget(_("Start"), properties={"width": 40}))
            graphic_start_x_line_edit = self.ui.create_line_edit_widget(properties={"width": 60})
            graphic_start_y_line_edit = self.ui.create_line_edit_widget(properties={"width": 60})
            graphic_start_x_line_edit.on_editing_finished = lambda text: start_x_binding.update_source(text)
            graphic_start_y_line_edit.on_editing_finished = lambda text: start_y_binding.update_source(text)
            graphic_start_x_line_edit.text = start_x_binding.get_target_value()
            graphic_start_y_line_edit.text = start_y_binding.get_target_value()
            graphic_start_row.add(graphic_start_x_line_edit)
            graphic_start_row.add_spacing(8)
            graphic_start_row.add(graphic_start_y_line_edit)
            graphic_start_row.add_stretch()
            graphic_end_row = self.ui.create_row_widget()
            graphic_end_row.add_spacing(20)
            graphic_end_row.add(self.ui.create_label_widget(_("End"), properties={"width": 40}))
            graphic_end_x_line_edit = self.ui.create_line_edit_widget(properties={"width": 60})
            graphic_end_y_line_edit = self.ui.create_line_edit_widget(properties={"width": 60})
            graphic_end_x_line_edit.on_editing_finished = lambda text: end_x_binding.update_source(text)
            graphic_end_y_line_edit.on_editing_finished = lambda text: end_y_binding.update_source(text)
            graphic_end_x_line_edit.text = end_x_binding.get_target_value()
            graphic_end_y_line_edit.text = end_y_binding.get_target_value()
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
            size_image = (image_size[0] * graphic.bounds[1][0], image_size[1] * graphic.bounds[1][1])
            origin_image = (size_image[0] * 0.5 + image_size[0] * graphic.bounds[0][0] - 0.5 * image_size[0],
            size_image[1] * 0.5 + image_size[1] * graphic.bounds[0][1] - 0.5 * image_size[1])
            origin_x_str = calibrations[1].convert_to_calibrated_value_str(origin_image[1])
            origin_y_str = calibrations[0].convert_to_calibrated_value_str(origin_image[0])
            size_x_str = calibrations[1].convert_to_calibrated_value_str(size_image[1])
            size_y_str = calibrations[0].convert_to_calibrated_value_str(size_image[0])
            # create the ui
            graphic_title_type_label.text = _("Rectangle")
            graphic_center_row = self.ui.create_row_widget()
            graphic_center_row.add_spacing(40)
            graphic_center_row.add(self.ui.create_label_widget("{0}, {1}".format(origin_x_str, origin_y_str)))
            graphic_center_row.add_stretch()
            graphic_size_row = self.ui.create_row_widget()
            graphic_size_row.add_spacing(40)
            graphic_size_row.add(self.ui.create_label_widget("{0} x {1}".format(size_x_str, size_y_str)))
            graphic_size_row.add_stretch()
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_center_row)
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_size_row)
            graphic_widget.add_spacing(4)
        if isinstance(graphic, Graphics.EllipseGraphic):
            # calculate values from ellipse graphic
            size_image = (image_size[0] * graphic.bounds[1][0], image_size[1] * graphic.bounds[1][1])
            origin_image = (size_image[0] * 0.5 + image_size[0] * graphic.bounds[0][0] - 0.5 * image_size[0],
            size_image[1] * 0.5 + image_size[1] * graphic.bounds[0][1] - 0.5 * image_size[1])
            origin_x_str = calibrations[1].convert_to_calibrated_value_str(origin_image[1])
            origin_y_str = calibrations[0].convert_to_calibrated_value_str(origin_image[0])
            size_x_str = calibrations[1].convert_to_calibrated_value_str(size_image[1])
            size_y_str = calibrations[0].convert_to_calibrated_value_str(size_image[0])
            # create the ui
            graphic_title_type_label.text = _("Ellipse")
            graphic_center_row = self.ui.create_row_widget()
            graphic_center_row.add_spacing(40)
            graphic_center_row.add(self.ui.create_label_widget("{0}, {1}".format(origin_x_str, origin_y_str)))
            graphic_center_row.add_stretch()
            graphic_size_row = self.ui.create_row_widget()
            graphic_size_row.add_spacing(40)
            graphic_size_row.add(self.ui.create_label_widget("{0} x {1}".format(size_x_str, size_y_str)))
            graphic_size_row.add_stretch()
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_center_row)
            graphic_widget.add_spacing(4)
            graphic_widget.add(graphic_size_row)
            graphic_widget.add_spacing(4)
        return graphic_widget

    # not thread safe
    def update(self):
        image_size = self.data_item_content_binding.spatial_shape
        calibrations = self.data_item_content_binding.calculated_calibrations
        graphics = self.data_item_content_binding.graphics
        if len(graphics) > 0:
            while self.graphic_sections.count() > 0:
                self.graphic_sections.remove(self.graphic_sections.count() - 1)
            while self.graphic_sections.count() < len(graphics):
                graphic_section_index = self.graphic_sections.count()
                self.graphic_sections.add(self.__create_graphic_widget(graphic_section_index, graphics[graphic_section_index], image_size, calibrations))
        else:
            while self.graphic_sections.count() > 0:
                self.graphic_sections.remove(self.graphic_sections.count() - 1)


class DataItemContentBinding(Storage.Broadcaster):

    """
        Data item properties binding is used to act as a buffer between
        a data item and a user interface element. The user interface element
        can listen to this binding and receive notification when a content
        item changes with the DataItem.DISPLAY item included in changes.
        The user interface element can also get/set properties on this binding
        as if it were the data item itself.
    """

    def __init__(self, data_item):
        super(DataItemContentBinding, self).__init__()
        self.__data_item = data_item
        self.__initialized = True
        # make sure we're listening to changes of the data item
        self.__data_item.add_listener(self)

    def close(self):
        # unlisten to data item
        self.__data_item.remove_listener(self)

    # this will typically happen on a thread
    def data_item_content_changed(self, data_item, changes):
        if any (k in changes for k in (DataItem.DISPLAY, )):
            self.notify_listeners("data_item_display_content_changed")

    def __getattr__(self, name):
        return getattr(self.__data_item, name)

    def __setattr__(self, name, value):
        # this test allows attributes to be set in the __init__ method
        if self.__dict__.has_key(name) or not self.__dict__.has_key('_DataItemContentBinding__initialized'):
            super(DataItemContentBinding, self).__setattr__(name, value)
        else:
            setattr(self.__data_item, name, value)


class DataItemInspector(object):

    def __init__(self, ui, data_item):
        self.ui = ui
        self.__data_item_content_binding = DataItemContentBinding(data_item)
        self.__data_item_binding_source = DataItem.DataItemBindingSource(data_item)

        self.__inspectors = list()
        # ui
        self.widget = self.ui.create_column_widget()
        self.widget.add_spacing(6)

        self.__inspectors.append(InfoInspector(self.ui, self.__data_item_content_binding))
        #self.__inspectors.append(ParamInspector(self.ui, self.__data_item_binding_source))
        self.__inspectors.append(CalibrationsInspector(self.ui, self.__data_item_content_binding))
        self.__inspectors.append(DisplayLimitsInspector(self.ui, self.__data_item_content_binding))
        self.__inspectors.append(GraphicsInspector(self.ui, self.__data_item_content_binding))

        for inspector in self.__inspectors:
            self.widget.add(inspector.widget)

    def close(self):
        # close inspectors
        for inspector in self.__inspectors:
            inspector.close()
        # close the data item content binding
        self.__data_item_content_binding.close()
        self.__data_item_binding_source.close()

    # update the values if needed
    def periodic(self):
        for inspector in self.__inspectors:
            inspector.periodic()
