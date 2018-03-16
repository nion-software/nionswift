# standard libraries
import gettext
import numpy
import time
import typing

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift import Undo
from nion.ui import Dialog
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import Model
from nion.swift import DataItemThumbnailWidget
from nion.swift.model import DataItem

_ = gettext.gettext


class Recorder:

    def __init__(self, document_controller, data_item):
        self.__document_controller = document_controller
        self.__document_model = document_controller.document_model
        self.__data_item = data_item

        self.on_live_state_changed = None
        self.on_recording_state_changed = None
        self.on_data_item_removed = None

        self.__recording_state = "stopped"
        self.__recording_start = 0.0
        self.__recording_index = 0
        self.__recording_data_item = None
        self.__recording_transaction = None
        self.__recording_error = False
        self.__recording_interval = None
        self.__recording_count = None

        def data_item_content_changed():
            is_live = data_item.is_live
            if not is_live:
                self.__stop_recording()
            if callable(self.on_live_state_changed):
                self.on_live_state_changed(is_live)

        # if the item source or recorded data item is removed, stop recording
        # called when an item is removed from the document
        def item_removed(key, value, index):
            if value == self.__recording_data_item:
                self.__stop_recording()
            if value == self.__data_item:
                self.__stop_recording()
                if callable(self.on_data_item_removed):
                    self.on_data_item_removed()

        def data_changed():
            current_xdata = self.__data_item.xdata
            if current_xdata and not current_xdata.is_sequence:
                hardware_source_metadata = current_xdata.metadata.get("hardware_source", dict())
                valid_rows = hardware_source_metadata.get("valid_rows", 0) if "valid_rows" in hardware_source_metadata else current_xdata.data_shape[0]
                if len(current_xdata.data_shape) == 1 or valid_rows >= current_xdata.data_shape[0]:
                    self.__last_complete_xdata = current_xdata
            else:
                self.__recording_error = True

        self.__library_item_changed_event_listener = data_item.library_item_changed_event.listen(data_item_content_changed)
        self.__item_removed_event_listener = self.__document_model.item_removed_event.listen(item_removed)
        self.__data_item_data_changed_event_listener = self.__data_item.data_changed_event.listen(data_changed)

        self.__last_complete_xdata = None

        data_item_content_changed()
        data_changed()

    def close(self):
        self.__library_item_changed_event_listener.close()
        self.__library_item_changed_event_listener = None
        self.__item_removed_event_listener.close()
        self.__item_removed_event_listener = None
        self.__data_item_data_changed_event_listener.close()
        self.__data_item_data_changed_event_listener = None

    @property
    def recording_state(self) -> str:
        return self.__recording_state

    class RecorderInsertLibraryItemCommandCommand(Undo.UndoableCommand):

        def __init__(self, document_controller, recorder: "Recorder", library_item_fn: typing.Callable[[], DataItem.LibraryItem]):
            super().__init__(_("Record Library Item"))
            self.__document_controller = document_controller
            self.__recorder = recorder
            self.__old_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__new_workspace_layout = None
            self.__library_item_uuid = None
            self.__library_item_fn = library_item_fn
            self.__library_item_index = None
            self.initialize()

        def close(self):
            self.__document_controller = None
            self.__library_item_uuid = None
            self.__library_item_fn = None
            self.__library_item_index = None
            self.__old_workspace_layout = None
            self.__new_workspace_layout = None
            super().close()

        def perform(self):
            self.__library_item_uuid = self.__library_item_fn().uuid

        @property
        def library_item(self):
            return self.__document_controller.document_model.get_data_item_by_uuid(self.__library_item_uuid)

        def _get_modified_state(self):
            return self.__document_controller.document_model.modified_state

        def _set_modified_state(self, modified_state) -> None:
            self.__document_controller.document_model.modified_state = modified_state

        def _redo(self):
            self.__document_controller.document_model.undelete_all(self.__undelete_log)
            self.__library_item_uuid = self.__document_controller.document_model.data_items[self.__library_item_index].uuid
            self.__document_controller.workspace_controller.reconstruct(self.__new_workspace_layout)

        def _undo(self):
            library_item = self.__document_controller.document_model.get_data_item_by_uuid(self.__library_item_uuid)
            self.__recorder.stop_recording()
            self.__new_workspace_layout = self.__document_controller.workspace_controller.deconstruct()
            self.__library_item_index = self.__document_controller.document_model.data_items.index(library_item)
            self.__undelete_log = self.__document_controller.document_model.remove_data_item(library_item, safe=True)
            self.__document_controller.workspace_controller.reconstruct(self.__old_workspace_layout)

    def continue_recording(self, current_time: float) -> None:
        if self.__recording_state == "recording":
            if (current_time - self.__recording_start) // self.__recording_interval > self.__recording_index - 1:
                self.__recording_last = current_time
                # first create an empty data item to hold the recorded data if it doesn't already exist
                if not self.__recording_data_item:
                    data_item = DataItem.DataItem(large_format=True)
                    data_item.ensure_data_source()
                    data_item.title = _("Recording of ") + self.__data_item.title

                    def process():
                        self.__document_model.append_data_item(data_item)
                        self.__document_controller.display_data_item(DataItem.DisplaySpecifier.from_data_item(data_item))
                        return data_item

                    command = Recorder.RecorderInsertLibraryItemCommandCommand(self.__document_controller, self, process)
                    command.perform()
                    self.__document_controller.push_undo_command(command)

                    self.__recording_data_item = data_item
                # next grab the current data and stop if it is a sequence (can't record sequences)
                current_xdata = self.__last_complete_xdata
                if self.__recording_error:
                    self.__stop_recording()
                    return
                if not current_xdata:
                    # no first image yet
                    return
                # now record the new data. it may or may not be a new frame at this point.
                last_xdata = self.__recording_data_item.xdata
                self.__recording_index += 1
                if current_xdata and last_xdata and current_xdata.data_shape == self.__recording_data_item.data_shape[1:]:
                    # continue, append the new data to existing data and update existing data item
                    intensity_calibration = last_xdata.intensity_calibration
                    dimensional_calibrations = last_xdata.dimensional_calibrations
                    data_descriptor = last_xdata.data_descriptor
                    sequence_xdata = DataAndMetadata.new_data_and_metadata(
                        numpy.vstack([last_xdata.data, [current_xdata.data]]),
                        intensity_calibration=intensity_calibration, dimensional_calibrations=dimensional_calibrations,
                        data_descriptor=data_descriptor)
                    self.__recording_data_item.set_xdata(sequence_xdata)
                elif current_xdata and not last_xdata:
                    # first acquisition, create the sequence
                    intensity_calibration = current_xdata.intensity_calibration
                    dimensional_calibrations = [Calibration.Calibration(scale=self.__recording_interval,
                                                                        units="s")] + list(
                        current_xdata.dimensional_calibrations)
                    data_descriptor = DataAndMetadata.DataDescriptor(True,
                                                                     current_xdata.data_descriptor.collection_dimension_count,
                                                                     current_xdata.data_descriptor.datum_dimension_count)
                    sequence_xdata = DataAndMetadata.new_data_and_metadata(current_xdata.data[numpy.newaxis, ...],
                                                                           intensity_calibration=intensity_calibration,
                                                                           dimensional_calibrations=dimensional_calibrations,
                                                                           data_descriptor=data_descriptor)
                    self.__recording_data_item.set_xdata(sequence_xdata)
                    self.__recording_transaction = self.__document_model.item_transaction(self.__recording_data_item)
                else:
                    # something is amiss. stop.
                    self.__stop_recording()
                    return
            # finally -- check if we've reached the maximum count
            if self.__recording_index >= self.__recording_count:
                self.__stop_recording()

    def start_recording(self, recording_start: float, recording_interval: float, recording_count: int) -> None:
        self.__recording_state = "recording"
        self.__recording_start = recording_start
        self.__recording_index = 0
        self.__recording_error = False
        self.__recording_interval = recording_interval
        self.__recording_count = recording_count
        if callable(self.on_recording_state_changed):
            self.on_recording_state_changed(self.__recording_state)

    def stop_recording(self):
        self.__stop_recording()

    def __stop_recording(self):
        if self.__recording_state == "recording":
            self.__recording_state = "stopped"
            self.__recording_start = 0.0
            self.__recording_index = 0
            self.__recording_error = False
            if self.__recording_data_item and self.__recording_transaction:
                self.__recording_transaction.close()
                self.__recording_transaction = None
                self.__recording_data_item = None
            if callable(self.on_recording_state_changed):
                self.on_recording_state_changed(self.__recording_state)


