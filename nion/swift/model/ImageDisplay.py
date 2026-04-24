from __future__ import annotations

# standard libraries
import copy
import dataclasses
import typing

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.utils import Geometry
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


class ImageDisplayInfo:
    """Represents the information needed to display an image, including the data and calibrations.

    This object is effectively immutable, i.e. outside of caching.
    """
    def __init__(
            self,
            display_calibration_info: DisplayItem.DisplayCalibrationInfo | None,
            display_properties: Persistence.PersistentDictType,
            display_data_info_list: typing.Sequence[DisplayItem.DisplayDataInfo | None],
            display_layers: typing.Sequence[DisplayItem.DisplayLayerInfo],
            graphics: typing.Sequence[Graphics.Graphic],
            graphic_selection: DisplayItem.GraphicSelection | None
    ) -> None:
        self.__display_calibration_info = display_calibration_info
        self.__display_properties = copy.deepcopy(display_properties)
        self.__display_data_info_list = list(display_data_info_list)
        self.__display_layers = list(display_layers)
        self.__graphics = list(graphics)
        self.__graphic_selection = copy.copy(graphic_selection) if graphic_selection else DisplayItem.GraphicSelection()

        # cached values
        self.__image_zoom = typing.cast(float, display_properties.get("image_zoom", 1.0))
        self.__image_position = Geometry.FloatPoint.make(display_properties.get("image_position", (0.5, 0.5)))
        self.__image_canvas_mode = typing.cast(str, display_properties.get("image_canvas_mode", "fit"))

    @property
    def display_calibration_info(self) -> DisplayItem.DisplayCalibrationInfo | None:
        return self.__display_calibration_info

    @property
    def display_layers(self) -> typing.Sequence[DisplayItem.DisplayLayerInfo]:
        return self.__display_layers

    @property
    def display_data_info(self) -> DisplayItem.DisplayDataInfo | None:
        return self.__display_data_info_list[0] if len(self.__display_data_info_list) > 0 else None

    @property
    def graphics(self) -> typing.Sequence[Graphics.Graphic]:
        return self.__graphics

    @property
    def graphic_selection(self) -> DisplayItem.GraphicSelection:
        return self.__graphic_selection

    @property
    def image_zoom(self) -> float:
        return self.__image_zoom

    @property
    def image_position(self) -> Geometry.FloatPoint:
        return self.__image_position

    @property
    def image_canvas_mode(self) -> str:
        return self.__image_canvas_mode

    @property
    def scale_marker_position(self) -> str | None:
        return typing.cast(str | None, self.__display_properties.get("scale_marker_position", None))

    @property
    def scale_marker_text_color(self) -> str | None:
        return typing.cast(str | None, self.__display_properties.get("scale_marker_text_color", None))

    @property
    def scale_marker_background_color(self) -> str | None:
        return typing.cast(str | None, self.__display_properties.get("scale_marker_background_color", None))

    @property
    def data_shape(self) -> Geometry.IntSize | None:
        if self.__display_calibration_info is not None:
            display_data_shape = self.__display_calibration_info.display_data_shape
            if display_data_shape is not None:
                return Geometry.IntSize.make(typing.cast(Geometry.IntSizeTuple, display_data_shape)) if len(display_data_shape) == 2 else None
        return None

    @property
    def dimensional_calibration(self) -> Calibration.Calibration:
        display_data_info = self.display_data_info
        data_metadata = display_data_info.data_metadata if display_data_info else None
        if data_metadata:
            display_calibration_info = self.display_calibration_info
            displayed_dimensional_calibrations = display_calibration_info.displayed_dimensional_calibrations if display_calibration_info else list()
            if len(displayed_dimensional_calibrations) == 0:
                dimensional_calibration = Calibration.Calibration()
            elif len(displayed_dimensional_calibrations) == 1:
                dimensional_calibration = displayed_dimensional_calibrations[0]
            else:
                datum_dimensions = data_metadata.datum_dimension_indexes
                collection_dimensions = data_metadata.collection_dimension_indexes
                if len(datum_dimensions) == 2:
                    if displayed_dimensional_calibrations[-1].units:
                        dimensional_calibration = displayed_dimensional_calibrations[-1]
                    else:
                        dimensional_calibration = data_metadata.dimensional_calibrations[datum_dimensions[-1]]
                elif len(collection_dimensions) > 0:
                    dimensional_calibration = data_metadata.dimensional_calibrations[collection_dimensions[-1]]
                elif len(datum_dimensions) > 0:
                    dimensional_calibration = data_metadata.dimensional_calibrations[datum_dimensions[-1]]
                else:
                    dimensional_calibration = Calibration.Calibration()
            return dimensional_calibration
        return Calibration.Calibration()

    @property
    def frame_info(self) -> FrameInfo:
        display_data_info = self.display_data_info
        data_metadata = display_data_info.data_metadata if display_data_info else None
        if data_metadata:
            return get_frame_info(data_metadata)
        return FrameInfo(0, list())

    def apply_display_data_delta(self, display_data_delta: DisplayItem.DisplayDataDelta) -> ImageDisplayInfo:
        """Apply the display data delta changes to this display info and return a new display info with the changes applied."""

        display_calibration_info = display_data_delta.display_calibration_info if display_data_delta.display_calibration_info_changed else self.__display_calibration_info
        display_properties = copy.deepcopy(display_data_delta.display_properties if display_data_delta.display_properties_changed else self.__display_properties)
        display_data_info_list = list(display_data_delta.display_data_info_list if display_data_delta.display_data_info_list_changed else self.__display_data_info_list)
        display_layers = list(display_data_delta.display_layers_list if display_data_delta.display_layers_list_changed else self.__display_layers)
        graphics = list(display_data_delta.graphics if display_data_delta.graphics_changed else self.__graphics)
        graphic_selection = copy.copy(display_data_delta.graphic_selection if display_data_delta.graphic_selection_changed else self.__graphic_selection)

        return ImageDisplayInfo(display_calibration_info, display_properties, display_data_info_list, display_layers, graphics, graphic_selection)
