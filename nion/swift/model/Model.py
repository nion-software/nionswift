"""Description of data model.

Reference: https://en.wikipedia.org/wiki/Data_modeling
"""

from __future__ import annotations

import copy
import datetime
import gettext
import typing
import uuid

from nion.swift.model import Schema

_ = gettext.gettext

# TODO: description of physical schema
# TODO: created and modified should be implicit in all records
# TODO: should timezone, timezone offset be implicit?
# TODO: some data must be copied on read/write (dict's)
# TODO: support external data concept with loaded/unloaded property
# TODO: support loaded/unloaded entities?
# TODO: support mounted/unmounted entity concept (projects)
# TODO: support write delay / transactions
# TODO: access to auto proxy items for references
# TODO: closing, reading, inserting, removing, modifying, copying, container
# TODO: notifying, storage, resolving, moving

# TODO: are interval descriptors implicit now?
# TODO: display_layers could be a record
# TODO: display_properties could be a record
# TODO: layout could be a record
# TODO: closed_items should be a set of references

Calibration = Schema.record({
    "offset": Schema.prop(Schema.FLOAT),
    "scale": Schema.prop(Schema.FLOAT),
    "units": Schema.prop(Schema.STRING),
})

Point = Schema.fixed_tuple([Schema.prop(Schema.FLOAT), Schema.prop(Schema.FLOAT)])

Size = Schema.fixed_tuple([Schema.prop(Schema.FLOAT), Schema.prop(Schema.FLOAT)])

Rect = Schema.fixed_tuple([Point,  Size])

Vector = Schema.fixed_tuple([Point, Point])

Interval = Schema.fixed_tuple([Schema.prop(Schema.FLOAT), Schema.prop(Schema.FLOAT)])

DataItem = Schema.entity("data-item", None, 13, {
    "created": Schema.prop(Schema.TIMESTAMP),
    "data_shape": Schema.indefinite_tuple(Schema.prop(Schema.INT)),
    "data_dtype": Schema.prop(Schema.STRING),
    "is_sequence": Schema.prop(Schema.BOOLEAN),
    "collection_dimension_count": Schema.prop(Schema.INT),
    "datum_dimension_count": Schema.prop(Schema.INT),
    "intensity_calibration": Calibration,
    "dimensional_calibrations": Schema.array(Calibration),
    "data_modified": Schema.prop(Schema.TIMESTAMP),
    "timezone": Schema.prop(Schema.STRING),
    "timezone_offset": Schema.prop(Schema.STRING),
    "metadata": Schema.prop(Schema.DICT),
    "title": Schema.prop(Schema.STRING),
    "caption": Schema.prop(Schema.STRING),
    "description": Schema.prop(Schema.STRING),
    "session_id": Schema.prop(Schema.STRING),
    "session": Schema.prop(Schema.DICT),
    "category": Schema.prop(Schema.STRING, default="persistent"),
    "source": Schema.reference(),
})

DataItem.rename("source", "source_uuid")

DisplayAdjustment = Schema.entity("display_adjustment", None, None, {
})

GammaDisplayAdjustment = Schema.entity("gamma", DisplayAdjustment, None, {
    "gamma": Schema.prop(Schema.FLOAT),
})

LogDisplayAdjustment = Schema.entity("log", DisplayAdjustment, None, {
})

EqualizedDisplayAdjustment = Schema.entity("equalized", DisplayAdjustment, None, {
})

DisplayDataChannel = Schema.entity("display_data_channel", None, None, {
    "brightness": Schema.prop(Schema.FLOAT),
    "contrast": Schema.prop(Schema.FLOAT),
    "adjustments": Schema.array(Schema.component(DisplayAdjustment)),
    "complex_display_type": Schema.prop(Schema.STRING),
    "display_limits": Schema.fixed_tuple([Schema.prop(Schema.FLOAT), Schema.prop(Schema.FLOAT)]),
    "color_map_id": Schema.prop(Schema.STRING),
    "sequence_index": Schema.prop(Schema.INT),
    "collection_index": Schema.indefinite_tuple(Schema.prop(Schema.INT)),
    "slice_center": Schema.prop(Schema.INT),
    "slice_width": Schema.prop(Schema.INT),
    "data_item": Schema.reference(DataItem),
})

