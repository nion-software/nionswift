.. _api-quick:

API Quick Summary
=================

   - API_
   - Application_
   - DataGroup_
   - DataItem_
   - Display_
   - DisplayPanel_
   - DocumentWindow_
   - Graphic_
   - HardwareSource_
   - Instrument_
   - Library_

.. _API:

API
---
class :py:class:`nion.typeshed.API_1_0.API`

**Methods**
   - :py:meth:`create_calibration <nion.typeshed.API_1_0.API.create_calibration>`
   - :py:meth:`create_data_and_metadata <nion.typeshed.API_1_0.API.create_data_and_metadata>`
   - :py:meth:`create_data_and_metadata_from_data <nion.typeshed.API_1_0.API.create_data_and_metadata_from_data>`
   - :py:meth:`create_data_and_metadata_io_handler <nion.typeshed.API_1_0.API.create_data_and_metadata_io_handler>`
   - :py:meth:`create_data_descriptor <nion.typeshed.API_1_0.API.create_data_descriptor>`
   - :py:meth:`create_hardware_source <nion.typeshed.API_1_0.API.create_hardware_source>`
   - :py:meth:`create_menu_item <nion.typeshed.API_1_0.API.create_menu_item>`
   - :py:meth:`create_panel <nion.typeshed.API_1_0.API.create_panel>`
   - :py:meth:`get_all_hardware_source_ids <nion.typeshed.API_1_0.API.get_all_hardware_source_ids>`
   - :py:meth:`get_all_instrument_ids <nion.typeshed.API_1_0.API.get_all_instrument_ids>`
   - :py:meth:`get_hardware_source_by_id <nion.typeshed.API_1_0.API.get_hardware_source_by_id>`
   - :py:meth:`get_instrument_by_id <nion.typeshed.API_1_0.API.get_instrument_by_id>`
   - :py:meth:`queue_task <nion.typeshed.API_1_0.API.queue_task>`

**Properties**
   - :py:attr:`application <nion.typeshed.API_1_0.API.application>`
   - :py:attr:`library <nion.typeshed.API_1_0.API.library>`


.. _Application:

Application
-----------
class :py:class:`nion.typeshed.API_1_0.Application`

**Properties**
   - :py:attr:`document_controllers <nion.typeshed.API_1_0.Application.document_controllers>`
   - :py:attr:`document_windows <nion.typeshed.API_1_0.Application.document_windows>`
   - :py:attr:`library <nion.typeshed.API_1_0.Application.library>`


.. _DataGroup:

DataGroup
---------
class :py:class:`nion.typeshed.API_1_0.DataGroup`

**Methods**
   - :py:meth:`add_data_item <nion.typeshed.API_1_0.DataGroup.add_data_item>`

**Properties**
   - :py:attr:`uuid <nion.typeshed.API_1_0.DataGroup.uuid>`


.. _DataItem:

DataItem
--------
class :py:class:`nion.typeshed.API_1_0.DataItem`

**Methods**
   - :py:meth:`add_channel_region <nion.typeshed.API_1_0.DataItem.add_channel_region>`
   - :py:meth:`add_ellipse_region <nion.typeshed.API_1_0.DataItem.add_ellipse_region>`
   - :py:meth:`add_interval_region <nion.typeshed.API_1_0.DataItem.add_interval_region>`
   - :py:meth:`add_line_region <nion.typeshed.API_1_0.DataItem.add_line_region>`
   - :py:meth:`add_point_region <nion.typeshed.API_1_0.DataItem.add_point_region>`
   - :py:meth:`add_rectangle_region <nion.typeshed.API_1_0.DataItem.add_rectangle_region>`
   - :py:meth:`delete_metadata_value <nion.typeshed.API_1_0.DataItem.delete_metadata_value>`
   - :py:meth:`get_metadata_value <nion.typeshed.API_1_0.DataItem.get_metadata_value>`
   - :py:meth:`has_metadata_value <nion.typeshed.API_1_0.DataItem.has_metadata_value>`
   - :py:meth:`mask_xdata <nion.typeshed.API_1_0.DataItem.mask_xdata>`
   - :py:meth:`remove_region <nion.typeshed.API_1_0.DataItem.remove_region>`
   - :py:meth:`set_data <nion.typeshed.API_1_0.DataItem.set_data>`
   - :py:meth:`set_data_and_metadata <nion.typeshed.API_1_0.DataItem.set_data_and_metadata>`
   - :py:meth:`set_dimensional_calibrations <nion.typeshed.API_1_0.DataItem.set_dimensional_calibrations>`
   - :py:meth:`set_intensity_calibration <nion.typeshed.API_1_0.DataItem.set_intensity_calibration>`
   - :py:meth:`set_metadata <nion.typeshed.API_1_0.DataItem.set_metadata>`
   - :py:meth:`set_metadata_value <nion.typeshed.API_1_0.DataItem.set_metadata_value>`

