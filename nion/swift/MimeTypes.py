"""
The MIME types used in the application.
"""
from __future__ import annotations

import json
import typing

from nion.ui import UserInterface
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Persistence

if typing.TYPE_CHECKING:
    from nion.swift.model import DocumentModel


DISPLAY_ITEM_MIME_TYPE = "text/vnd.nionswift.display_item"
DISPLAY_ITEMS_MIME_TYPE = "text/vnd.nionswift.display_items"
DISPLAY_PANEL_MIME_TYPE = "text/vnd.nionswift.display_panel"
DATA_SOURCE_MIME_TYPE = "text/vnd.nionswift.display_source"
GRAPHICS_MIME_TYPE = "text/vnd.nionswift.graphics"
DATA_GROUP_MIME_TYPE = "text/vnd.nionswift.data_group"
LAYER_MIME_TYPE = "text/vnd.nionswift.display_layer"
SVG_MIME_TYPE = "image/svg+xml"


def mime_data_get_data_source(mime_data: UserInterface.MimeData, document_model: DocumentModel.DocumentModel) -> typing.Tuple[typing.Optional[DisplayItem.DisplayItem], typing.Optional[Graphics.Graphic]]:
    display_item = None
    graphic = None
    if mime_data.has_format(DATA_SOURCE_MIME_TYPE):
        data_source_mime_data = json.loads(mime_data.data_as_string(DATA_SOURCE_MIME_TYPE))
        display_item_specifier = Persistence.read_persistent_specifier(data_source_mime_data["display_item_specifier"])
        display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], document_model.resolve_item_specifier(display_item_specifier)) if display_item_specifier else None
        if "graphic_specifier" in data_source_mime_data:
            graphic_specifier = Persistence.read_persistent_specifier(data_source_mime_data["graphic_specifier"])
            graphic = typing.cast(typing.Optional[Graphics.Graphic], document_model.resolve_item_specifier(graphic_specifier)) if graphic_specifier else None
    return display_item, graphic


def mime_data_put_data_source(mime_data: UserInterface.MimeData, display_item: DisplayItem.DisplayItem, graphic: typing.Optional[Graphics.Graphic]) -> None:
    mime_data_content = dict()
    mime_data_content["display_item_specifier"] = Persistence.write_persistent_specifier(display_item.uuid)
    if graphic and graphic.project:
        mime_data_content["graphic_specifier"] = Persistence.write_persistent_specifier(graphic.uuid)
    mime_data.set_data_as_string(DATA_SOURCE_MIME_TYPE, json.dumps(mime_data_content))


def mime_data_get_display_item(mime_data: UserInterface.MimeData, document_model: DocumentModel.DocumentModel) -> typing.Optional[DisplayItem.DisplayItem]:
    display_item = None
    if mime_data.has_format(DISPLAY_ITEM_MIME_TYPE):
        data_source_mime_data = json.loads(mime_data.data_as_string(DISPLAY_ITEM_MIME_TYPE))
        display_item_specifier = Persistence.read_persistent_specifier(data_source_mime_data["display_item_specifier"])
        display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], document_model.resolve_item_specifier(display_item_specifier)) if display_item_specifier else None
    return display_item


def mime_data_get_display_items(mime_data: UserInterface.MimeData, document_model: DocumentModel.DocumentModel) -> typing.List[DisplayItem.DisplayItem]:
    display_items : typing.List[DisplayItem.DisplayItem] = list()
    if mime_data.has_format(DISPLAY_ITEMS_MIME_TYPE):
        data_sources_mime_data = json.loads(mime_data.data_as_string(DISPLAY_ITEMS_MIME_TYPE))
        for data_source_mime_data in data_sources_mime_data:
            display_item_specifier = Persistence.read_persistent_specifier(data_source_mime_data["display_item_specifier"])
            display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], document_model.resolve_item_specifier(display_item_specifier)) if display_item_specifier else None
            if display_item:
                display_items.append(display_item)
    if mime_data.has_format(DISPLAY_ITEM_MIME_TYPE):
        data_source_mime_data = json.loads(mime_data.data_as_string(DISPLAY_ITEM_MIME_TYPE))
        display_item_specifier = Persistence.read_persistent_specifier(data_source_mime_data["display_item_specifier"])
        display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], document_model.resolve_item_specifier(display_item_specifier)) if display_item_specifier else None
        if display_item:
            display_items.append(display_item)
    return display_items