DisplayDataChannel.rename("data_item", "data_item_reference")

DisplayLayer = Schema.entity("display_layer", None, None, {
    "data_row": Schema.prop(Schema.INT),
    "stroke_color": Schema.prop(Schema.STRING),
    "fill_color": Schema.prop(Schema.STRING),
    "label": Schema.prop(Schema.STRING),
    "display_data_channel": Schema.reference(DisplayDataChannel),
})

Graphic = Schema.entity("graphic", None, None, {
    "graphic_id": Schema.prop(Schema.STRING),
    "stroke_color": Schema.prop(Schema.STRING),
    "fill_color": Schema.prop(Schema.STRING),
    "label": Schema.prop(Schema.STRING),
    "is_position_locked": Schema.prop(Schema.BOOLEAN),
    "is_shape_locked": Schema.prop(Schema.BOOLEAN),
    "is_bounds_constrained": Schema.prop(Schema.BOOLEAN),
    "role": Schema.prop(Schema.STRING),
    "source": Schema.reference(),
})

Graphic.rename("source", "source_uuid")
Graphic.rename("stroke_color", "color")

RectangleTypeGraphic = Schema.entity("rect-type-graphic", Graphic, None, {
    "bounds": Rect,
    "rotation": Schema.prop(Schema.FLOAT),
})

RectangleGraphic = Schema.entity("rect-graphic", RectangleTypeGraphic, None, {})

EllipseGraphic = Schema.entity("ellipse-graphic", RectangleTypeGraphic, None, {})

LineTypeGraphic = Schema.entity("line-type-graphic", Graphic, None, {
    "start": Point,
    "end": Point,
    "start_arrow_enabled": Schema.prop(Schema.BOOLEAN),
    "end_arrow_enabled": Schema.prop(Schema.BOOLEAN),
})

LineGraphic = Schema.entity("line-graphic", LineTypeGraphic, None, {})

LineProfileGraphic = Schema.entity("line-profile-graphic", LineTypeGraphic, None, {
    "width": Schema.prop(Schema.FLOAT, default=1.0),
    "interval_descriptors": Schema.prop(Schema.LIST),
})

PointGraphic = Schema.entity("point-graphic", Graphic, None, {
    "position": Point,
})

IntervalGraphic = Schema.entity("interval-graphic", Graphic, None, {
    "start": Schema.prop(Schema.FLOAT, default=0.0),
    "end": Schema.prop(Schema.FLOAT, default=1.0),
})

ChannelGraphic = Schema.entity("channel-graphic", Graphic, None, {
    "position": Schema.prop(Schema.FLOAT, default=0.5),
})

SpotGraphic = Schema.entity("spot-graphic", Graphic, None, {
    "bounds": Rect,
    "rotation": Schema.prop(Schema.FLOAT),
})

WedgeGraphic = Schema.entity("wedge-graphic", Graphic, None, {
    "angle_interval": Interval,
})

RingGraphic = Schema.entity("ring-graphic", Graphic, None, {
    "radius_1": Schema.prop(Schema.FLOAT, default=0.2),
    "radius_2": Schema.prop(Schema.FLOAT, default=0.4),
    "mode": Schema.prop(Schema.STRING, default="band-pass"),
})

LatticeGraphic = Schema.entity("lattice-graphic", Graphic, None, {
    "u_pos": Point,
    "v_pos": Point,
    "u_count": Schema.prop(Schema.INT, default=1),
    "v_count": Schema.prop(Schema.INT, default=1),
    "radius": Schema.prop(Schema.FLOAT, default=0.1),
})

