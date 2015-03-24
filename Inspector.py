# standard libraries
import collections
import copy
import functools
import gettext
import logging
import operator

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import Calibration
from nion.swift.model import DataItem
from nion.swift.model import Graphics
from nion.swift.model import Operation
from nion.ui import Binding
from nion.ui import Converter
from nion.ui import Observable

_ = gettext.gettext


class InspectorPanel(Panel.Panel):
    """Inspect the current selection.

    The current selection will be a list of selection specifiers, which is itself a list of containers
    enclosing other containers or objects.
    """

    def __init__(self, document_controller, panel_id, properties):
        super(InspectorPanel, self).__init__(document_controller, panel_id, _("Inspector"))

        # the currently selected display
        self.__display_specifier = DataItem.DisplaySpecifier()

        self.__display_inspector = None
        self.request_focus = False

        # listen for selected display binding changes
        self.__display_binding = document_controller.create_selected_display_binding()
        self.__selected_display_binding_changed_event_listener = self.__display_binding.selected_display_binding_changed_event.listen(self.__selected_display_binding_changed)
        self.__set_display_specifier(DataItem.DisplaySpecifier())

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
        self.__selected_display_binding_changed_event_listener.close()
        self.__selected_display_binding_changed_event_listener = None
        # close the property controller. note: this will close and create
        # a new data item inspector; so it should go before the final
        # data item inspector close, which is below.
        self.__display_binding.close()
        self.__display_binding = None
        self.__set_display_specifier(DataItem.DisplaySpecifier())
        # close the data item inspector
        if self.__display_inspector:
            self.__display_inspector.close()
            self.__display_inspector = None
        self.document_controller.clear_task("update_display" + str(id(self)))
        # finish closing
        super(InspectorPanel, self).close()

    # close the old data item inspector, and create a new one
    # not thread safe.
    def __update_display_inspector(self):
        if self.__display_inspector:
            self.column.remove(self.__display_inspector.widget)
            self.__display_inspector.close()
            self.__display_inspector = None
        if self.__display_specifier.display:
            self.__display_inspector = DataItemInspector(self.ui, self.__display_specifier)
            self.column.add(self.__display_inspector.widget)

    # not thread safe
    def __set_display_specifier(self, display_specifier):
        if self.__display_specifier != display_specifier:
            self.__display_specifier = copy.copy(display_specifier)
            self.__update_display_inspector()
        if self.request_focus:
            if self.__display_inspector:
                self.__display_inspector._get_inspectors()[0].info_title_label.focused = True
                self.__display_inspector._get_inspectors()[0].info_title_label.select_all()
            self.request_focus = False

    # this message is received from the data item binding.
    # it is established using add_listener. when it is called
    # mark the data item as needing updating.
    # thread safe.
    def __selected_display_binding_changed(self, display_specifier):
        def update_display():
            self.__set_display_specifier(display_specifier)
        self.document_controller.add_task("update_display" + str(id(self)), update_display)


