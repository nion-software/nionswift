# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import copy
import functools
import gettext
import math
import operator
import uuid

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.swift import DataItemThumbnailWidget
from nion.swift import Panel
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.ui import Widgets
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import Observable
from nion.utils import Stream

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
        self.__data_item_will_be_removed_event_listener = None
        self.__selected_data_item_binding = document_controller.create_selected_data_item_binding()
        self.__data_item_changed_event_listener = self.__selected_data_item_binding.data_item_changed_event.listen(self.__data_item_changed)
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
        self.__data_item_changed_event_listener.close()
        self.__data_item_changed_event_listener = None
        # close the property controller. note: this will close and create
        # a new data item inspector; so it should go before the final
        # data item inspector close, which is below.
        self.__selected_data_item_binding.close()
        self.__selected_data_item_binding = None
        self.__set_display_specifier(DataItem.DisplaySpecifier())
        # close the data item inspector
        if self.__display_inspector:
            self.__display_inspector.close()
            self.__display_inspector = None
        self.document_controller.clear_task("update_display" + str(id(self)))
        self.document_controller.clear_task("update_display_inspector" + str(id(self)))
        # finish closing
        super(InspectorPanel, self).close()

    def _get_inspector_sections(self):
        return self.__display_inspector._get_inspectors() if self.__display_inspector else None

    # close the old data item inspector, and create a new one
    # not thread safe.
    def __update_display_inspector(self):
        self.column.remove_all()
        if self.__display_inspector:
            if self.__display_type_changed_listener:
                self.__display_type_changed_listener.close()
                self.__display_type_changed_listener = None
            if self.__display_graphic_selection_changed_event_listener:
                self.__display_graphic_selection_changed_event_listener.close()
                self.__display_graphic_selection_changed_event_listener = None
            self.__display_inspector.close()
            self.__display_inspector = None

        self.__display_inspector = DataItemInspector(self.ui, self.document_controller.document_model, self.__display_specifier)

        # this ugly item below, which adds a listener for a changing selection and then calls
        # back to this very method, is here to make sure the inspectors get updated when the
        # user changes the selection.
        if self.__display_specifier.display:
            display = self.__display_specifier.display

            def display_graphic_selection_changed(graphic_selection):
                # not really a recursive call; only delayed
                # this may come in on a thread (superscan probe position connection closing). delay even more.
                self.document_controller.add_task("update_display_inspector" + str(id(self)), self.__update_display_inspector)

            def display_type_changed():
                # not really a recursive call; only delayed
                # this may come in on a thread (superscan probe position connection closing). delay even more.
                self.document_controller.add_task("update_display_inspector" + str(id(self)), self.__update_display_inspector)

            self.__display_type_changed_listener = display.display_type_changed_event.listen(display_type_changed)
            self.__display_graphic_selection_changed_event_listener = display.display_graphic_selection_changed_event.listen(display_graphic_selection_changed)
        else:
            self.__display_type_changed_listener = None
            self.__display_graphic_selection_changed_event_listener = None

        self.column.add(self.__display_inspector.widget)
        stretch_column = self.ui.create_column_widget()
        stretch_column.add_stretch()
        self.column.add(stretch_column)

    # not thread safe
    def __set_display_specifier(self, display_specifier):
        if self.__display_specifier != display_specifier:
            self.__display_specifier = copy.copy(display_specifier)
            self.__update_display_inspector()
        if self.request_focus:
            if self.__display_inspector:
                self.__display_inspector.focus_default()
            self.request_focus = False

    # this message is received from the data item binding.
    # mark the data item as needing updating.
    # thread safe.
    def __data_item_changed(self, data_item):
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)
        def data_item_will_be_removed(data_item):
            self.document_controller.clear_task("update_display" + str(id(self)))
            self.document_controller.clear_task("update_display_inspector" + str(id(self)))
            if self.__data_item_will_be_removed_event_listener:
                self.__data_item_will_be_removed_event_listener.close()
                self.__data_item_will_be_removed_event_listener = None
        def update_display():
            self.__set_display_specifier(display_specifier)
            if self.__data_item_will_be_removed_event_listener:
                self.__data_item_will_be_removed_event_listener.close()
                self.__data_item_will_be_removed_event_listener = None
        # handle the case where the selected display binding changes and then the item is removed before periodic has
        # had a chance to update display. in that case, when periodic finally gets called, we need to make sure that
        # update display has been canceled somehow. this barely passes the smell test.
        if display_specifier.data_item:
            if self.__data_item_will_be_removed_event_listener:
                self.__data_item_will_be_removed_event_listener.close()
                self.__data_item_will_be_removed_event_listener = None
            self.__data_item_will_be_removed_event_listener = self.document_controller.document_model.data_item_will_be_removed_event.listen(data_item_will_be_removed)
        self.document_controller.add_task("update_display" + str(id(self)), update_display)


class InspectorSection:
    """A class to manage creation of a widget representing a twist down inspector section.

    Represent a section in the inspector. The section is composed of a title in bold and then content. Subclasses should
    use add_widget_to_content to add items to the content portion of the section, then call finish_widget_content to
    properly handle the stretch at the bottom of the section.

    The content of the section will be associated with a subset of the content of a display specifier. The section is
    responsible for watching for mutations to that subset of content and updating appropriately.
    """

    def __init__(self, ui, section_id, section_title):
        self.ui = ui  # for use in subclasses
        self.__section_content_column = self.ui.create_column_widget()
        self.widget = Widgets.SectionWidget(ui, section_title, self.__section_content_column, "inspector/" + section_id + "/open")

    def close(self):
        pass

    def add_widget_to_content(self, widget):
        """Subclasses should call this to add content in the section's top level column."""
        self.__section_content_column.add_spacing(4)
        self.__section_content_column.add(widget)

    def finish_widget_content(self):
        """Subclasses should all this after calls to add_widget_content."""
        pass

    @property
    def _section_content_for_test(self):
        return self.__section_content_column


class InfoInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement info inspector.
    """

    def __init__(self, ui, data_item):
        super(InfoInspectorSection, self).__init__(ui, "info", _("Info"))
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
        class FlaggedToIndexConverter:
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
        self.finish_widget_content()


class SessionInspectorSection(InspectorSection):

    def __init__(self, ui, data_item):
        super().__init__(ui, "session", _("Session"))

        field_descriptions = [
            [_("Site"), _("Site Description"), "site"],
            [_("Instrument"), _("Instrument Description"), "instrument"],
            [_("Task"), _("Task Description"), "task"],
            [_("Microscopist"), _("Microscopist Name(s)"), "microscopist"],
            [_("Sample"), _("Sample Description"), "sample"],
            [_("Sample Area"), _("Sample Area Description"), "sample_area"],
        ]

        widget = self.ui.create_column_widget()

        def line_edit_changed(line_edit_widget, field_id, text):
            session_metadata = data_item.session_metadata
            session_metadata[field_id] = str(text)
            data_item.session_metadata = session_metadata
            line_edit_widget.select_all()

        field_line_edit_widget_map = dict()

        first_field = True
        for field_description in field_descriptions:
            title, placeholder, field_id = field_description
            row = self.ui.create_row_widget()
            row.add(self.ui.create_label_widget(title, properties={"width": 100}))
            line_edit_widget = self.ui.create_line_edit_widget()
            line_edit_widget.placeholder_text = placeholder
            line_edit_widget.on_editing_finished = functools.partial(line_edit_changed, line_edit_widget, field_id)
            field_line_edit_widget_map[field_id] = line_edit_widget
            row.add(line_edit_widget)
            if not first_field:
                widget.add_spacing(4)
            first_field = False
            widget.add(row)

        def update_fields(fields):
            for field_id, line_edit_widget in field_line_edit_widget_map.items():
                line_edit_widget.text = fields.get(field_id)

        def fields_changed(key, value):
            if key == 'session_metadata':
                widget.add_task("update_fields", functools.partial(update_fields, value))
        self.__property_changed_listener = data_item.property_changed_event.listen(fields_changed)

        update_fields(data_item.session_metadata)

        self.add_widget_to_content(widget)
        self.finish_widget_content()

    def close(self):
        self.__property_changed_listener.close()
        self.__property_changed_listener = None


class CalibrationStreamToObservable(Observable.Observable):
    """Provides observable calibration object.

    Clients can get/set/observer offset, scale, and unit properties.

    Pass in a calibration stream and a setter function.

    The function setter will take a calibration argument. A typical function setter might be
    data_source.set_dimensional_calibration(0, calibration).
    """

    def __init__(self, calibration_stream, setter_fn):
        super().__init__()
        self.__calibration_stream = calibration_stream
        self.__cached_value = Calibration.Calibration()
        self.__setter_fn = setter_fn
        def update_calibration(calibration):
            if self.__cached_value is not None:
                if calibration.offset != self.__cached_value.offset:
                    self.notify_set_property("offset", calibration.offset)
                if calibration.scale != self.__cached_value.scale:
                    self.notify_set_property("scale", calibration.scale)
                if calibration.units != self.__cached_value.units:
                    self.notify_set_property("units", calibration.units)
            self.__cached_value = calibration
        self.__listener = calibration_stream.value_stream.listen(update_calibration)
        update_calibration(calibration_stream.value)

    def close(self):
        self.__calibration_stream = None
        self.__listener.close()
        self.__listener = None
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


def make_calibration_style_chooser(ui, display):
    display_calibration_style_options = ((_("Calibrated"), "calibrated"), (_("Pixels (Top Left)"), "pixels-top-left"), (_("Pixels (Center)"), "pixels-center"), (_("Relative (Top Left)"), "relative-top-left"), (_("Relative (Center)"), "relative-center"))
    display_calibration_style_reverse_map = {"calibrated": 0, "pixels-top-left": 1, "pixels-center": 2, "relative-top-left": 3, "relative-center": 4}

    class CalibrationStyleIndexConverter:
        """
            Convert from flag index (-1, 0, 1) to chooser index.
        """
        def convert(self, value):
            return display_calibration_style_reverse_map.get(value, 0)
        def convert_back(self, value):
            if value >= 0 and value < len(display_calibration_style_options):
                return display_calibration_style_options[value][1]
            else:
                return "calibrated"

    display_calibration_style_chooser = ui.create_combo_box_widget(items=display_calibration_style_options, item_getter=operator.itemgetter(0))
    display_calibration_style_chooser.bind_current_index(Binding.PropertyBinding(display, "dimensional_calibration_style", converter=CalibrationStyleIndexConverter(), fallback=0))

    return display_calibration_style_chooser


class CalibrationsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement calibrations inspector.
    """

    def __init__(self, ui, data_item, buffered_data_source, display):
        super(CalibrationsInspectorSection, self).__init__(ui, "calibrations", _("Calibrations"))
        # get streams
        dimensional_calibrations_stream = Stream.PropertyStream(buffered_data_source, "dimensional_calibrations")
        self.__intensity_calibration_stream = Stream.PropertyStream(buffered_data_source, "intensity_calibration").add_ref()
        # configure the bindings to dimension calibrations
        self.__calibrations = list()
        self.__dimensional_calibration_streams = list()
        for index in range(len(buffered_data_source.dimensional_calibrations)):
            # select the indexed dimensional calibration and form a new stream
            dimensional_calibration_stream = Stream.MapStream(dimensional_calibrations_stream, operator.itemgetter(index))
            # then convert it to an observable so that we can bind to offset/scale/units and add it to calibrations list
            self.__calibrations.append(CalibrationStreamToObservable(dimensional_calibration_stream, functools.partial(buffered_data_source.set_dimensional_calibration, index)))
            self.__dimensional_calibration_streams.append(dimensional_calibration_stream.add_ref())
        # ui. create the spatial calibrations list.
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        for index, spatial_calibration in enumerate(self.__calibrations):
            list_widget.insert_item(spatial_calibration, index)
        self.add_widget_to_content(list_widget)
        # create the intensity row
        intensity_calibration = CalibrationStreamToObservable(self.__intensity_calibration_stream, buffered_data_source.set_intensity_calibration)
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
        self.display_calibrations_row.add(self.ui.create_label_widget(_("Display"), properties={"width": 60}))
        self.display_calibrations_row.add(make_calibration_style_chooser(self.ui, display))
        self.display_calibrations_row.add_stretch()
        self.add_widget_to_content(self.display_calibrations_row)
        self.finish_widget_content()

    def close(self):
        # close the bound calibrations
        for spatial_calibration in self.__calibrations:
            spatial_calibration.close()
        self.__intensity_calibration_stream.remove_ref()
        self.__intensity_calibration_stream = None
        for dimensional_calibration_stream in self.__dimensional_calibration_streams:
            dimensional_calibration_stream.remove_ref()
        self.__dimensional_calibration_streams = None

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
        if len(self.__calibrations) == 1:
            row_label_text = _("Channel")
        elif len(self.__calibrations) == 2:
            row_label_text = (_("Y"), _("X"))[self.__calibrations.index(calibration)]
        else:
            row_label_text = str(self.__calibrations.index(calibration))
        row_label.text = row_label_text
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


def make_display_type_chooser(ui, display):
    display_type_row = ui.create_row_widget()
    display_type_items = ((_("Default"), None), (_("Line Plot"), "line_plot"), (_("Image"), "image"))
    display_type_reverse_map = {None: 0, "line_plot": 1, "image": 2}
    display_type_chooser = ui.create_combo_box_widget(items=display_type_items, item_getter=operator.itemgetter(0))
    display_type_chooser.on_current_item_changed = lambda item: setattr(display, "display_type", item[1])
    display_type_chooser.current_item = display_type_items[display_type_reverse_map.get(display.display_type, 0)]
    display_type_row.add(ui.create_label_widget(_("Display Type:"), properties={"width": 120}))
    display_type_row.add(display_type_chooser)
    display_type_row.add_stretch()
    return display_type_row


def make_color_map_chooser(ui, display):
    color_map_row = ui.create_row_widget()
    color_map_options = ((_("Default"), None), (_("Grayscale"), "grayscale"), (_("Magma"), "magma"), (_("HSV"), "hsv"), (_("Viridis"), "viridis"), (_("Plasma"), "plasma"), (_("Ice"), "ice"))
    color_map_reverse_map = {None: 0, "grayscale": 1, "magma": 2, "hsv": 3, "viridis": 4, "plasma": 5, "ice": 6}
    color_map_chooser = ui.create_combo_box_widget(items=color_map_options, item_getter=operator.itemgetter(0))
    color_map_chooser.on_current_item_changed = lambda item: setattr(display, "color_map_id", item[1])
    color_map_chooser.current_item = color_map_options[color_map_reverse_map.get(display.color_map_id, 0)]
    color_map_row.add(ui.create_label_widget(_("Color Map:"), properties={"width": 120}))
    color_map_row.add(color_map_chooser)
    color_map_row.add_stretch()
    return color_map_row


class ImageDisplayInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, ui, display):
        super().__init__(ui, "display-limits", _("Display"))

        # display type
        display_type_row = make_display_type_chooser(ui, display)

        # color map
        color_map_row = make_color_map_chooser(ui, display)

        # configure the display limit editor
        self.display_limits_range_row = ui.create_row_widget()
        self.display_limits_range_low = ui.create_label_widget(properties={"width": 80})
        self.display_limits_range_high = ui.create_label_widget(properties={"width": 80})
        float_point_2_converter = Converter.FloatToStringConverter(format="{0:.2f}")
        self.display_limits_range_low.bind_text(Binding.TuplePropertyBinding(display, "data_range", 0, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_high.bind_text(Binding.TuplePropertyBinding(display, "data_range", 1, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_range_row.add(ui.create_label_widget(_("Data Range:"), properties={"width": 120}))
        self.display_limits_range_row.add(self.display_limits_range_low)
        self.display_limits_range_row.add_spacing(8)
        self.display_limits_range_row.add(self.display_limits_range_high)
        self.display_limits_range_row.add_stretch()
        self.display_limits_limit_row = ui.create_row_widget()
        self.display_limits_limit_low = ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_high = ui.create_line_edit_widget(properties={"width": 80})
        self.display_limits_limit_low.bind_text(Binding.TuplePropertyBinding(display, "display_range", 0, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_limit_high.bind_text(Binding.TuplePropertyBinding(display, "display_range", 1, float_point_2_converter, fallback=_("N/A")))
        self.display_limits_limit_row.add(ui.create_label_widget(_("Display Limits:"), properties={"width": 120}))
        self.display_limits_limit_row.add(self.display_limits_limit_low)
        self.display_limits_limit_row.add_spacing(8)
        self.display_limits_limit_row.add(self.display_limits_limit_high)
        self.display_limits_limit_row.add_stretch()

        self.add_widget_to_content(display_type_row)
        self.add_widget_to_content(color_map_row)
        self.add_widget_to_content(self.display_limits_range_row)
        self.add_widget_to_content(self.display_limits_limit_row)

        self.finish_widget_content()


class LinePlotDisplayInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement display limits inspector.
    """

    def __init__(self, ui, display):
        super().__init__(ui, "line-plot", _("Display"))

        # display type
        display_type_row = make_display_type_chooser(ui, display)

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

        class LogCheckedToCheckStateConverter:
            """ Convert between bool and checked/unchecked strings. """

            def convert(self, value):
                """ Convert bool to checked or unchecked string """
                return "checked" if value == "log" else "unchecked"

            def convert_back(self, value):
                """ Convert checked or unchecked string to bool """
                return "log" if value == "checked" else "linear"

        self.style_row = self.ui.create_row_widget()
        self.style_y_log = self.ui.create_check_box_widget(_("Log Scale (Y)"))
        self.style_y_log.bind_check_state(Binding.PropertyBinding(display, "y_style", converter=LogCheckedToCheckStateConverter()))
        self.style_row.add(self.style_y_log)
        self.style_row.add_stretch()

        self.add_widget_to_content(display_type_row)
        self.add_widget_to_content(self.display_limits_range_row)
        self.add_widget_to_content(self.display_limits_limit_row)
        self.add_widget_to_content(self.channels_row)
        self.add_widget_to_content(self.style_row)
        self.finish_widget_content()


class SequenceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, ui, data_item, buffered_data_source, display):
        super().__init__(ui, "sequence", _("Sequence"))

        sequence_index_row_widget = self.ui.create_row_widget()
        sequence_index_label_widget = self.ui.create_label_widget(_("Index"))
        sequence_index_line_edit_widget = self.ui.create_line_edit_widget()
        sequence_index_slider_widget = self.ui.create_slider_widget()
        sequence_index_slider_widget.maximum = buffered_data_source.dimensional_shape[0] - 1  # sequence_index
        sequence_index_slider_widget.bind_value(Binding.PropertyBinding(display, "sequence_index"))
        sequence_index_line_edit_widget.bind_text(Binding.PropertyBinding(display, "sequence_index", converter=Converter.IntegerToStringConverter()))
        sequence_index_row_widget.add(sequence_index_label_widget)
        sequence_index_row_widget.add_spacing(8)
        sequence_index_row_widget.add(sequence_index_slider_widget)
        sequence_index_row_widget.add_spacing(8)
        sequence_index_row_widget.add(sequence_index_line_edit_widget)
        sequence_index_row_widget.add_stretch()

        self.add_widget_to_content(sequence_index_row_widget)
        self.finish_widget_content()

        # for testing
        self._sequence_index_slider_widget = sequence_index_slider_widget
        self._sequence_index_line_edit_widget = sequence_index_line_edit_widget


class CollectionIndexInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, ui, buffered_data_source, display):
        super().__init__(ui, "collection-index", _("Index"))

        column_widget = self.ui.create_column_widget()
        collection_index_base = 1 if buffered_data_source.is_sequence else 0
        for index in range(buffered_data_source.collection_dimension_count):
            index_row_widget = self.ui.create_row_widget()
            index_label_widget = self.ui.create_label_widget("{}: {}".format(_("Index"), index))
            index_line_edit_widget = self.ui.create_line_edit_widget()
            index_slider_widget = self.ui.create_slider_widget()
            index_slider_widget.maximum = buffered_data_source.dimensional_shape[collection_index_base + index] - 1
            index_slider_widget.bind_value(Binding.TuplePropertyBinding(display, "collection_index", index))
            index_line_edit_widget.bind_text(Binding.TuplePropertyBinding(display, "collection_index", index, converter=Converter.IntegerToStringConverter()))
            index_row_widget.add(index_label_widget)
            index_row_widget.add_spacing(8)
            index_row_widget.add(index_slider_widget)
            index_row_widget.add_spacing(8)
            index_row_widget.add(index_line_edit_widget)
            index_row_widget.add_stretch()
            column_widget.add(index_row_widget)

        self.add_widget_to_content(column_widget)
        self.finish_widget_content()

        # for testing
        self._column_widget = column_widget


class SliceInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement slice inspector.
    """

    def __init__(self, ui, data_item, buffered_data_source, display):
        super().__init__(ui, "slice", _("Slice"))

        slice_center_row_widget = self.ui.create_row_widget()
        slice_center_label_widget = self.ui.create_label_widget(_("Slice"))
        slice_center_line_edit_widget = self.ui.create_line_edit_widget()
        slice_center_slider_widget = self.ui.create_slider_widget()
        slice_center_slider_widget.maximum = buffered_data_source.dimensional_shape[-1] - 1  # signal_index
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
        slice_width_slider_widget.maximum = buffered_data_source.dimensional_shape[-1] - 1  # signal_index
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
        self.finish_widget_content()

        # for testing
        self._slice_center_slider_widget = slice_center_slider_widget
        self._slice_width_slider_widget = slice_width_slider_widget
        self._slice_center_line_edit_widget = slice_center_line_edit_widget
        self._slice_width_line_edit_widget = slice_width_line_edit_widget


class RadianToDegreeStringConverter:
    """
        Converter object to convert from radian value to degree string and back.
    """
    def convert(self, value):
        return "{0:.4f}°".format(math.degrees(value))
    def convert_back(self, str):
        return math.radians(Converter.FloatToStringConverter().convert_back(str))


class CalibratedValueFloatToStringConverter:
    """
        Converter object to convert from calibrated value to string and back.
    """
    def __init__(self, buffered_data_source, display, index):
        self.__buffered_data_source = buffered_data_source
        self.__display = display
        self.__index = index
    def convert_calibrated_value_to_str(self, calibrated_value):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        return calibration.convert_calibrated_value_to_str(calibrated_value)
    def convert_to_calibrated_value(self, value):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        data_size = self.__buffered_data_source.dimensional_shape[self.__index]
        return calibration.convert_to_calibrated_value(data_size * value)
    def convert_from_calibrated_value(self, calibrated_value):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        data_size = self.__buffered_data_source.dimensional_shape[self.__index]
        return calibration.convert_from_calibrated_value(calibrated_value) / data_size
    def convert(self, value):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        data_size = self.__buffered_data_source.dimensional_shape[self.__index]
        return calibration.convert_to_calibrated_value_str(data_size * value, value_range=(0, data_size), samples=data_size)
    def convert_back(self, str):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        data_size = self.__buffered_data_source.dimensional_shape[self.__index]
        return calibration.convert_from_calibrated_value(Converter.FloatToStringConverter().convert_back(str)) / data_size


class CalibratedSizeFloatToStringConverter:
    """
        Converter object to convert from calibrated size to string and back.
        """
    def __init__(self, buffered_data_source, display, index, factor=1.0):
        self.__buffered_data_source = buffered_data_source
        self.__display = display
        self.__index = index
        self.__factor = factor
    def convert_calibrated_value_to_str(self, calibrated_value):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        return calibration.convert_calibrated_value_to_str(calibrated_value)
    def convert_to_calibrated_value(self, size):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        data_size = self.__buffered_data_source.dimensional_shape[self.__index]
        return calibration.convert_to_calibrated_size(data_size * size * self.__factor)
    def convert(self, size):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        data_size = self.__buffered_data_source.dimensional_shape[self.__index]
        return calibration.convert_to_calibrated_size_str(data_size * size * self.__factor, value_range=(0, data_size), samples=data_size)
    def convert_back(self, str):
        calibration = self.__display.displayed_dimensional_calibrations[self.__index]
        data_size = self.__buffered_data_source.dimensional_shape[self.__index]
        return calibration.convert_from_calibrated_value(Converter.FloatToStringConverter().convert_back(str)) / data_size / self.__factor


class CalibratedBinding(Binding.Binding):
    def __init__(self, buffered_data_source, display, value_binding, converter):
        super().__init__(None, converter)
        self.__value_binding = value_binding
        def update_target(value):
            self.update_target_direct(self.get_target_value())
        self.__value_binding.target_setter = update_target
        self.__metadata_changed_event_listener = buffered_data_source.metadata_changed_event.listen(lambda: update_target(None))
        def calibrations_changed(k, v):
            if k == "displayed_dimensional_calibrations":
                update_target(v)
        self.__calibrations_changed_event_listener = display.property_changed_event.listen(calibrations_changed)
    def close(self):
        self.__metadata_changed_event_listener.close()
        self.__metadata_changed_event_listener = None
        self.__value_binding.close()
        self.__value_binding = None
        self.__calibrations_changed_event_listener.close()
        self.__calibrations_changed_event_listener = None
        super().close()
    # set the model value from the target ui element text.
    def update_source(self, target_value):
        converted_value = self.converter.convert_back(target_value)
        self.__value_binding.update_source(converted_value)
    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self):
        value = self.__value_binding.get_target_value()
        return self.converter.convert(value)


class CalibratedValueBinding(CalibratedBinding):
    def __init__(self, buffered_data_source, index, display, value_binding):
        converter = CalibratedValueFloatToStringConverter(buffered_data_source, display, index)
        super().__init__(buffered_data_source, display, value_binding, converter)


class CalibratedSizeBinding(CalibratedBinding):
    def __init__(self, buffered_data_source, index, display, value_binding):
        converter = CalibratedSizeFloatToStringConverter(buffered_data_source, display, index)
        super().__init__(buffered_data_source, display, value_binding, converter)


class CalibratedWidthBinding(CalibratedBinding):
    def __init__(self, buffered_data_source, display, value_binding):
        factor = 1.0 / buffered_data_source.dimensional_shape[0]
        converter = CalibratedSizeFloatToStringConverter(buffered_data_source, display, 0, factor)  # width is stored in pixels. argh.
        super().__init__(buffered_data_source, display, value_binding, converter)


class CalibratedLengthBinding(Binding.Binding):
    def __init__(self, buffered_data_source, display, start_binding, end_binding):
        super().__init__(None, None)
        self.__x_converter = CalibratedValueFloatToStringConverter(buffered_data_source, display, 1)
        self.__y_converter = CalibratedValueFloatToStringConverter(buffered_data_source, display, 0)
        self.__size_converter = CalibratedSizeFloatToStringConverter(buffered_data_source, display, 0)
        self.__start_binding = start_binding
        self.__end_binding = end_binding
        def update_target(value):
            self.update_target_direct(self.get_target_value())
        self.__start_binding.target_setter = update_target
        self.__end_binding.target_setter = update_target
        self.__metadata_changed_event_listener = buffered_data_source.metadata_changed_event.listen(lambda: update_target(None))
        def calibrations_changed(k, v):
            if k == "displayed_dimensional_calibrations":
                update_target(v)
        self.__calibrations_changed_event_listener = display.property_changed_event.listen(calibrations_changed)
    def close(self):
        self.__metadata_changed_event_listener.close()
        self.__metadata_changed_event_listener = None
        self.__start_binding.close()
        self.__start_binding = None
        self.__end_binding.close()
        self.__end_binding = None
        self.__calibrations_changed_event_listener.close()
        self.__calibrations_changed_event_listener = None
        super().close()
    # set the model value from the target ui element text.
    def update_source(self, target_value):
        start = self.__start_binding.get_target_value()
        end = self.__end_binding.get_target_value()
        calibrated_start = Geometry.FloatPoint(y=self.__y_converter.convert_to_calibrated_value(start[0]), x=self.__x_converter.convert_to_calibrated_value(start[1]))
        calibrated_end = Geometry.FloatPoint(y=self.__y_converter.convert_to_calibrated_value(end[0]), x=self.__x_converter.convert_to_calibrated_value(end[1]))
        delta = calibrated_end - calibrated_start
        angle = -math.atan2(delta.y, delta.x)
        new_calibrated_end = calibrated_start + target_value * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))
        end = Geometry.FloatPoint(y=self.__y_converter.convert_from_calibrated_value(new_calibrated_end.y), x=self.__x_converter.convert_from_calibrated_value(new_calibrated_end.x))
        self.__end_binding.update_source(end)
    # get the value from the model and return it as a string suitable for the target ui element.
    # in this binding, it combines the two source bindings into one.
    def get_target_value(self):
        start = self.__start_binding.get_target_value()
        end = self.__end_binding.get_target_value()
        calibrated_dy = self.__y_converter.convert_to_calibrated_value(end[0]) - self.__y_converter.convert_to_calibrated_value(start[0])
        calibrated_dx = self.__x_converter.convert_to_calibrated_value(end[1]) - self.__x_converter.convert_to_calibrated_value(start[1])
        calibrated_value = math.sqrt(calibrated_dx * calibrated_dx + calibrated_dy * calibrated_dy)
        return self.__size_converter.convert_calibrated_value_to_str(calibrated_value)


def make_point_type_inspector(ui, graphic_widget, display_specifier, graphic):
    # create the ui
    graphic_position_row = ui.create_row_widget()
    graphic_position_row.add_spacing(20)
    graphic_position_x_row = ui.create_row_widget()
    graphic_position_x_row.add(ui.create_label_widget(_("X"), properties={"width": 26}))
    graphic_position_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_position_x_row.add(graphic_position_x_line_edit)
    graphic_position_y_row = ui.create_row_widget()
    graphic_position_y_row.add(ui.create_label_widget(_("Y"), properties={"width": 26}))
    graphic_position_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_position_y_row.add(graphic_position_y_line_edit)
    graphic_position_row.add(graphic_position_x_row)
    graphic_position_row.add_spacing(8)
    graphic_position_row.add(graphic_position_y_row)
    graphic_position_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_position_row)
    graphic_widget.add_spacing(4)

    image_size = display_specifier.buffered_data_source.dimensional_shape
    if (len(image_size) > 1):
        # calculate values from rectangle type graphic
        # signal_index
        position_x_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 1, display_specifier.display, Binding.TuplePropertyBinding(graphic, "position", 1))
        position_y_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 0, display_specifier.display, Binding.TuplePropertyBinding(graphic, "position", 0))
        graphic_position_x_line_edit.bind_text(position_x_binding)
        graphic_position_y_line_edit.bind_text(position_y_binding)
    else:
        graphic_position_x_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "position", 1))
        graphic_position_y_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "position", 0))