DisplayItem = Schema.entity("display_item", None, None, {
    "created": Schema.prop(Schema.TIMESTAMP),
    "display_type": Schema.prop(Schema.STRING),
    "title": Schema.prop(Schema.STRING),
    "caption": Schema.prop(Schema.STRING),
    "description": Schema.prop(Schema.STRING),
    "session_id": Schema.prop(Schema.STRING),
    "calibration_style_id": Schema.prop(Schema.STRING, default="calibrated"),
    "display_properties": Schema.prop(Schema.DICT),
    "display_layers": Schema.array(Schema.component(DisplayLayer)),
    "graphics": Schema.array(Schema.component(Graphic)),
    "display_data_channels": Schema.array(Schema.component(DisplayDataChannel)),
})

ComputationVariable = Schema.entity("variable", None, None, {
    "name": Schema.prop(Schema.STRING),
    "label": Schema.prop(Schema.STRING),
    "value_type": Schema.prop(Schema.STRING),
    "value": Schema.prop(Schema.ANY),
    "value_default": Schema.prop(Schema.ANY),
    "value_min": Schema.prop(Schema.ANY),
    "value_max": Schema.prop(Schema.ANY),
    "item": Schema.reference(),
    "item2": Schema.reference(),
    "items": Schema.array(Schema.reference(), Schema.OPTIONAL),
    "property_name": Schema.prop(Schema.STRING),
    "control_type": Schema.prop(Schema.STRING),
})

ComputationVariable.rename("item", "specifier")
ComputationVariable.rename("item2", "secondary_specifier")
ComputationVariable.rename("items", "object_specifiers")

ComputationResult = Schema.entity("output", None, None, {
    "name": Schema.prop(Schema.STRING),
    "label": Schema.prop(Schema.STRING),
    "item": Schema.reference(),
    "items": Schema.array(Schema.reference(), Schema.OPTIONAL),
})

ComputationResult.rename("item", "specifier")
ComputationResult.rename("items", "specifiers")

Computation = Schema.entity("computation", None, None, {
    "source": Schema.reference(),
    "original_expression": Schema.prop(Schema.STRING),
    "error_text": Schema.prop(Schema.STRING),
    "label": Schema.prop(Schema.STRING),
    "processing_id": Schema.prop(Schema.STRING),
    "variables": Schema.array(Schema.component(ComputationVariable)),
    "results": Schema.array(Schema.component(ComputationResult)),
})

Computation.rename("source", "source_uuid")

DataStructure = Schema.entity("data_structure", None, None, {
    "source": Schema.reference(),
    "structure_type": Schema.prop(Schema.STRING),
    "properties": Schema.prop(Schema.DICT),
})

DataStructure.rename("source", "source_uuid")

Connection = Schema.entity("connection", None, None, {
    "parent": Schema.reference(),
})

Connection.rename("parent", "parent_uuid")

PropertyConnection = Schema.entity("property-connection", Connection, None, {
    "source": Schema.reference(),
    "source_property": Schema.prop(Schema.STRING),
    "target": Schema.reference(),
    "target_property": Schema.prop(Schema.STRING),
})

PropertyConnection.rename("source", "source_uuid")
PropertyConnection.rename("target", "target_uuid")

IntervalListConnection = Schema.entity("interval-list-connection", Connection, None, {
    "source": Schema.reference(),
    "target": Schema.reference(),
})

IntervalListConnection.rename("source", "source_uuid")
IntervalListConnection.rename("target", "target_uuid")

DataGroup = Schema.entity("data_group", None, None, {
    "title": Schema.prop(Schema.STRING, default=_("Untitled")),
    "display_items": Schema.array(Schema.component(DisplayItem)),
    "data_groups": Schema.array(Schema.component("data_group")),
})

DataGroup.rename("display_items", "display_item_references")

Workspace = Schema.entity("workspace", None, None, {
    "name": Schema.prop(Schema.STRING),
    "layout": Schema.prop(Schema.DICT, Schema.OPTIONAL),
    "workspace_id": Schema.prop(Schema.STRING, Schema.OPTIONAL),
})