class InspectorSection(object):

    """
        Represent a section in the inspector. The section is composed of a
        title in bold and then content. Subclasses should use add_widget_to_content
        to add item to the content portion of the section.
    """

    def __init__(self, ui, section_title):
        self.ui = ui
        section_widget = self.ui.create_column_widget()
        section_title_row = self.ui.create_row_widget()
        #section_title_row.add(self.ui.create_label_widget(u"\u25B6", properties={"width": "20"}))
        section_title_row.add(self.ui.create_label_widget(section_title, properties={"stylesheet": "font-weight: bold"}))
        section_title_row.add_stretch()
        section_widget.add(section_title_row)
        section_content_row = self.ui.create_row_widget()
        self.__section_content_column = self.ui.create_column_widget()
        section_content_row.add_spacing(20)
        section_content_row.add(self.__section_content_column)
        section_widget.add(section_content_row)
        section_widget.add_spacing(4)
        self.widget = section_widget

    def close(self):
        pass

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
        self.info_title_label = self.ui.create_line_edit_widget()
        self.info_title_label.bind_text(Binding.PropertyBinding(data_item, "title"))
        self.info_section_title_row.add(self.info_title_label)
        self.info_section_title_row.add_spacing(8)
        # caption
        self.caption_row = self.ui.create_row_widget()

        self.caption_label_column = self.ui.create_column_widget()
        self.caption_label_column.add(self.ui.create_label_widget(_("Caption"), properties={"width": 60}))
        self.caption_label_column.add_stretch()

        self.caption_edit_stack = self.ui.create_stack_widget()

        self.caption_static_column = self.ui.create_column_widget()
        self.caption_static_text = self.ui.create_text_edit_widget(properties={"height": 60})
        self.caption_static_text.editable = False
        self.caption_static_text.bind_text(Binding.PropertyBinding(data_item, "caption"))
        self.caption_static_button_row = self.ui.create_row_widget()
        self.caption_static_edit_button = self.ui.create_push_button_widget(_("Edit"))
        def begin_caption_edit():
            self.caption_editable_text.text = data_item.caption
            self.caption_static_text.unbind_text()
            self.caption_edit_stack.set_current_index(1)
        self.caption_static_edit_button.on_clicked = begin_caption_edit
        self.caption_static_button_row.add(self.caption_static_edit_button)
        self.caption_static_button_row.add_stretch()
        self.caption_static_column.add(self.caption_static_text)
        self.caption_static_column.add(self.caption_static_button_row)
        self.caption_static_column.add_stretch()

        self.caption_editable_column = self.ui.create_column_widget()
        self.caption_editable_text = self.ui.create_text_edit_widget(properties={"height": 60})
        self.caption_editable_button_row = self.ui.create_row_widget()
        self.caption_editable_save_button = self.ui.create_push_button_widget(_("Save"))
        self.caption_editable_cancel_button = self.ui.create_push_button_widget(_("Cancel"))
        def end_caption_edit():
            self.caption_static_text.bind_text(Binding.PropertyBinding(data_item, "caption"))
            self.caption_edit_stack.set_current_index(0)
        def save_caption_edit():
            data_item.caption = self.caption_editable_text.text
            end_caption_edit()
        self.caption_editable_button_row.add(self.caption_editable_save_button)
        self.caption_editable_button_row.add(self.caption_editable_cancel_button)
        self.caption_editable_button_row.add_stretch()
        self.caption_editable_save_button.on_clicked = save_caption_edit
        self.caption_editable_cancel_button.on_clicked = end_caption_edit
        self.caption_editable_column.add(self.caption_editable_text)
        self.caption_editable_column.add(self.caption_editable_button_row)
        self.caption_editable_column.add_stretch()

        self.caption_edit_stack.add(self.caption_static_column)
        self.caption_edit_stack.add(self.caption_editable_column)

        self.caption_row.add(self.caption_label_column)
        self.caption_row.add(self.caption_edit_stack)
        self.caption_row.add_spacing(8)

        # flag
        self.flag_row = self.ui.create_row_widget()
        class FlaggedToIndexConverter(object):
            """
                Convert from flag index (-1, 0, 1) to chooser index.
            """
            def convert(self, value):
                return (2, 0, 1)[value + 1]
            def convert_back(self, value):
                return (0, 1, -1)[value]
        self.flag_chooser = self.ui.create_combo_box_widget()
        self.flag_chooser.items = [_("Unflagged"), _("Picked"), _("Rejected")]
        self.flag_chooser.bind_current_index(Binding.PropertyBinding(data_item, "flag", converter=FlaggedToIndexConverter()))
        self.flag_row.add(self.ui.create_label_widget(_("Flag"), properties={"width": 60}))
        self.flag_row.add(self.flag_chooser)
        self.flag_row.add_stretch()
        # rating
        self.rating_row = self.ui.create_row_widget()
        self.rating_chooser = self.ui.create_combo_box_widget()
        self.rating_chooser.items = [_("No Rating"), _("1 Star"), _("2 Star"), _("3 Star"), _("4 Star"), _("5 Star")]
        self.rating_chooser.bind_current_index(Binding.PropertyBinding(data_item, "rating"))
        self.rating_row.add(self.ui.create_label_widget(_("Rating"), properties={"width": 60}))
        self.rating_row.add(self.rating_chooser)
        self.rating_row.add_stretch()
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
        self.info_datetime_label.bind_text(Binding.PropertyBinding(data_item, "created_local_as_string"))
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
        self.add_widget_to_content(self.caption_row)
        #self.add_widget_to_content(self.flag_row)
        #self.add_widget_to_content(self.rating_row)
        self.add_widget_to_content(self.info_section_session_row)
        self.add_widget_to_content(self.info_section_datetime_row)
        self.add_widget_to_content(self.info_section_format_row)