def make_line_type_inspector(ui, graphic_widget, display_specifier, graphic):
    # create the ui
    graphic_start_row = ui.create_row_widget()
    graphic_start_row.add_spacing(20)
    graphic_start_x_row = ui.create_row_widget()
    graphic_start_x_row.add(ui.create_label_widget(_("X0"), properties={"width": 26}))
    graphic_start_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_start_x_row.add(graphic_start_x_line_edit)
    graphic_start_y_row = ui.create_row_widget()
    graphic_start_y_row.add(ui.create_label_widget(_("Y0"), properties={"width": 26}))
    graphic_start_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_start_y_row.add(graphic_start_y_line_edit)
    graphic_start_row.add(graphic_start_x_row)
    graphic_start_row.add_spacing(8)
    graphic_start_row.add(graphic_start_y_row)
    graphic_start_row.add_stretch()
    graphic_end_row = ui.create_row_widget()
    graphic_end_row.add_spacing(20)
    graphic_end_x_row = ui.create_row_widget()
    graphic_end_x_row.add(ui.create_label_widget(_("X1"), properties={"width": 26}))
    graphic_end_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_end_x_row.add(graphic_end_x_line_edit)
    graphic_end_y_row = ui.create_row_widget()
    graphic_end_y_row.add(ui.create_label_widget(_("Y1"), properties={"width": 26}))
    graphic_end_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_end_y_row.add(graphic_end_y_line_edit)
    graphic_end_row.add(graphic_end_x_row)
    graphic_end_row.add_spacing(8)
    graphic_end_row.add(graphic_end_y_row)
    graphic_end_row.add_stretch()
    graphic_param_row = ui.create_row_widget()
    graphic_param_row.add_spacing(20)
    graphic_param_l_row = ui.create_row_widget()
    graphic_param_l_row.add(ui.create_label_widget(_("L"), properties={"width": 26}))
    graphic_param_l_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_param_l_row.add(graphic_param_l_line_edit)
    graphic_param_a_row = ui.create_row_widget()
    graphic_param_a_row.add(ui.create_label_widget(_("A"), properties={"width": 26}))
    graphic_param_a_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_param_a_row.add(graphic_param_a_line_edit)
    graphic_param_row.add(graphic_param_l_row)
    graphic_param_row.add_spacing(8)
    graphic_param_row.add(graphic_param_a_row)
    graphic_param_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_start_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_end_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_param_row)
    graphic_widget.add_spacing(4)

    image_size = display_specifier.buffered_data_source.dimensional_shape
    if len(image_size) > 1:
        # configure the bindings
        # signal_index
        start_x_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 1, display_specifier.display, Binding.TuplePropertyBinding(graphic, "start", 1))
        start_y_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 0, display_specifier.display, Binding.TuplePropertyBinding(graphic, "start", 0))
        end_x_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 1, display_specifier.display, Binding.TuplePropertyBinding(graphic, "end", 1))
        end_y_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 0, display_specifier.display, Binding.TuplePropertyBinding(graphic, "end", 0))
        length_binding = CalibratedLengthBinding(display_specifier.buffered_data_source, display_specifier.display, Binding.PropertyBinding(graphic, "start"), Binding.PropertyBinding(graphic, "end"))
        angle_binding = Binding.PropertyBinding(graphic, "angle", RadianToDegreeStringConverter())
        graphic_start_x_line_edit.bind_text(start_x_binding)
        graphic_start_y_line_edit.bind_text(start_y_binding)
        graphic_end_x_line_edit.bind_text(end_x_binding)
        graphic_end_y_line_edit.bind_text(end_y_binding)
        graphic_param_l_line_edit.bind_text(length_binding)
        graphic_param_a_line_edit.bind_text(angle_binding)
    else:
        graphic_start_x_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "start", 1))
        graphic_start_y_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "start", 0))
        graphic_end_x_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "end", 1))
        graphic_end_y_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "end", 0))
        graphic_param_l_line_edit.bind_text(Binding.PropertyBinding(graphic, "length"))
        graphic_param_a_line_edit.bind_text(Binding.PropertyBinding(graphic, "angle", RadianToDegreeStringConverter()))


