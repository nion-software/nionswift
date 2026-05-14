from __future__ import annotations

# standard libraries
import copy
import dataclasses
import typing

# local libraries
from nion.data import DataAndMetadata
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift.model import Persistence


@dataclasses.dataclass
class FrameInfo:
    frame_index: int
    info_items: typing.Sequence[str]


def get_frame_info(data_metadata: DataAndMetadata.DataMetadata) -> FrameInfo:
    # extracts the dict from metadata. packages can provide components which get called to extract
    # the metadata and form the info_items and frame_index, if available.
    # allow registered metadata_display components to populate a dictionary
    # the image canvas item will look at "frame_index" and "info_items"
    d: Persistence.PersistentDictType = dict()
    for component in Registry.get_components_by_type("metadata_display"):
        component.populate(d, data_metadata.metadata)
    # pull out the frame_index and info_items keys
    frame_index = d.get("frame_index", 0)
    info_items = d.get("info_items", list[str]())
    return FrameInfo(frame_index, info_items)


class DisplayInfo:
    """Holds a snapshot of display data, calibrations, properties, layers, and graphics.

    Provides display calibration info: calibration metadata for each display data item and calibration styles.

    Provides display properties: a dictionary of properties that may be used for presentation.

    Provides display data info: a list of display data and other properties to display the data.

    Provides display layers: a list of display layers that determine the order and style composite item layers.

    Provides graphics: a list of graphics associated with this display, used for mutating UI elements.

    Provides graphic_renderers: a list of self-contained graphic renderers to draw graphics.

    Provides graphic_selection: a selection of graphics that are selected, for example, by the user in the UI.

    All methods are immutable and do not trigger any lengthy computations.
    """

    def __init__(
            self,
            display_calibration_info: DisplayItem.DisplayCalibrationInfo | None,
            display_properties: typing.Mapping[str, typing.Any],
            display_data_info_list: typing.Sequence[DisplayItem.DisplayDataInfo | None],
            display_layers: typing.Sequence[DisplayItem.DisplayLayerInfo],
            graphics: typing.Sequence[Graphics.Graphic],
            graphic_renderers: typing.Sequence[Graphics.GraphicRenderer],
            graphic_selection: DisplayItem.GraphicSelection | None
    ) -> None:
        self.__display_calibration_info = display_calibration_info
        self.__display_properties = copy.deepcopy(display_properties)
        self.__display_data_info_list = list(display_data_info_list)
        self.__display_layers = list(display_layers)
        self.__graphics = list(graphics)
        self.__graphic_renderers = list(graphic_renderers)
        self.__graphic_selection = copy.copy(graphic_selection) if graphic_selection else DisplayItem.GraphicSelection()

    @property
    def display_calibration_info(self) -> DisplayItem.DisplayCalibrationInfo | None:
        return self.__display_calibration_info

    @property
    def is_valid(self) -> bool:
        return self.__display_calibration_info is not None

    @property
    def display_properties(self) -> typing.Mapping[str, typing.Any]:
        return self.__display_properties

    @property
    def display_data_info_list(self) -> typing.Sequence[DisplayItem.DisplayDataInfo | None]:
        return self.__display_data_info_list

    @property
    def display_data_info(self) -> DisplayItem.DisplayDataInfo | None:
        return self.__display_data_info_list[0] if len(self.__display_data_info_list) > 0 else None

    @property
    def display_layers(self) -> typing.Sequence[DisplayItem.DisplayLayerInfo]:
        return self.__display_layers

    @property
    def graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return self.__graphics

    @property
    def graphic_renderers(self) -> typing.Sequence[Graphics.GraphicRenderer]:
        return self.__graphic_renderers

    @property
    def graphic_selection(self) -> DisplayItem.GraphicSelection:
        return self.__graphic_selection

    @property
    def frame_info(self) -> FrameInfo:
        display_data_info = self.display_data_info
        data_metadata = display_data_info.data_metadata if display_data_info else None
        if data_metadata:
            return get_frame_info(data_metadata)
        return FrameInfo(0, list())