class CalibrationPublisherToObservable(Observable.Observable):
    """Provides observable calibration object.

    Clients can get/set/observer offset, scale, and unit properties.

    Pass in a publisher that publishes DataAndCalibrations and a setter function. A typical publisher
    might be data_and_calibration_publisher.select(lambda x: x.dimensional_calibrations[0]).cached().
    The function setter will take a calibration argument. A typical function setter might be
    data_source.set_dimensional_calibration(0, calibration).
    """

    def __init__(self, publisher, setter_fn):
        super(CalibrationPublisherToObservable, self).__init__()
        self.__cached_value = Calibration.Calibration()
        self.__setter_fn = setter_fn
        def handle_next_calibration(calibration):
            if self.__cached_value is not None:
                if calibration.offset != self.__cached_value.offset:
                    self.notify_set_property("offset", calibration.offset)
                if calibration.scale != self.__cached_value.scale:
                    self.notify_set_property("scale", calibration.scale)
                if calibration.units != self.__cached_value.units:
                    self.notify_set_property("units", calibration.units)
            self.__cached_value = calibration
        subscriber = Observable.Subscriber(handle_next_calibration)
        self.__subscription = publisher.subscribex(subscriber)

    def close(self):
        self.__subscription.close()
        self.__cached_value = None
        self.__setter_fn = None

    @property
    def offset(self):
        return self.__cached_value.offset

    @offset.setter
    def offset(self, value):
        calibration = self.__cached_value
        calibration.offset = value
        self.__setter_fn(calibration)
        self.notify_set_property("offset", calibration.offset)

    @property
    def scale(self):
        return self.__cached_value.scale

    @scale.setter
    def scale(self, value):
        calibration = self.__cached_value
        calibration.scale = value
        self.__setter_fn(calibration)
        self.notify_set_property("scale", calibration.scale)

    @property
    def units(self):
        return self.__cached_value.units

    @units.setter
    def units(self, value):
        calibration = self.__cached_value
        calibration.units = value
        self.__setter_fn(calibration)
        self.notify_set_property("units", calibration.units)


class CalibrationsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement calibrations inspector.
    """

    def __init__(self, ui, data_item, buffered_data_source, display):
        super(CalibrationsInspectorSection, self).__init__(ui, _("Calibrations"))
        # get a data_and_calibration publisher
        data_and_calibration_publisher = buffered_data_source.get_data_and_calibration_publisher()
        # configure the bindings to dimension calibrations
        self.__calibrations = list()
        for index in range(len(buffered_data_source.dimensional_calibrations)):
            # select the indexed dimensional calibration and then cache the latest value
            def select_dimensional_calibration(index, data_and_calibration):
                # note that arguments are reversed from typical usage so that functools.partial works correctly
                return data_and_calibration.get_dimensional_calibration(index)
            calibration_publisher = data_and_calibration_publisher.select(functools.partial(select_dimensional_calibration, index)).cache()
            # then convert it to an observable so that we can bind to offset/scale/units and add it to calibrations list
            self.__calibrations.append(CalibrationPublisherToObservable(calibration_publisher, functools.partial(buffered_data_source.set_dimensional_calibration, index)))
        # ui. create the spatial calibrations list.
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        for index, spatial_calibration in enumerate(self.__calibrations):
            list_widget.insert_item(spatial_calibration, index)
        self.add_widget_to_content(list_widget)
        # create the intensity row
        calibration_publisher = data_and_calibration_publisher.select(operator.attrgetter("intensity_calibration")).cache()
        intensity_calibration = CalibrationPublisherToObservable(calibration_publisher, buffered_data_source.set_intensity_calibration)
        if intensity_calibration is not None:
            intensity_row = self.ui.create_row_widget()
            row_label = self.ui.create_label_widget(_("Intensity"), properties={"width": 60})
            offset_field = self.ui.create_line_edit_widget(properties={"width": 60})
            scale_field = self.ui.create_line_edit_widget(properties={"width": 60})
            units_field = self.ui.create_line_edit_widget(properties={"width": 60})
            float_point_4_converter = Converter.FloatToStringConverter(format="{0:.4f}")
            offset_field.bind_text(Binding.PropertyBinding(intensity_calibration, "offset", converter=float_point_4_converter))
            scale_field.bind_text(Binding.PropertyBinding(intensity_calibration, "scale", float_point_4_converter))
            units_field.bind_text(Binding.PropertyBinding(intensity_calibration, "units"))
            intensity_row.add(row_label)
            intensity_row.add_spacing(12)
            intensity_row.add(offset_field)
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

    def close(self):
        # close the bound calibrations
        for spatial_calibration in self.__calibrations:
            spatial_calibration.close()

    # not thread safe
    def __create_header_widget(self):
        header_row = self.ui.create_row_widget()
        axis_header_label = self.ui.create_label_widget("Axis", properties={"width": 60})
        offset_header_label = self.ui.create_label_widget(_("Offset"), properties={"width": 60})
        scale_header_label = self.ui.create_label_widget(_("Scale"), properties={"width": 60})
        units_header_label = self.ui.create_label_widget(_("Units"), properties={"width": 60})
        header_row.add(axis_header_label)
        header_row.add_spacing(12)
        header_row.add(offset_header_label)
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
        offset_field = self.ui.create_line_edit_widget(properties={"width": 60})
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
                index = self.__calibrations.index(value)
                if len(self.__calibrations) == 1:
                    return _("Channel")
                if len(self.__calibrations) == 2:
                    return (_("Y"), _("X"))[index]
                return str(index)
            def convert_back(self, str):
                raise NotImplementedError()
        # binding
        row_label.bind_text(Binding.ObjectBinding(calibration, converter=CalibrationToIndexStringConverter(self.__calibrations)))
        float_point_4_converter = Converter.FloatToStringConverter(format="{0:.4f}")
        offset_field.bind_text(Binding.PropertyBinding(calibration, "offset", converter=float_point_4_converter))
        scale_field.bind_text(Binding.PropertyBinding(calibration, "scale", float_point_4_converter))
        units_field.bind_text(Binding.PropertyBinding(calibration, "units"))
        # notice the binding of calibration_index below.
        calibration_row.add(row_label)
        calibration_row.add_spacing(12)
        calibration_row.add(offset_field)
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


class LinePlotInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, ui, display):
        super(LinePlotInspectorSection, self).__init__(ui, _("Line Plot"))

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

        float_point_2_none_converter = Converter.FloatToStringConverter(format="{0:.2f}", pass_none=True)

        self.display_limits_limit_row = self.ui.create_row_widget()
        self.display_limits_limit_low = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_high = self.ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_low.bind_text(Binding.PropertyBinding(display, "y_min", float_point_2_none_converter))
        self.display_limits_limit_high.bind_text(Binding.PropertyBinding(display, "y_max", float_point_2_none_converter))
        self.display_limits_limit_low.placeholder_text = _("Auto")
        self.display_limits_limit_high.placeholder_text = _("Auto")
        self.display_limits_limit_row.add(self.ui.create_label_widget(_("Display:"), properties={"width": 120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()

        self.channels_row = self.ui.create_row_widget()
        self.channels_left = self.ui.create_line_edit_widget(properties={"width": 80})
        self.channels_right = self.ui.create_line_edit_widget(properties={"width": 80})
        self.channels_left.bind_text(Binding.PropertyBinding(display, "left_channel", float_point_2_none_converter))
        self.channels_right.bind_text(Binding.PropertyBinding(display, "right_channel", float_point_2_none_converter))
        self.channels_left.placeholder_text = _("Auto")
        self.channels_right.placeholder_text = _("Auto")
        self.channels_row.add(self.ui.create_label_widget(_("Channels:"), properties={"width": 120}))
        self.channels_row.add(self.channels_left)
        self.channels_row.add_spacing(8)
        self.channels_row.add(self.channels_right)
        self.channels_row.add_stretch()

        self.add_widget_to_content(self.display_limits_range_row)
        self.add_widget_to_content(self.display_limits_limit_row)
        self.add_widget_to_content(self.channels_row)


class SliceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, ui, data_item, buffered_data_source, display):
        super(SliceInspectorSection, self).__init__(ui, _("Display"))

        slice_center_row_widget = self.ui.create_row_widget()
        slice_center_label_widget = self.ui.create_label_widget(_("Slice"))
        slice_center_line_edit_widget = self.ui.create_line_edit_widget()
        slice_center_slider_widget = self.ui.create_slider_widget()
        slice_center_slider_widget.maximum = buffered_data_source.dimensional_shape[0] - 1
        slice_center_slider_widget.bind_value(Binding.PropertyBinding(display, "slice_center"))
        slice_center_line_edit_widget.bind_text(Binding.PropertyBinding(display, "slice_center", converter=Converter.IntegerToStringConverter()))
        slice_center_row_widget.add(slice_center_label_widget)
        slice_center_row_widget.add_spacing(8)
        slice_center_row_widget.add(slice_center_slider_widget)
        slice_center_row_widget.add_spacing(8)
        slice_center_row_widget.add(slice_center_line_edit_widget)
        slice_center_row_widget.add_stretch()

        slice_width_row_widget = self.ui.create_row_widget()
        slice_width_label_widget = self.ui.create_label_widget(_("Width"))
        slice_width_line_edit_widget = self.ui.create_line_edit_widget()
        slice_width_slider_widget = self.ui.create_slider_widget()
        slice_width_slider_widget.maximum = buffered_data_source.dimensional_shape[0] - 1
        slice_width_slider_widget.bind_value(Binding.PropertyBinding(display, "slice_width"))
        slice_width_line_edit_widget.bind_text(Binding.PropertyBinding(display, "slice_width", converter=Converter.IntegerToStringConverter()))
        slice_width_row_widget.add(slice_width_label_widget)
        slice_width_row_widget.add_spacing(8)
        slice_width_row_widget.add(slice_width_slider_widget)
        slice_width_row_widget.add_spacing(8)
        slice_width_row_widget.add(slice_width_line_edit_widget)
        slice_width_row_widget.add_stretch()

        self.add_widget_to_content(slice_center_row_widget)
        self.add_widget_to_content(slice_width_row_widget)


class CalibratedValueFloatToStringConverter(object):
    """
        Converter object to convert from calibrated value to string and back.
    """
    def __init__(self, buffered_data_source, index, data_size):
        self.__buffered_data_source = buffered_data_source
        self.__index = index
        self.__data_size = data_size
    def convert(self, value):
        calibration = self.__buffered_data_source.dimensional_calibrations[self.__index]
        return calibration.convert_to_calibrated_value_str(self.__data_size * value)
    def convert_back(self, str):
        calibration = self.__buffered_data_source.dimensional_calibrations[self.__index]
        return calibration.convert_from_calibrated_value(Converter.FloatToStringConverter().convert_back(str)) / self.__data_size


class CalibratedSizeFloatToStringConverter(object):
    """
        Converter object to convert from calibrated size to string and back.
        """
    def __init__(self, buffered_data_source, index, data_size):
        self.__buffered_data_source = buffered_data_source
        self.__index = index
        self.__data_size = data_size
    def convert(self, size):
        calibration = self.__buffered_data_source.dimensional_calibrations[self.__index]
        return calibration.convert_to_calibrated_size_str(self.__data_size * size)
    def convert_back(self, str):
        calibration = self.__buffered_data_source.dimensional_calibrations[self.__index]
        return calibration.convert_from_calibrated_value(Converter.FloatToStringConverter().convert_back(str)) / self.__data_size


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
        self.__value_binding = None
        self.__display_calibrated_values_binding.close()
        self.__display_calibrated_values_binding = None
        super(CalibratedValueBinding, self).close()
    # set the model value from the target ui element text.
    def update_source(self, target_value):
        display_calibrated_values = self.__display_calibrated_values_binding.get_target_value()
        if display_calibrated_values:
            converted_value = self.converter.convert_back(target_value)
        else:
            converted_value = Converter.FloatToStringConverter().convert_back(target_value)
        self.__value_binding.update_source(converted_value)
    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self):
        display_calibrated_values = self.__display_calibrated_values_binding.get_target_value()
        value = self.__value_binding.get_target_value()
        return self.converter.convert(value) if display_calibrated_values else "{0:g}".format(value)


def make_point_type_inspector(ui, graphic_widget, display_specifier, image_size, graphic):
    def new_display_calibrated_values_binding():
        return Binding.PropertyBinding(display_specifier.display, "display_calibrated_values")
    # calculate values from rectangle type graphic
    x_converter = CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 1, image_size[1])
    y_converter = CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 0, image_size[0])
    position_x_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "position", 1), new_display_calibrated_values_binding(), x_converter)
    position_y_binding = CalibratedValueBinding(Binding.TuplePropertyBinding(graphic, "position", 0), new_display_calibrated_values_binding(), y_converter)
    # create the ui
    graphic_position_row = ui.create_row_widget()
    graphic_position_row.add_spacing(20)
    graphic_position_row.add(ui.create_label_widget(_("Position"), properties={"width": 40}))
    graphic_position_x_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_position_y_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_position_x_line_edit.bind_text(position_x_binding)
    graphic_position_y_line_edit.bind_text(position_y_binding)
    graphic_position_row.add(graphic_position_x_line_edit)
    graphic_position_row.add_spacing(8)
    graphic_position_row.add(graphic_position_y_line_edit)
    graphic_position_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_position_row)
    graphic_widget.add_spacing(4)


def make_line_type_inspector(ui, graphic_widget, display_specifier, image_size, graphic):
    def new_display_calibrated_values_binding():
        return Binding.PropertyBinding(display_specifier.display, "display_calibrated_values")
    # configure the bindings
    x_converter = CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 1, image_size[1])
    y_converter = CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 0, image_size[0])
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


def make_line_profile_inspector(ui, graphic_widget, display_specifier, image_size, graphic):
    def new_display_calibrated_values_binding():
        return Binding.PropertyBinding(display_specifier.display, "display_calibrated_values")
    make_line_type_inspector(ui, graphic_widget, display_specifier, image_size, graphic)
    # configure the bindings
    width_converter = CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 0, 1.0)
    width_binding = CalibratedValueBinding(Binding.PropertyBinding(graphic, "width"), new_display_calibrated_values_binding(), width_converter)
    # create the ui
    graphic_width_row = ui.create_row_widget()
    graphic_width_row.add_spacing(20)
    graphic_width_row.add(ui.create_label_widget(_("Width"), properties={"width": 40}))
    graphic_width_line_edit = ui.create_line_edit_widget(properties={"width": 80})
    graphic_width_line_edit.bind_text(width_binding)
    graphic_width_row.add(graphic_width_line_edit)
    graphic_width_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_width_row)
    graphic_widget.add_spacing(4)


def make_rectangle_type_inspector(ui, graphic_widget, display_specifier, image_size, graphic):
    def new_display_calibrated_values_binding():
        return Binding.PropertyBinding(display_specifier.display, "display_calibrated_values")
    # calculate values from rectangle type graphic
    x_converter = CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 1, image_size[1])
    y_converter = CalibratedValueFloatToStringConverter(display_specifier.buffered_data_source, 0, image_size[0])
    width_converter = CalibratedSizeFloatToStringConverter(display_specifier.buffered_data_source, 1, image_size[1])
    height_converter = CalibratedSizeFloatToStringConverter(display_specifier.buffered_data_source, 0, image_size[0])
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

    def __init__(self, ui, data_item, buffered_data_source, display):
        super(GraphicsInspectorSection, self).__init__(ui, _("Graphics"))
        self.__image_size = buffered_data_source.dimensional_shape
        self.__calibrations = buffered_data_source.dimensional_calibrations
        self.__graphics = display.drawn_graphics
        self.__display_specifier = DataItem.DisplaySpecifier(data_item, buffered_data_source, display)
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
        # NOTE: it is not valid to access self.__graphics here. graphic may or may not be in that list due to threading.
        # graphic_section_index = self.__graphics.index(graphic)
        image_size = self.__image_size
        graphic_title_row = self.ui.create_row_widget()
        # graphic_title_index_label = self.ui.create_label_widget(str(graphic_section_index), properties={"width": 20})
        graphic_title_type_label = self.ui.create_label_widget()
        # graphic_title_row.add(graphic_title_index_label)
        graphic_title_row.add(graphic_title_type_label)
        graphic_title_row.add_stretch()
        graphic_widget = self.ui.create_column_widget()
        graphic_widget.add(graphic_title_row)
        if isinstance(graphic, Graphics.PointGraphic):
            graphic_title_type_label.text = _("Point")
            make_point_type_inspector(self.ui, graphic_widget, self.__display_specifier, image_size, graphic)
        if isinstance(graphic, Graphics.LineGraphic):
            graphic_title_type_label.text = _("Line")
            make_line_type_inspector(self.ui, graphic_widget, self.__display_specifier, image_size, graphic)
        if isinstance(graphic, Graphics.LineProfileGraphic):
            graphic_title_type_label.text = _("Line Profile")
            make_line_profile_inspector(self.ui, graphic_widget, self.__display_specifier, image_size, graphic)
        if isinstance(graphic, Graphics.RectangleGraphic):
            graphic_title_type_label.text = _("Rectangle")
            make_rectangle_type_inspector(self.ui, graphic_widget, self.__display_specifier, image_size, graphic)
        if isinstance(graphic, Graphics.EllipseGraphic):
            graphic_title_type_label.text = _("Ellipse")
            make_rectangle_type_inspector(self.ui, graphic_widget, self.__display_specifier, image_size, graphic)
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
        # ui. create the spatial operations list.
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), None, header_for_empty_list_widget)
        list_widget.bind_items(Binding.ListBinding(data_item, "ordered_operations"))
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
            elif type == "boolean-checkbox":
                row_widget = self.ui.create_row_widget()
                check_box_widget = self.ui.create_check_box_widget(name)
                check_box_widget.bind_check_state(Operation.OperationPropertyBinding(operation, property, converter=Converter.CheckedToCheckStateConverter()))
                row_widget.add(check_box_widget)
                row_widget.add_stretch()
                operation_widget.add_spacing(4)
                operation_widget.add(row_widget)
            elif type == "slice-center-field":
                row_widget = self.ui.create_row_widget()
                label_widget = self.ui.create_label_widget(name)
                line_edit_widget = self.ui.create_line_edit_widget()
                slider_widget = self.ui.create_slider_widget()
                slider_widget.maximum = operation.data_sources[0].dimensional_shape[0] - 1
                slider_widget.bind_value(Operation.OperationPropertyBinding(operation, property))
                line_edit_widget.bind_text(Operation.SliceOperationPropertyBinding(operation, property, converter=Converter.IntegerToStringConverter()))
                row_widget.add(label_widget)
                row_widget.add_spacing(8)
                row_widget.add(slider_widget)
                row_widget.add_spacing(8)
                row_widget.add(line_edit_widget)
                row_widget.add_stretch()
                operation_widget.add_spacing(4)
                operation_widget.add(row_widget)
            elif type == "slice-width-field":
                row_widget = self.ui.create_row_widget()
                label_widget = self.ui.create_label_widget(name)
                line_edit_widget = self.ui.create_line_edit_widget()
                slider_widget = self.ui.create_slider_widget()
                slider_widget.minimum = 1
                slider_widget.maximum = operation.data_sources[0].dimensional_shape[0]
                slider_widget.bind_value(Operation.OperationPropertyBinding(operation, property))
                line_edit_widget.bind_text(Operation.SliceOperationPropertyBinding(operation, property, converter=Converter.IntegerToStringConverter()))
                row_widget.add(label_widget)
                row_widget.add_spacing(8)
                row_widget.add(slider_widget)
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

    def __init__(self, ui, display_specifier):
        self.ui = ui

        data_item, buffered_data_source, display = display_specifier.data_item, display_specifier.buffered_data_source, display_specifier.display

        self.__inspectors = list()
        content_widget = self.ui.create_column_widget()
        content_widget.add_spacing(6)

        self.__inspectors.append(InfoInspectorSection(self.ui, data_item))
        self.__inspectors.append(CalibrationsInspectorSection(self.ui, data_item, buffered_data_source, display))
        if buffered_data_source and buffered_data_source.is_data_1d:
            self.__inspectors.append(LinePlotInspectorSection(self.ui, display))
        elif buffered_data_source and buffered_data_source.is_data_2d:
            self.__inspectors.append(DisplayLimitsInspectorSection(self.ui, display))
            self.__inspectors.append(GraphicsInspectorSection(self.ui, data_item, buffered_data_source, display))
        elif buffered_data_source and buffered_data_source.is_data_3d:
            self.__inspectors.append(DisplayLimitsInspectorSection(self.ui, display))
            self.__inspectors.append(GraphicsInspectorSection(self.ui, data_item, buffered_data_source, display))
            self.__inspectors.append(SliceInspectorSection(self.ui, data_item, buffered_data_source, display))
        self.__inspectors.append(OperationsInspectorSection(self.ui, data_item))

        for inspector in self.__inspectors:
            content_widget.add(inspector.widget)

        content_widget.add_stretch()

        self.widget = content_widget

    def close(self):
        # close inspectors
        for inspector in self.__inspectors:
            inspector.close()
        self.__inspectors = None

    def _get_inspectors(self):
        """ Return a copy of the list of inspectors. """
        return copy.copy(self.__inspectors)
