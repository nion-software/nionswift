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

    def periodic(self):
        super(InfoInspector, self).periodic()
        self.info_title_label.periodic()  # widget
        self.info_session_label.periodic()  # widget
        self.info_datetime_label.periodic()  # widget
        self.info_format_label.periodic()  # widget


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

    def periodic(self):
        super(ParamInspector, self).periodic()
        self.param_field.periodic()  # widget
        self.param_slider.periodic()  # widget


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
        self.header_and_content_section = self.ui.create_column_widget()
        self.header_section = self.ui.create_column_widget()
        self.content_section = self.ui.create_column_widget(properties={"spacing": 4, "margin-top": 4})
        self.header_and_content_section.add(self.header_section)
        self.header_and_content_section.add(self.content_section)
        self.add_widget_to_content(self.header_and_content_section)
        self.display_calibrations_row = self.ui.create_row_widget()
        self.display_calibrations_checkbox = self.ui.create_check_box_button_widget(_("Displayed"))
        self.display_calibrations_checkbox.on_state_changed = lambda state: self.display_calibrations_changed(state)
        self.display_calibrations_row.add(self.display_calibrations_checkbox)
        self.display_calibrations_row.add_stretch()
        self.add_widget_to_content(self.display_calibrations_row)
        self.periodic_widgets = list()
        # initial update
        self.update()

    def close(self):
        self.data_item_content_binding.remove_listener(self)
        super(CalibrationsInspector, self).close()

    # this gets called from the data_item_content_binding
    # thread safe
    def data_item_display_content_changed(self):
        self.add_task("update", lambda: self.update())

    # not thead safe
    def create_header(self):
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
    def create_header_for_empty_list(self):
        header_for_empty_list_row = self.ui.create_row_widget()
        header_for_empty_list_row.add(self.ui.create_label_widget("None", properties={"stylesheet": "font: italic"}))
        return header_for_empty_list_row

    # not thread safe
    def create_content_for_list_item(self, calibrations, calibration_index):
        calibration = calibrations[calibration_index]
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
                return str(calibrations.index(value))
            def convert_back(self, str):
                raise NotImplementedError()
        # binding
        row_label.bind_text(UserInterfaceUtility.ObjectBinding(calibration, converter=CalibrationToIndexStringConverter(calibrations)))
        origin_field.bind_text(UserInterfaceUtility.PropertyBinding(calibration, "origin", converter=UserInterfaceUtility.FloatToStringConverter(format="{0:.2f}")))
        scale_field.bind_text(UserInterfaceUtility.PropertyBinding(calibration, "scale", converter=UserInterfaceUtility.FloatToStringConverter(format="{0:.2f}")))
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
        return calibration_row, (row_label, origin_field, scale_field, units_field)

    # not thread safe
    def update(self):
        self.display_calibrations_checkbox.check_state = "checked" if self.data_item_content_binding.display_calibrated_values else "unchecked"
        # calibrations
        # first match the number of rows to the number of calibrations
        # then populate
        calibrations = self.data_item_content_binding.calibrations
        if len(calibrations) > 0:
            # remove all rows in the header section
            while self.header_section.count() > 0:
                self.header_section.remove(self.header_section.count() - 1)
            # create the header row
            header_row = self.create_header()
            # create header subsection, so it can be deleted easily
            header_subsection = self.ui.create_column_widget()
            header_subsection.add(header_row)
            header_subsection.add_spacing(2)
            # add subsection to section
            self.header_section.add(header_subsection)
        else:
            # remove all rows in the header section
            while self.header_section.count() > 0:
                self.header_section.remove(self.header_section.count() - 1)
            # create header subsection, so it can be deleted easily
            header_subsection = self.ui.create_column_widget()
            header_subsection.add_spacing(2)
            header_for_empty_list_row = self.create_header_for_empty_list()
            header_subsection.add(header_for_empty_list_row)
            self.header_section.add(header_subsection)
        # create a row for each calibration
        while self.content_section.count() < len(calibrations):
            calibration_index = self.content_section.count()
            calibration_row, periodic_items = self.create_content_for_list_item(calibrations, calibration_index)
            self.periodic_widgets.append(periodic_items)
            self.content_section.add(calibration_row)
        # remove extra rows in the content section
        while self.content_section.count() > len(calibrations):
            self.content_section.remove(len(calibrations) - 1)
            del self.periodic_widgets[-1]

    def display_calibrations_changed(self, state):
        self.data_item_content_binding.display_calibrated_values = state == "checked"
        self.update()  # clean up displayed values

    def periodic(self):
        super(CalibrationsInspector, self).periodic()
        for row_label, origin_field, scale_field, units_field in self.periodic_widgets:
            row_label.periodic()
            origin_field.periodic()
            scale_field.periodic()
            units_field.periodic()


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

        # bindings

        self.__data_item_content_binding = DataItemContentBinding(data_item)
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
        self.__data_item_binding.close()
        self.__data_item_binding_source.close()

    # update the values if needed
    def periodic(self):
        for inspector in self.__inspectors:
            inspector.periodic()
        self.__data_item_binding.periodic()