**Properties**
   - :py:attr:`created <nion.typeshed.API_1_0.DataItem.created>`
   - :py:attr:`data <nion.typeshed.API_1_0.DataItem.data>`
   - :py:attr:`data_and_metadata <nion.typeshed.API_1_0.DataItem.data_and_metadata>`
   - :py:attr:`dimensional_calibrations <nion.typeshed.API_1_0.DataItem.dimensional_calibrations>`
   - :py:attr:`display <nion.typeshed.API_1_0.DataItem.display>`
   - :py:attr:`display_xdata <nion.typeshed.API_1_0.DataItem.display_xdata>`
   - :py:attr:`graphics <nion.typeshed.API_1_0.DataItem.graphics>`
   - :py:attr:`intensity_calibration <nion.typeshed.API_1_0.DataItem.intensity_calibration>`
   - :py:attr:`metadata <nion.typeshed.API_1_0.DataItem.metadata>`
   - :py:attr:`modified <nion.typeshed.API_1_0.DataItem.modified>`
   - :py:attr:`regions <nion.typeshed.API_1_0.DataItem.regions>`
   - :py:attr:`title <nion.typeshed.API_1_0.DataItem.title>`
   - :py:attr:`uuid <nion.typeshed.API_1_0.DataItem.uuid>`
   - :py:attr:`xdata <nion.typeshed.API_1_0.DataItem.xdata>`


.. _Display:

Display
-------
class :py:class:`nion.typeshed.API_1_0.Display`

**Methods**
   - :py:meth:`get_graphic_by_id <nion.typeshed.API_1_0.Display.get_graphic_by_id>`

**Properties**
   - :py:attr:`data_item <nion.typeshed.API_1_0.Display.data_item>`
   - :py:attr:`display_type <nion.typeshed.API_1_0.Display.display_type>`
   - :py:attr:`graphics <nion.typeshed.API_1_0.Display.graphics>`
   - :py:attr:`selected_graphics <nion.typeshed.API_1_0.Display.selected_graphics>`
   - :py:attr:`uuid <nion.typeshed.API_1_0.Display.uuid>`


.. _DisplayPanel:

DisplayPanel
------------
class :py:class:`nion.typeshed.API_1_0.DisplayPanel`

**Methods**
   - :py:meth:`set_data_item <nion.typeshed.API_1_0.DisplayPanel.set_data_item>`

**Properties**
   - :py:attr:`data_item <nion.typeshed.API_1_0.DisplayPanel.data_item>`


.. _DocumentWindow:

DocumentWindow
--------------
class :py:class:`nion.typeshed.API_1_0.DocumentWindow`

**Methods**
   - :py:meth:`add_data <nion.typeshed.API_1_0.DocumentWindow.add_data>`
   - :py:meth:`create_data_item_from_data <nion.typeshed.API_1_0.DocumentWindow.create_data_item_from_data>`
   - :py:meth:`create_data_item_from_data_and_metadata <nion.typeshed.API_1_0.DocumentWindow.create_data_item_from_data_and_metadata>`
   - :py:meth:`display_data_item <nion.typeshed.API_1_0.DocumentWindow.display_data_item>`
   - :py:meth:`get_display_panel_by_id <nion.typeshed.API_1_0.DocumentWindow.get_display_panel_by_id>`
   - :py:meth:`get_or_create_data_group <nion.typeshed.API_1_0.DocumentWindow.get_or_create_data_group>`
   - :py:meth:`queue_task <nion.typeshed.API_1_0.DocumentWindow.queue_task>`
   - :py:meth:`show_confirmation_message_box <nion.typeshed.API_1_0.DocumentWindow.show_confirmation_message_box>`
   - :py:meth:`show_get_string_message_box <nion.typeshed.API_1_0.DocumentWindow.show_get_string_message_box>`
   - :py:meth:`show_modeless_dialog <nion.typeshed.API_1_0.DocumentWindow.show_modeless_dialog>`

**Properties**
   - :py:attr:`all_display_panels <nion.typeshed.API_1_0.DocumentWindow.all_display_panels>`
   - :py:attr:`library <nion.typeshed.API_1_0.DocumentWindow.library>`
   - :py:attr:`target_data_item <nion.typeshed.API_1_0.DocumentWindow.target_data_item>`
   - :py:attr:`target_display <nion.typeshed.API_1_0.DocumentWindow.target_display>`


.. _Graphic:

Graphic
-------
class :py:class:`nion.typeshed.API_1_0.Graphic`