Project = Schema.entity("project", None, 3, {
    "title": Schema.prop(Schema.STRING),
    "data_items": Schema.array(Schema.component(DataItem), Schema.OPTIONAL),
    "display_items": Schema.array(Schema.component(DisplayItem)),
    "computations": Schema.array(Schema.component(Computation)),
    "data_structures": Schema.array(Schema.component(DataStructure)),
    "connections": Schema.array(Schema.component(Connection)),
    "data_groups": Schema.array(Schema.component(DataGroup)),
    "workspaces": Schema.array(Schema.component(Workspace)),
    "workspace": Schema.reference(Workspace),
    "data_item_references": Schema.map(Schema.STRING, Schema.reference(DataItem)),
    "mapped_items": Schema.array(Schema.reference(DataItem), Schema.OPTIONAL),
    "project_data_folders": Schema.array(Schema.prop(Schema.PATH)),
})

Project.rename("workspace", "workspace_uuid")


def transform_forward(d: typing.Dict) -> typing.Dict:
    for display_item in d.get("display_items", list()):
        display_data_channels = display_item.get("display_data_channels", list())
        for display_layer in display_item.get("display_layers", list()):
            display_layer["type"] = "display_layer"
            display_layer["uuid"] = str(uuid.uuid4())
            display_layer["modified"] = copy.copy(display_item.get("modified", str(datetime.datetime.utcnow())))
            data_index = display_layer.pop("data_index", None)
            if data_index is not None and 0 <= data_index < len(display_data_channels):
                display_layer["display_data_channel"] = display_data_channels[data_index]["uuid"]
    return d


def transform_backward(d: typing.Dict) -> typing.Dict:
    for display_item in d.get("display_items", list()):
        display_data_channels = display_item.get("display_data_channels", list())
        display_data_channel_map = {display_data_channel["uuid"]: index for index, display_data_channel in enumerate(display_data_channels)}
        for display_layer in display_item.get("display_layers", list()):
            display_layer.pop("type", None)
            display_layer.pop("uuid", None)
            display_layer.pop("modified", None)
            display_data_channel_uuid = display_layer.pop("display_data_channel", None)
            data_index = display_data_channel_map.get(display_data_channel_uuid, None)
            if data_index is not None:
                display_layer["data_index"] = data_index
    return d


Project.transform(transform_forward, transform_backward)

ProjectReference = Schema.entity("project_reference", None, None, {
    "project": Schema.reference(Project),
    "is_active": Schema.prop(Schema.BOOLEAN),
    "last_used": Schema.prop(Schema.TIMESTAMP),
})

ProjectReference.rename("project", "project_uuid")

IndexProjectReference = Schema.entity("project_index", ProjectReference, None, {
    "project_path": Schema.prop(Schema.PATH),
})

FolderProjectReference = Schema.entity("project_folder", ProjectReference, None, {
    "project_folder_path": Schema.prop(Schema.PATH),
})

MemoryProjectReference = Schema.entity("project_memory", ProjectReference, None, {
})

ScriptItem = Schema.entity("script_item", None, None, {
})

FileScriptItem = Schema.entity("file_script_item", ScriptItem, None, {
    "path": Schema.prop(Schema.PATH),
})

FolderScriptItem = Schema.entity("folder_script_item", ScriptItem, None, {
    "folder_path": Schema.prop(Schema.PATH),
    "is_closed": Schema.prop(Schema.BOOLEAN),
})

Profile = Schema.entity("profile", None, 2, {
    "project_references": Schema.array(Schema.component(ProjectReference)),
    "last_project_reference": Schema.reference(ProjectReference),
    "work_project": Schema.reference(ProjectReference),
    "closed_items": Schema.prop(Schema.SET),
    "script_items": Schema.array(Schema.component(ScriptItem)),
})

Profile.rename("target_project", "target_project_reference_uuid")
Profile.rename("work_project", "work_project_reference_uuid")