def make_line_profile_inspector(ui, graphic_widget, display_specifier, graphic):
    make_line_type_inspector(ui, graphic_widget, display_specifier, graphic)
    # configure the bindings
    width_binding = CalibratedWidthBinding(display_specifier.buffered_data_source, display_specifier.display, Binding.PropertyBinding(graphic, "width"))
    # create the ui
    graphic_width_row = ui.create_row_widget()
    graphic_width_row.add_spacing(20)
    graphic_width_row.add(ui.create_label_widget(_("Width"), properties={"width": 52}))
    graphic_width_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_width_line_edit.bind_text(width_binding)
    graphic_width_row.add(graphic_width_line_edit)
    graphic_width_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_width_row)
    graphic_widget.add_spacing(4)


def make_rectangle_type_inspector(ui, graphic_widget, display_specifier, graphic):
    # create the ui
    graphic_center_row = ui.create_row_widget()
    graphic_center_row.add_spacing(20)
    graphic_center_x_row = ui.create_row_widget()
    graphic_center_x_row.add(ui.create_label_widget(_("X"), properties={"width": 26}))
    graphic_center_x_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_x_row.add(graphic_center_x_line_edit)
    graphic_center_y_row = ui.create_row_widget()
    graphic_center_y_row.add(ui.create_label_widget(_("Y"), properties={"width": 26}))
    graphic_center_y_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_y_row.add(graphic_center_y_line_edit)
    graphic_center_row.add(graphic_center_x_row)
    graphic_center_row.add_spacing(8)
    graphic_center_row.add(graphic_center_y_row)
    graphic_center_row.add_stretch()
    graphic_size_row = ui.create_row_widget()
    graphic_size_row.add_spacing(20)
    graphic_center_w_row = ui.create_row_widget()
    graphic_center_w_row.add(ui.create_label_widget(_("W"), properties={"width": 26}))
    graphic_size_width_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_w_row.add(graphic_size_width_line_edit)
    graphic_center_h_row = ui.create_row_widget()
    graphic_center_h_row.add(ui.create_label_widget(_("H"), properties={"width": 26}))
    graphic_size_height_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_h_row.add(graphic_size_height_line_edit)
    graphic_size_row.add(graphic_center_w_row)
    graphic_size_row.add_spacing(8)
    graphic_size_row.add(graphic_center_h_row)
    graphic_size_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_center_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_size_row)
    graphic_widget.add_spacing(4)

    # calculate values from rectangle type graphic
    image_size = display_specifier.buffered_data_source.dimensional_shape
    if len(image_size) > 1:
        # signal_index
        center_x_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 1, display_specifier.display, Binding.TuplePropertyBinding(graphic, "center", 1))
        center_y_binding = CalibratedValueBinding(display_specifier.buffered_data_source, 0, display_specifier.display, Binding.TuplePropertyBinding(graphic, "center", 0))
        size_width_binding = CalibratedSizeBinding(display_specifier.buffered_data_source, 1, display_specifier.display, Binding.TuplePropertyBinding(graphic, "size", 1))
        size_height_binding = CalibratedSizeBinding(display_specifier.buffered_data_source, 0, display_specifier.display, Binding.TuplePropertyBinding(graphic, "size", 0))
        graphic_center_x_line_edit.bind_text(center_x_binding)
        graphic_center_y_line_edit.bind_text(center_y_binding)
        graphic_size_width_line_edit.bind_text(size_width_binding)
        graphic_size_height_line_edit.bind_text(size_height_binding)
    else:
        graphic_center_x_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "center", 1))
        graphic_center_y_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "center", 0))
        graphic_size_width_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "size", 1))
        graphic_size_height_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "size", 0))