**Methods**
   - :py:meth:`get_property <nion.typeshed.API_1_0.Graphic.get_property>`
   - :py:meth:`mask_xdata_with_shape <nion.typeshed.API_1_0.Graphic.mask_xdata_with_shape>`
   - :py:meth:`set_property <nion.typeshed.API_1_0.Graphic.set_property>`

**Properties**
   - :py:attr:`angle <nion.typeshed.API_1_0.Graphic.angle>`
   - :py:attr:`bounds <nion.typeshed.API_1_0.Graphic.bounds>`
   - :py:attr:`center <nion.typeshed.API_1_0.Graphic.center>`
   - :py:attr:`end <nion.typeshed.API_1_0.Graphic.end>`
   - :py:attr:`graphic_id <nion.typeshed.API_1_0.Graphic.graphic_id>`
   - :py:attr:`graphic_type <nion.typeshed.API_1_0.Graphic.graphic_type>`
   - :py:attr:`interval <nion.typeshed.API_1_0.Graphic.interval>`
   - :py:attr:`label <nion.typeshed.API_1_0.Graphic.label>`
   - :py:attr:`position <nion.typeshed.API_1_0.Graphic.position>`
   - :py:attr:`region <nion.typeshed.API_1_0.Graphic.region>`
   - :py:attr:`size <nion.typeshed.API_1_0.Graphic.size>`
   - :py:attr:`start <nion.typeshed.API_1_0.Graphic.start>`
   - :py:attr:`type <nion.typeshed.API_1_0.Graphic.type>`
   - :py:attr:`uuid <nion.typeshed.API_1_0.Graphic.uuid>`
   - :py:attr:`vector <nion.typeshed.API_1_0.Graphic.vector>`


.. _HardwareSource:

HardwareSource
--------------
class :py:class:`nion.typeshed.API_1_0.HardwareSource`

**Methods**
   - :py:meth:`abort_playing <nion.typeshed.API_1_0.HardwareSource.abort_playing>`
   - :py:meth:`abort_recording <nion.typeshed.API_1_0.HardwareSource.abort_recording>`
   - :py:meth:`close <nion.typeshed.API_1_0.HardwareSource.close>`
   - :py:meth:`create_record_task <nion.typeshed.API_1_0.HardwareSource.create_record_task>`
   - :py:meth:`create_view_task <nion.typeshed.API_1_0.HardwareSource.create_view_task>`
   - :py:meth:`get_default_frame_parameters <nion.typeshed.API_1_0.HardwareSource.get_default_frame_parameters>`
   - :py:meth:`get_frame_parameters <nion.typeshed.API_1_0.HardwareSource.get_frame_parameters>`
   - :py:meth:`get_frame_parameters_for_profile_by_index <nion.typeshed.API_1_0.HardwareSource.get_frame_parameters_for_profile_by_index>`
   - :py:meth:`get_property_as_bool <nion.typeshed.API_1_0.HardwareSource.get_property_as_bool>`
   - :py:meth:`get_property_as_float <nion.typeshed.API_1_0.HardwareSource.get_property_as_float>`
   - :py:meth:`get_property_as_float_point <nion.typeshed.API_1_0.HardwareSource.get_property_as_float_point>`
   - :py:meth:`get_property_as_int <nion.typeshed.API_1_0.HardwareSource.get_property_as_int>`
   - :py:meth:`get_property_as_str <nion.typeshed.API_1_0.HardwareSource.get_property_as_str>`
   - :py:meth:`grab_next_to_finish <nion.typeshed.API_1_0.HardwareSource.grab_next_to_finish>`
   - :py:meth:`grab_next_to_start <nion.typeshed.API_1_0.HardwareSource.grab_next_to_start>`
   - :py:meth:`record <nion.typeshed.API_1_0.HardwareSource.record>`
   - :py:meth:`set_frame_parameters <nion.typeshed.API_1_0.HardwareSource.set_frame_parameters>`
   - :py:meth:`set_frame_parameters_for_profile_by_index <nion.typeshed.API_1_0.HardwareSource.set_frame_parameters_for_profile_by_index>`
   - :py:meth:`set_property_as_bool <nion.typeshed.API_1_0.HardwareSource.set_property_as_bool>`
   - :py:meth:`set_property_as_float <nion.typeshed.API_1_0.HardwareSource.set_property_as_float>`
   - :py:meth:`set_property_as_float_point <nion.typeshed.API_1_0.HardwareSource.set_property_as_float_point>`
   - :py:meth:`set_property_as_int <nion.typeshed.API_1_0.HardwareSource.set_property_as_int>`
   - :py:meth:`set_property_as_str <nion.typeshed.API_1_0.HardwareSource.set_property_as_str>`
   - :py:meth:`start_playing <nion.typeshed.API_1_0.HardwareSource.start_playing>`
   - :py:meth:`start_recording <nion.typeshed.API_1_0.HardwareSource.start_recording>`
   - :py:meth:`stop_playing <nion.typeshed.API_1_0.HardwareSource.stop_playing>`

