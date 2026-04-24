from __future__ import annotations

# standard libraries
import typing

# local libraries
from nion.data import Calibration
from nion.swift.model import DisplayInfo
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.utils import Geometry

if typing.TYPE_CHECKING:
    from nion.swift.model import Persistence


class ImageDisplayInfo(DisplayInfo.DisplayInfo):
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
        super().__init__(display_calibration_info, display_properties, display_data_info_list, display_layers, graphics, graphic_selection)

        # cached values
        self.__image_zoom = typing.cast(float, display_properties.get("image_zoom", 1.0))
        self.__image_position = Geometry.FloatPoint.make(display_properties.get("image_position", (0.5, 0.5)))
        self.__image_canvas_mode = typing.cast(str, display_properties.get("image_canvas_mode", "fit"))

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
        return typing.cast(str | None, self.display_properties.get("scale_marker_position", None))

    @property
    def scale_marker_text_color(self) -> str | None:
        return typing.cast(str | None, self.display_properties.get("scale_marker_text_color", None))

    @property
    def scale_marker_background_color(self) -> str | None:
        return typing.cast(str | None, self.display_properties.get("scale_marker_background_color", None))

    @property
    def data_shape(self) -> Geometry.IntSize | None:
        if self.display_calibration_info is not None:
            display_data_shape = self.display_calibration_info.display_data_shape
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

    def apply_display_info(
            self,
            display_calibration_info: DisplayItem.DisplayCalibrationInfo | None,
            display_properties: Persistence.PersistentDictType,
            display_data_info_list: typing.Sequence[DisplayItem.DisplayDataInfo | None],
            display_layers: typing.Sequence[DisplayItem.DisplayLayerInfo],
            graphics: typing.Sequence[Graphics.Graphic],
            graphic_selection: DisplayItem.GraphicSelection | None
    ) -> DisplayInfo.DisplayInfo:
        return ImageDisplayInfo(display_calibration_info, display_properties, display_data_info_list, display_layers, graphics, graphic_selection)