class RecorderDialog(Dialog.ActionDialog):

    def __init__(self, document_controller, data_item):
        ui = document_controller.ui
        super().__init__(ui, _("Recorder"), app=document_controller.app, parent_window=document_controller, persistent_id="Recorder" + str(data_item.uuid))

        self.__recorder = Recorder(document_controller, data_item)

        self.ui = ui
        self.document_controller = document_controller

        self.__data_item = data_item

        self._create_menus()

        self.__record_button = ui.create_push_button_widget(_("Record"))

        def thumbnail_widget_drag(mime_data, thumbnail, hot_spot_x, hot_spot_y):
            # use this convoluted base object for drag so that it doesn't disappear after the drag.
            self.content.drag(mime_data, thumbnail, hot_spot_x, hot_spot_y)

        data_item_thumbnail_source = DataItemThumbnailWidget.DataItemThumbnailSource(ui, data_item=data_item)
        data_item_chooser_widget = DataItemThumbnailWidget.ThumbnailWidget(ui, data_item_thumbnail_source, Geometry.IntSize(48, 48))
        data_item_chooser_widget.on_drag = thumbnail_widget_drag

        self.__recording_interval_property = Model.PropertyModel(1000)
        self.__recording_count_property = Model.PropertyModel(20)

        recording_period_widget = ui.create_line_edit_widget(properties={"width": 60})
        recording_period_widget.bind_text(Binding.PropertyBinding(self.__recording_interval_property, "value", converter=Converter.IntegerToStringConverter()))

        recording_count_widget = ui.create_line_edit_widget(properties={"width": 60})
        recording_count_widget.bind_text(Binding.PropertyBinding(self.__recording_count_property, "value", converter=Converter.IntegerToStringConverter()))

        row0 = ui.create_row_widget()
        row0.add_stretch()
        row0.add_spacing(8)
        row0.add(self.__record_button)
        row0.add_spacing(8)

        row1 = ui.create_row_widget()
        row1.add(ui.create_label_widget(_("Interval")))
        row1.add_spacing(8)
        row1.add(recording_period_widget)
        row1.add_spacing(4)
        row1.add(ui.create_label_widget(_("msec")))
        row1.add_spacing(8)
        row1.add_stretch()

        row2 = ui.create_row_widget()
        row2.add(ui.create_label_widget(_("Frames")))
        row2.add_spacing(8)
        row2.add(recording_count_widget)
        row2.add_spacing(8)
        row2.add_stretch()

        column1 = ui.create_column_widget()
        column1.add(row1)
        column1.add_spacing(4)
        column1.add(row2)
        column1.add_spacing(4)
        column1.add(row0)

        button_row = ui.create_row_widget()
        button_row.add_spacing(8)
        button_row.add(data_item_chooser_widget)
        button_row.add_spacing(8)
        button_row.add_stretch()
        button_row.add_spacing(8)
        button_row.add(column1)
        button_row.add_spacing(8)

        def record_pressed():
            if self.__recorder.recording_state == "recording":
                self.__recorder.stop_recording()
            else:
                self.__recorder.start_recording(time.time(), self.__recording_interval_property.value / 1000, self.__recording_count_property.value)

        self.__record_button.on_clicked = record_pressed

        column = self.content
        column.add_spacing(6)
        column.add(button_row)
        column.add_spacing(6)

        def live_state_changed(is_live: bool) -> None:
            self.__record_button.enabled = is_live

        def recording_state_changed(recording_state: str) -> None:
            if recording_state == "recording":
                self.__record_button.text = _("Stop")
            else:
                self.__record_button.text = _("Record")

        def data_item_removed() -> None:
            self.request_close()

        self.__recorder.on_live_state_changed = live_state_changed
        self.__recorder.on_recording_state_changed = recording_state_changed
        self.__recorder.on_data_item_removed = data_item_removed

        live_state_changed(data_item.is_live)
        recording_state_changed("stopped")

    def close(self):
        self.__recorder.close()
        self.__recorder = None
        super().close()

    def periodic(self):
        super().periodic()
        self.__recorder.continue_recording(time.time())