**Properties**
   - :py:attr:`is_playing <nion.typeshed.API_1_0.HardwareSource.is_playing>`
   - :py:attr:`is_recording <nion.typeshed.API_1_0.HardwareSource.is_recording>`
   - :py:attr:`profile_index <nion.typeshed.API_1_0.HardwareSource.profile_index>`


.. _Instrument:

Instrument
----------
class :py:class:`nion.typeshed.API_1_0.Instrument`

**Methods**
   - :py:meth:`close <nion.typeshed.API_1_0.Instrument.close>`
   - :py:meth:`get_control_output <nion.typeshed.API_1_0.Instrument.get_control_output>`
   - :py:meth:`get_control_state <nion.typeshed.API_1_0.Instrument.get_control_state>`
   - :py:meth:`get_property_as_bool <nion.typeshed.API_1_0.Instrument.get_property_as_bool>`
   - :py:meth:`get_property_as_float <nion.typeshed.API_1_0.Instrument.get_property_as_float>`
   - :py:meth:`get_property_as_float_point <nion.typeshed.API_1_0.Instrument.get_property_as_float_point>`
   - :py:meth:`get_property_as_int <nion.typeshed.API_1_0.Instrument.get_property_as_int>`
   - :py:meth:`get_property_as_str <nion.typeshed.API_1_0.Instrument.get_property_as_str>`
   - :py:meth:`set_control_output <nion.typeshed.API_1_0.Instrument.set_control_output>`
   - :py:meth:`set_property_as_bool <nion.typeshed.API_1_0.Instrument.set_property_as_bool>`
   - :py:meth:`set_property_as_float <nion.typeshed.API_1_0.Instrument.set_property_as_float>`
   - :py:meth:`set_property_as_float_point <nion.typeshed.API_1_0.Instrument.set_property_as_float_point>`
   - :py:meth:`set_property_as_int <nion.typeshed.API_1_0.Instrument.set_property_as_int>`
   - :py:meth:`set_property_as_str <nion.typeshed.API_1_0.Instrument.set_property_as_str>`


.. _Library:

Library
-------
class :py:class:`nion.typeshed.API_1_0.Library`

**Methods**
   - :py:meth:`copy_data_item <nion.typeshed.API_1_0.Library.copy_data_item>`
   - :py:meth:`create_data_item <nion.typeshed.API_1_0.Library.create_data_item>`
   - :py:meth:`create_data_item_from_data <nion.typeshed.API_1_0.Library.create_data_item_from_data>`
   - :py:meth:`create_data_item_from_data_and_metadata <nion.typeshed.API_1_0.Library.create_data_item_from_data_and_metadata>`
   - :py:meth:`data_ref_for_data_item <nion.typeshed.API_1_0.Library.data_ref_for_data_item>`
   - :py:meth:`delete_library_value <nion.typeshed.API_1_0.Library.delete_library_value>`
   - :py:meth:`get_data_item_by_uuid <nion.typeshed.API_1_0.Library.get_data_item_by_uuid>`
   - :py:meth:`get_data_item_for_hardware_source <nion.typeshed.API_1_0.Library.get_data_item_for_hardware_source>`
   - :py:meth:`get_data_item_for_reference_key <nion.typeshed.API_1_0.Library.get_data_item_for_reference_key>`
   - :py:meth:`get_dependent_data_items <nion.typeshed.API_1_0.Library.get_dependent_data_items>`
   - :py:meth:`get_graphic_by_uuid <nion.typeshed.API_1_0.Library.get_graphic_by_uuid>`
   - :py:meth:`get_library_value <nion.typeshed.API_1_0.Library.get_library_value>`
   - :py:meth:`get_or_create_data_group <nion.typeshed.API_1_0.Library.get_or_create_data_group>`
   - :py:meth:`get_source_data_items <nion.typeshed.API_1_0.Library.get_source_data_items>`
   - :py:meth:`has_library_value <nion.typeshed.API_1_0.Library.has_library_value>`
   - :py:meth:`set_library_value <nion.typeshed.API_1_0.Library.set_library_value>`
   - :py:meth:`snapshot_data_item <nion.typeshed.API_1_0.Library.snapshot_data_item>`

**Properties**
   - :py:attr:`data_item_count <nion.typeshed.API_1_0.Library.data_item_count>`
   - :py:attr:`data_items <nion.typeshed.API_1_0.Library.data_items>`
   - :py:attr:`uuid <nion.typeshed.API_1_0.Library.uuid>`