def mime_data_put_display_item(mime_data: UserInterface.MimeData, display_item: DisplayItem.DisplayItem) -> None:
    mime_data_content = {"display_item_specifier": Persistence.write_persistent_specifier(display_item.uuid)}
    mime_data.set_data_as_string(DISPLAY_ITEM_MIME_TYPE, json.dumps(mime_data_content))


def mime_data_put_display_items(mime_data: UserInterface.MimeData, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
    mime_data_content = [{"display_item_specifier": Persistence.write_persistent_specifier(display_item.uuid)} for display_item in display_items]
    mime_data.set_data_as_string(DISPLAY_ITEMS_MIME_TYPE, json.dumps(mime_data_content))


def mime_data_get_graphics(mime_data: UserInterface.MimeData) -> typing.Sequence[Graphics.Graphic]:
    graphics = list()
    if mime_data.has_format(GRAPHICS_MIME_TYPE):
        json_str = mime_data.data_as_string(GRAPHICS_MIME_TYPE)
        graphics_dict = json.loads(json_str)
        for graphic_dict in graphics_dict.get("graphics", list()):
            graphic = Graphics.factory(lambda t: str(graphic_dict["type"]))
            graphic.read_from_mime_data(graphic_dict)
            if graphic:
                graphics.append(graphic)
    return graphics


def mime_data_put_graphics(mime_data: UserInterface.MimeData, graphics: typing.Sequence[Graphics.Graphic]) -> None:
    graphic_dict_list = list()
    for graphic in graphics:
        graphic_dict_list.append(graphic.mime_data_dict())
    graphics_dict = {"graphics": graphic_dict_list}
    mime_data.set_data_as_string(GRAPHICS_MIME_TYPE, json.dumps(graphics_dict))


def mime_data_get_layer(mime_data: UserInterface.MimeData, document_model: DocumentModel.DocumentModel) -> typing.Tuple[Persistence.PersistentDictType, typing.Optional[DisplayItem.DisplayItem]]:
    mime_dict = json.loads(mime_data.data_as_string(LAYER_MIME_TYPE))
    legend_data = mime_dict["legend_data"]
    display_item_specifier = Persistence.read_persistent_specifier(mime_dict["display_item_specifier"])
    display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], document_model.resolve_item_specifier(display_item_specifier)) if display_item_specifier else None
    return legend_data, display_item


def mime_data_put_layer(mime_data: UserInterface.MimeData, index: int, display_item: DisplayItem.DisplayItem, label: typing.Optional[str], fill_color: typing.Optional[str], stroke_color: typing.Optional[str]) -> None:
    legend_data: Persistence.PersistentDictType = {
        "index": index,
    }
    if label:
        legend_data["label"] = label
    if fill_color:
        legend_data["fill_color"] = fill_color
    if stroke_color:
        legend_data["stroke_color"] = stroke_color
    mime_dict = {
        "legend_data": legend_data,
        "display_item_specifier": Persistence.write_persistent_specifier(display_item.uuid)
    }
    mime_data.set_data_as_string(LAYER_MIME_TYPE, json.dumps(mime_dict))


def mime_data_get_panel(mime_data: UserInterface.MimeData, document_model: DocumentModel.DocumentModel) -> typing.Tuple[typing.Optional[DisplayItem.DisplayItem], Persistence.PersistentDictType]:
    display_item = None
    d: Persistence.PersistentDictType = dict()
    if mime_data.has_format(DISPLAY_PANEL_MIME_TYPE):
        d = json.loads(mime_data.data_as_string(DISPLAY_PANEL_MIME_TYPE))
        if "display_item_specifier" in d:
            display_item_specifier = Persistence.read_persistent_specifier(d["display_item_specifier"])
            display_item = typing.cast(typing.Optional[DisplayItem.DisplayItem], document_model.resolve_item_specifier(display_item_specifier)) if display_item_specifier else None
    return display_item, d


def mime_data_put_panel(mime_data: UserInterface.MimeData, display_item: typing.Optional[DisplayItem.DisplayItem], d: Persistence.PersistentDictType) -> None:
    if display_item:
        d = dict(d)
        d["display_item_specifier"] = Persistence.write_persistent_specifier(display_item.uuid)
    mime_data.set_data_as_string(DISPLAY_PANEL_MIME_TYPE, json.dumps(d))