def make_wedge_type_inspector(ui, graphic_widget, display_specifier, graphic):
    # create the ui
    graphic_center_start_angle_row = ui.create_row_widget()
    graphic_center_start_angle_row.add_spacing(20)
    graphic_center_start_angle_row.add(ui.create_label_widget(_("Start Angle"), properties={"width": 60}))
    graphic_center_start_angle_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_start_angle_row.add(graphic_center_start_angle_line_edit)
    graphic_center_start_angle_row.add_stretch()
    graphic_center_end_angle_row = ui.create_row_widget()
    graphic_center_end_angle_row.add_spacing(20)
    graphic_center_end_angle_row.add(ui.create_label_widget(_("End Angle"), properties={"width": 60}))
    graphic_center_angle_measure_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_center_end_angle_row.add(graphic_center_angle_measure_line_edit)
    graphic_center_end_angle_row.add_stretch()
    graphic_widget.add(graphic_center_start_angle_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_center_end_angle_row)
    graphic_widget.add_spacing(4)

    graphic_center_start_angle_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "angle_interval", 0, RadianToDegreeStringConverter()))
    graphic_center_angle_measure_line_edit.bind_text(Binding.TuplePropertyBinding(graphic, "angle_interval", 1, RadianToDegreeStringConverter()))


def make_interval_type_inspector(ui, graphic_widget, display_specifier, graphic):
    # configure the bindings
    start_binding = CalibratedValueBinding(display_specifier.buffered_data_source, -1, display_specifier.display, Binding.PropertyBinding(graphic, "start"))
    end_binding = CalibratedValueBinding(display_specifier.buffered_data_source, -1, display_specifier.display, Binding.PropertyBinding(graphic, "end"))
    # create the ui
    graphic_start_row = ui.create_row_widget()
    graphic_start_row.add_spacing(20)
    graphic_start_row.add(ui.create_label_widget(_("Start"), properties={"width": 52}))
    graphic_start_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_start_line_edit.bind_text(start_binding)
    graphic_start_row.add(graphic_start_line_edit)
    graphic_start_row.add_stretch()
    graphic_end_row = ui.create_row_widget()
    graphic_end_row.add_spacing(20)
    graphic_end_row.add(ui.create_label_widget(_("End"), properties={"width": 52}))
    graphic_end_line_edit = ui.create_line_edit_widget(properties={"width": 98})
    graphic_end_line_edit.bind_text(end_binding)
    graphic_end_row.add(graphic_end_line_edit)
    graphic_end_row.add_stretch()
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_start_row)
    graphic_widget.add_spacing(4)
    graphic_widget.add(graphic_end_row)
    graphic_widget.add_spacing(4)


class GraphicsInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement graphics inspector.
        """

    def __init__(self, ui, data_item, buffered_data_source, display, selected_only=False):
        super(GraphicsInspectorSection, self).__init__(ui, "graphics", _("Graphics"))
        self.__image_size = buffered_data_source.dimensional_shape
        self.__calibrations = buffered_data_source.dimensional_calibrations
        self.__graphics = display.graphics
        self.__display_specifier = DataItem.DisplaySpecifier(data_item, buffered_data_source, display)
        # ui
        header_widget = self.__create_header_widget()
        header_for_empty_list_widget = self.__create_header_for_empty_list_widget()
        # create the widgets for each graphic
        # TODO: do not use dynamic list object in graphics inspector; the dynamic aspect is not utilized.
        list_widget = self.ui.create_new_list_widget(lambda item: self.__create_list_item_widget(item), header_widget, header_for_empty_list_widget)
        list_widget.bind_items(Binding.ListBinding(display, "selected_graphics" if selected_only else "graphics"))
        self.add_widget_to_content(list_widget)
        # create the display calibrations check box row
        display_calibrations_row = self.ui.create_row_widget()
        display_calibrations_row.add(self.ui.create_label_widget(_("Display"), properties={"width": 60}))
        display_calibrations_row.add(make_calibration_style_chooser(self.ui, display))
        display_calibrations_row.add_stretch()
        self.add_widget_to_content(display_calibrations_row)
        self.finish_widget_content()

    def __create_header_widget(self):
        return self.ui.create_row_widget()

    def __create_header_for_empty_list_widget(self):
        return self.ui.create_row_widget()

    # not thread safe
    def __create_list_item_widget(self, graphic):
        # NOTE: it is not valid to access self.__graphics here. graphic may or may not be in that list due to threading.
        # graphic_section_index = self.__graphics.index(graphic)
        image_size = self.__image_size
        graphic_widget = self.ui.create_column_widget()
        # create the title row
        title_row = self.ui.create_row_widget()
        graphic_type_label = self.ui.create_label_widget(properties={"width": 100})
        label_line_edit = self.ui.create_line_edit_widget()
        label_line_edit.placeholder_text = _("None")
        label_line_edit.bind_text(Binding.PropertyBinding(graphic, "label"))
        title_row.add(graphic_type_label)
        title_row.add_spacing(8)
        title_row.add(label_line_edit)
        title_row.add_stretch()
        graphic_widget.add(title_row)
        graphic_widget.add_spacing(4)
        # create the graphic specific widget
        if isinstance(graphic, Graphics.PointGraphic):
            graphic_type_label.text = _("Point")
            make_point_type_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        elif isinstance(graphic, Graphics.LineProfileGraphic):
            graphic_type_label.text = _("Line Profile")
            make_line_profile_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        elif isinstance(graphic, Graphics.LineGraphic):
            graphic_type_label.text = _("Line")
            make_line_type_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        elif isinstance(graphic, Graphics.RectangleGraphic):
            graphic_type_label.text = _("Rectangle")
            make_rectangle_type_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        elif isinstance(graphic, Graphics.EllipseGraphic):
            graphic_type_label.text = _("Ellipse")
            make_rectangle_type_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        elif isinstance(graphic, Graphics.IntervalGraphic):
            graphic_type_label.text = _("Interval")
            make_interval_type_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        elif isinstance(graphic, Graphics.SpotGraphic):
            graphic_type_label.text = _("Spot")
            make_rectangle_type_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        elif isinstance(graphic, Graphics.WedgeGraphic):
            graphic_type_label.text = _("Wedge")
            make_wedge_type_inspector(self.ui, graphic_widget, self.__display_specifier, graphic)
        column = self.ui.create_column_widget()
        column.add_spacing(4)
        column.add(graphic_widget)
        return column


class ComputationInspectorSection(InspectorSection):

    """
        Subclass InspectorSection to implement operations inspector.
    """

    def __init__(self, ui, document_model: DocumentModel.DocumentModel, data_item: DataItem.DataItem, buffered_data_source: DataItem.BufferedDataSource):
        super(ComputationInspectorSection, self).__init__(ui, "computation", _("Computation"))
        computation = buffered_data_source.computation
        self.__widget_wrappers = list()
        if computation:
            label_row = self.ui.create_row_widget()
            label_widget = self.ui.create_label_widget()
            label_widget.bind_text(Binding.PropertyBinding(computation, "label"))
            label_row.add(label_widget)
            label_row.add_stretch()

            column = self.ui.create_column_widget()

            stretch_column = self.ui.create_column_widget()
            stretch_column.add_stretch()

            self.add_widget_to_content(label_row)
            self.add_widget_to_content(column)
            self.add_widget_to_content(stretch_column)

            def variable_inserted(index: int, variable: Symbolic.ComputationVariable) -> None:
                # boolean (label)
                # integer, slider (label, minimum, maximum)
                # float, slider (label, minimum, maximum)
                # integer, field (label, minimum, maximum)
                # float, field (label, minimum, maximum, significant digits)
                # complex, fields (label, significant digits)
                # float, angle
                # color, control
                # choices, combo box
                # point, region
                # vector, region
                # interval, region
                # rectangle, region
                # string, field
                # float, distance
                # float, duration (units)
                # image

                class WidgetWrapper:
                    def __init__(self, widget, closeables=[]):
                        self.widget = widget
                        self.__closeables = copy.copy(closeables)
                    def close(self):
                        for closeable in self.__closeables:
                            closeable.close()

                def make_checkbox(variable):
                    column = self.ui.create_column_widget()
                    row = self.ui.create_row_widget()
                    check_box_widget = self.ui.create_check_box_widget(variable.display_label)
                    check_box_widget.bind_checked(Binding.PropertyBinding(variable, "value"))
                    row.add(check_box_widget)
                    row.add_stretch()
                    column.add(row)
                    column.add_spacing(4)
                    return WidgetWrapper(column)

                def make_slider_int(variable, converter):
                    column = self.ui.create_column_widget()
                    row = self.ui.create_row_widget()
                    label_widget = self.ui.create_label_widget(variable.display_label, properties={"width": 80})
                    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
                    slider_widget = self.ui.create_slider_widget()
                    slider_widget.minimum = variable.value_min
                    slider_widget.maximum = variable.value_max
                    slider_widget.bind_value(Binding.PropertyBinding(variable, "value"))
                    line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 60})
                    line_edit_widget.bind_text(Binding.PropertyBinding(variable, "value", converter=converter))
                    row.add(label_widget)
                    row.add_spacing(8)
                    row.add(slider_widget)
                    row.add_spacing(8)
                    row.add(line_edit_widget)
                    row.add_spacing(8)
                    column.add(row)
                    column.add_spacing(4)
                    return WidgetWrapper(column)

                def make_slider_float(variable, converter):
                    column = self.ui.create_column_widget()
                    row = self.ui.create_row_widget()
                    label_widget = self.ui.create_label_widget(variable.display_label, properties={"width": 80})
                    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
                    f_converter = Converter.FloatToScaledIntegerConverter(1000, variable.value_min, variable.value_max)
                    slider_widget = self.ui.create_slider_widget()
                    slider_widget.minimum = 0
                    slider_widget.maximum = 1000
                    slider_widget.bind_value(Binding.PropertyBinding(variable, "value", converter=f_converter))
                    line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 60})
                    line_edit_widget.bind_text(Binding.PropertyBinding(variable, "value", converter=converter))
                    row.add(label_widget)
                    row.add_spacing(8)
                    row.add(slider_widget)
                    row.add_spacing(8)
                    row.add(line_edit_widget)
                    row.add_spacing(8)
                    column.add(row)
                    column.add_spacing(4)
                    return WidgetWrapper(column)

                def make_field(variable, converter):
                    column = self.ui.create_column_widget()
                    row = self.ui.create_row_widget()
                    label_widget = self.ui.create_label_widget(variable.display_label, properties={"width": 80})
                    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
                    line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 60})
                    line_edit_widget.bind_text(Binding.PropertyBinding(variable, "value", converter=converter))
                    row.add(label_widget)
                    row.add_spacing(8)
                    row.add(line_edit_widget)
                    row.add_stretch()
                    column.add(row)
                    column.add_spacing(4)
                    return WidgetWrapper(column)

                def make_image_chooser(variable):
                    column = self.ui.create_column_widget()
                    row = self.ui.create_row_widget()
                    label_column = self.ui.create_column_widget()
                    label_widget = self.ui.create_label_widget(variable.display_label, properties={"width": 80})
                    label_widget.bind_text(Binding.PropertyBinding(variable, "display_label"))
                    label_column.add(label_widget)
                    label_column.add_stretch()
                    row.add(label_column)
                    row.add_spacing(8)
                    property_name_ref = [None]
                    base_variable_specifier = copy.copy(variable.specifier)
                    property_name_ref[0] = base_variable_specifier.pop("property", None)
                    bound_data_item = document_model.resolve_object_specifier(base_variable_specifier)
                    data_item = bound_data_item.data_item if bound_data_item else None

                    def data_item_drop(data_item_uuid):
                        data_item = document_model.get_data_item_by_key(data_item_uuid)
                        variable_specifier = document_model.get_object_specifier(data_item)
                        if property_name_ref[0]:
                            variable_specifier["property"] = property_name_ref[0]
                        variable.specifier = variable_specifier

                    def data_item_delete():
                        variable_specifier = {"type": "data_item", "version": 1, "uuid": str(uuid.uuid4())}
                        if property_name_ref[0]:
                            variable_specifier["property"] = property_name_ref[0]
                        variable.specifier = variable_specifier

                    data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(document_model.dispatch_task, ui, data_item)
                    data_item_chooser_widget = DataItemThumbnailWidget.DataItemThumbnailWidget(self.ui,
                                                                                               data_item_thumbnail_source,
                                                                                               Geometry.IntSize(80, 80))

                    def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
                        # use this convoluted base object for drag so that it doesn't disappear after the drag.
                        column.root_container.widget.drag(mime_data, thumbnail, hot_spot_x, hot_spot_y)

                    data_item_chooser_widget.on_drag = thumbnail_widget_drag
                    data_item_chooser_widget.on_data_item_drop = data_item_drop
                    data_item_chooser_widget.on_data_item_delete = data_item_delete

                    def property_changed(key, value):
                        if key == "specifier":
                            base_variable_specifier = copy.copy(variable.specifier)
                            property_name_ref[0] = base_variable_specifier.pop("property", None)
                            bound_data_item = document_model.resolve_object_specifier(base_variable_specifier)
                            data_item = bound_data_item.data_item if bound_data_item else None
                            data_item_thumbnail_source.set_data_item(data_item)

                    property_changed_listener = variable.property_changed_event.listen(property_changed)
                    row.add(data_item_chooser_widget)
                    row.add_stretch()
                    column.add(row)
                    column.add_spacing(4)
                    return WidgetWrapper(column, [property_changed_listener])

                def make_widget_from_variable(variable):
                    if variable.variable_type == "boolean":
                        return make_checkbox(variable)
                    elif variable.variable_type == "integral" and (True or variable.control_type == "slider") and variable.has_range:
                        return make_slider_int(variable, Converter.IntegerToStringConverter())
                    elif variable.variable_type == "integral":
                        return make_field(variable, Converter.IntegerToStringConverter())
                    elif variable.variable_type == "real" and (True or variable.control_type == "slider") and variable.has_range:
                        return make_slider_float(variable, Converter.FloatToStringConverter())
                    elif variable.variable_type == "real":
                        return make_field(variable, Converter.FloatToStringConverter())
                    elif variable.variable_type in ("data_item", "data", "display_data"):
                        return make_image_chooser(variable)
                    elif variable.variable_type == "region":
                        return WidgetWrapper(self.ui.create_row_widget())
                    else:
                        return WidgetWrapper(self.ui.create_row_widget())

                widget_wrapper = make_widget_from_variable(variable)
                self.__widget_wrappers.insert(index, widget_wrapper)
                column.insert(widget_wrapper.widget, index)

            def variable_removed(index: int, variable: Symbolic.ComputationVariable) -> None:
                column.remove(column.children[index])
                self.__widget_wrappers[index].close()
                del self.__widget_wrappers[index]

            self.__computation_variable_inserted_event_listener = computation.variable_inserted_event.listen(variable_inserted)
            self.__computation_variable_removed_event_listener = computation.variable_removed_event.listen(variable_removed)

            for index, variable in enumerate(computation.variables):
                variable_inserted(index, variable)
        else:
            none_widget = self.ui.create_row_widget()
            none_widget.add(self.ui.create_label_widget("None", properties={"stylesheet": "font: italic"}))
            self.add_widget_to_content(none_widget)
            self.__computation_variable_inserted_event_listener = None
            self.__computation_variable_removed_event_listener = None
        self.finish_widget_content()

    def close(self):
        for widget_wrapper in self.__widget_wrappers:
            widget_wrapper.close()
        self.__widget_wrappers = None
        if self.__computation_variable_inserted_event_listener:
            self.__computation_variable_inserted_event_listener.close()
            self.__computation_variable_inserted_event_listener = None
        if self.__computation_variable_removed_event_listener:
            self.__computation_variable_removed_event_listener.close()
            self.__computation_variable_removed_event_listener = None
        super(ComputationInspectorSection, self).close()


class DataItemInspector:
    """A class to manage creation of a widget representing an inspector for a display specifier.

    A new data item inspector is created whenever the display specifier changes, but not when the content of the items
    within the display specifier mutate.
    """

    def __init__(self, ui, document_model: DocumentModel.DocumentModel, display_specifier: DataItem.DisplaySpecifier):
        self.ui = ui

        data_item, buffered_data_source, display = display_specifier.data_item, display_specifier.buffered_data_source, display_specifier.display

        content_widget = self.ui.create_column_widget()
        content_widget.add_spacing(4)
        if data_item:
            title_row = self.ui.create_row_widget()
            title_label_widget = self.ui.create_label_widget(properties={"stylesheet": "font-weight: bold"})
            title_label_widget.bind_text(Binding.PropertyBinding(data_item, "title"))
            title_row.add_spacing(20)
            title_row.add(title_label_widget)
            title_row.add_stretch()
            content_widget.add(title_row)
            content_widget.add_spacing(4)

        self.__focus_default = None
        self.__inspector_sections = list()
        display_data_shape = display.preview_2d_shape if buffered_data_source else ()
        display_data_shape = display_data_shape if display_data_shape is not None else ()
        if buffered_data_source and display.graphic_selection.has_selection:
            self.__inspector_sections.append(GraphicsInspectorSection(self.ui, data_item, buffered_data_source, display, selected_only=True))
            def focus_default():
                pass
            self.__focus_default = focus_default
        elif buffered_data_source and (len(display_data_shape) == 1 or display.display_type == "line_plot"):
            self.__inspector_sections.append(InfoInspectorSection(self.ui, data_item))
            self.__inspector_sections.append(SessionInspectorSection(self.ui, data_item))
            self.__inspector_sections.append(CalibrationsInspectorSection(self.ui, data_item, buffered_data_source, display))
            self.__inspector_sections.append(LinePlotDisplayInspectorSection(self.ui, display))
            self.__inspector_sections.append(GraphicsInspectorSection(self.ui, data_item, buffered_data_source, display))
            if buffered_data_source.is_sequence:
                self.__inspector_sections.append(SequenceInspectorSection(self.ui, data_item, buffered_data_source, display))
            if buffered_data_source.is_collection:
                if buffered_data_source.collection_dimension_count == 2 and buffered_data_source.datum_dimension_count == 1:
                    self.__inspector_sections.append(SliceInspectorSection(self.ui, data_item, buffered_data_source, display))
                else:  # default, pick
                    self.__inspector_sections.append(CollectionIndexInspectorSection(self.ui, buffered_data_source, display))
            self.__inspector_sections.append(ComputationInspectorSection(self.ui, document_model, data_item, buffered_data_source))
            def focus_default():
                self.__inspector_sections[0].info_title_label.focused = True
                self.__inspector_sections[0].info_title_label.select_all()
            self.__focus_default = focus_default
        elif buffered_data_source and (len(display_data_shape) == 2 or display.display_type == "image"):
            self.__inspector_sections.append(InfoInspectorSection(self.ui, data_item))
            self.__inspector_sections.append(SessionInspectorSection(self.ui, data_item))
            self.__inspector_sections.append(CalibrationsInspectorSection(self.ui, data_item, buffered_data_source, display))
            self.__inspector_sections.append(ImageDisplayInspectorSection(self.ui, display))
            self.__inspector_sections.append(GraphicsInspectorSection(self.ui, data_item, buffered_data_source, display))
            if buffered_data_source.is_sequence:
                self.__inspector_sections.append(SequenceInspectorSection(self.ui, data_item, buffered_data_source, display))
            if buffered_data_source.is_collection:
                if buffered_data_source.collection_dimension_count == 2 and buffered_data_source.datum_dimension_count == 1:
                    self.__inspector_sections.append(SliceInspectorSection(self.ui, data_item, buffered_data_source, display))
                else:  # default, pick
                    self.__inspector_sections.append(CollectionIndexInspectorSection(self.ui, buffered_data_source, display))
            self.__inspector_sections.append(ComputationInspectorSection(self.ui, document_model, data_item, buffered_data_source))
            def focus_default():
                self.__inspector_sections[0].info_title_label.focused = True
                self.__inspector_sections[0].info_title_label.select_all()
            self.__focus_default = focus_default
        elif data_item:
            self.__inspector_sections.append(InfoInspectorSection(self.ui, data_item))
            self.__inspector_sections.append(SessionInspectorSection(self.ui, data_item))
            def focus_default():
                self.__inspector_sections[0].info_title_label.focused = True
                self.__inspector_sections[0].info_title_label.select_all()
            self.__focus_default = focus_default

        for inspector_section in self.__inspector_sections:
            content_widget.add(inspector_section.widget)

        content_widget.add_stretch()

        self.widget = content_widget

    def close(self):
        # close inspectors
        for inspector in self.__inspector_sections:
            inspector.close()
        self.__inspector_sections = None

    def _get_inspectors(self):
        """ Return a copy of the list of inspectors. """
        return copy.copy(self.__inspector_sections)

    def focus_default(self):
        if self.__focus_default:
            self.__focus_default()
