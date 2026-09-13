from __future__ import annotations

# standard libraries
import math
import pkgutil
import gettext
import typing

# third party libraries
# None

# local libraries
from nion.data import Calibration
from nion.swift import DisplayPanel
from nion.swift import Inspector
from nion.swift.model import DisplayInfo
from nion.swift.model import DisplayItem
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.ui import Bitmap
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import ListModel
from nion.utils import Model
from nion.utils import ReferenceCounting
from nion.utils import Stream

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

_ = gettext.gettext


_GraphicPropertyCommandModelValueType = typing.TypeVar("_GraphicPropertyCommandModelValueType")


class GraphicPropertyCommandModel(Model.PropertyModel[_GraphicPropertyCommandModelValueType]):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, graphic: Graphics.Graphic,
                 property_name: str, title: str,  command_id: str, read_property_name: str | None = None) -> None:
        read_name = read_property_name if read_property_name else property_name
        super().__init__(getattr(graphic, read_name))
        self.__property_name = property_name
        self.__read_property_name = read_name
        self.__graphic = graphic

        def property_changed_from_user(value: _GraphicPropertyCommandModelValueType | None) -> None:
            if value != getattr(graphic, self.__read_property_name):
                command = DisplayPanel.ChangeGraphicsCommand(document_controller.document_model, display_item, [graphic],
                                                            title=title, command_id=command_id, is_mergeable=True,
                                                            **{self.__property_name: typing.cast(typing.Any, value)})
                command.perform()
                document_controller.push_undo_command(command)
                self.value = getattr(graphic, self.__read_property_name)

        self.on_value_changed = property_changed_from_user
        self.__changed_listener = graphic.property_changed_event.listen(
            ReferenceCounting.weak_partial(GraphicPropertyCommandModel.__property_changed_from_graphic, self))

    def __property_changed_from_graphic(self, name: str) -> None:
        if name == self.__read_property_name:
            self.value = getattr(self.__graphic, self.__read_property_name)



class RadianToDegreeStringConverter(Converter.ConverterLike[float, str]):
    """
        Converter object to convert from radian value to degree string and back.
    """
    def convert(self, value: typing.Optional[float]) -> typing.Optional[str]:
        if value is not None:
            return "{0:.4f}°".format(math.degrees(value))
        return None

    def convert_back(self, value_str: typing.Optional[str]) -> typing.Optional[float]:
        if value_str is not None:
            return math.radians(Converter.FloatToStringConverter().convert_back(value_str) or 0.0)
        return None


class DisplayItemCalibratedDimensionValueModel(Model.ValueModel[str]):
    def __init__(self, property_model: Model.ValueModel[tuple[float, ...]], display_item: DisplayItem.DisplayItem, *, dimension_index: int, is_size: bool, uniform: bool = False, factor: float = 1.0) -> None:
        super().__init__()
        self.__property_model = property_model
        self.__display_item = display_item
        self.__dimension_index = dimension_index
        self.__is_size = is_size
        self.__uniform = uniform
        self.__factor = factor
        display_info = display_item.display_info
        self.__display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_item_listener = Stream.ValueStreamAction(self.__display_item.display_info_stream, ReferenceCounting.weak_partial(self.__class__.__handle_display_info_changed, self))
        self.__property_listener = self.__property_model.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__on_value_changed, self))
        self.__value_str: str | None = None
        self.__update()

    def __get_calibration_and_data_size(self) -> DisplayItem.CalibrationAndDataSize:
        if self.__display_calibration_info:
            return self.__display_calibration_info.get_dimension_calibration_and_data_size(self.__dimension_index, uniform=self.__uniform)
        else:
            return DisplayItem.CalibrationAndDataSize(Calibration.Calibration(), 1)

    def __get_value_str(self) -> str | None:
        value_tuple = self.__property_model.value
        if value_tuple is not None:
            calibration_and_data_size = self.__get_calibration_and_data_size()
            calibration = calibration_and_data_size.calibration
            data_size = calibration_and_data_size.data_size
            if self.__is_size:
                return calibration.convert_to_calibrated_size_str(data_size * value_tuple[self.__dimension_index] * self.__factor, value_range=(0, data_size), samples=data_size)
            else:
                return calibration.convert_to_calibrated_value_str(data_size * value_tuple[self.__dimension_index] * self.__factor, value_range=(0, data_size), samples=data_size)
        return None

    def __update(self) -> None:
        new_value = self.__get_value_str()
        if new_value != self.__value_str:
            self.__value_str = new_value
            self.notify_property_changed("value")

    def __handle_display_info_changed(self, display_info: DisplayInfo.DisplayInfo | None) -> None:
        display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_calibration_info = display_calibration_info
        self.__update()

    def __on_value_changed(self, property: str) -> None:
        self.__update()

    @property
    def value(self) -> str | None:
        return self.__value_str

    @value.setter
    def value(self, value_str: str | None) -> None:
        new_value: float | None = None
        if value_str is not None:
            calibration_and_data_size = self.__get_calibration_and_data_size()
            calibration = calibration_and_data_size.calibration
            data_size = calibration_and_data_size.data_size
            value = Converter.FloatToStringConverter().convert_back(value_str)
            if value is not None:
                if self.__is_size:
                    new_value = calibration.convert_from_calibrated_size(value) / data_size / self.__factor
                else:
                    new_value = calibration.convert_from_calibrated_value(value) / data_size / self.__factor
        value_tuple = self.__property_model.value
        # Only update the model if the value at the dimension has changed.
        if value_tuple is not None and new_value is not None and value_tuple[self.__dimension_index] != new_value:
            value_list = list(value_tuple)
            value_list[self.__dimension_index] = new_value
            self.__property_model.value = tuple(value_list)


class TupleToFloatPropertyElementModel(Model.ValueModel[float]):
    """Model to represent an indexed element of a tuple model."""

    def __init__(self, source: Model.ValueModel[tuple[float, ...]], index: int):
        super().__init__()
        self.__source = source
        self.__index = index
        self.__listener = self.__source.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__on_source_changed, self))

    @property
    def value(self) -> float | None:
        tuple_value = self.__source.value
        return tuple_value[self.__index] if tuple_value else None

    @value.setter
    def value(self, new_value: float | None) -> None:
        if self.value != new_value:
            tuple_value = self.__source.value
            tuple_as_list: list[float] = list(tuple_value) if tuple_value else []
            tuple_as_list[self.__index] = new_value or 0.0
            self.__source.value = tuple(tuple_as_list)

    def __on_source_changed(self, property_name: str) -> None:
        if property_name == "value":
            self.notify_property_changed("value")


class FloatToTuplePropertyElementModel(Model.ValueModel[tuple[float, ...]]):
    """Model to represent an indexed element of a tuple model."""

    def __init__(self, source: Model.ValueModel[float]):
        super().__init__()
        self.__source = source
        self.__listener = self.__source.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__on_source_changed, self))

    @property
    def value(self) -> tuple[float, ...] | None:
        source_value = self.__source.value
        return (source_value,) if isinstance(source_value, float) else None

    @value.setter
    def value(self, new_value: tuple[float, ...] | None) -> None:
        if self.value != new_value:
            self.__source.value = new_value[0] if new_value is not None and len(new_value) > 0 else None

    def __on_source_changed(self, property_name: str) -> None:
        if property_name == "value":
            self.notify_property_changed("value")


class FloatPointToTuplePropertyModel(Model.ValueModel[tuple[float, ...]]):
    """Model to represent a FloatPoint as a tuple model."""

    def __init__(self, source: Model.ValueModel[Geometry.FloatPoint]):
        super().__init__()
        self.__source = source
        self.__listener = self.__source.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__handle_source_changed, self))

    @property
    def value(self) -> tuple[float, ...] | None:
        source_value = self.__source.value
        return (source_value.y, source_value.x) if isinstance(source_value, Geometry.FloatPoint) else None

    @value.setter
    def value(self, new_value: tuple[float, ...] | None) -> None:
        if self.value != new_value:
            self.__source.value = Geometry.FloatPoint(y=new_value[0], x=new_value[1]) if new_value is not None and len(new_value) == 2 else None

    def __handle_source_changed(self, property_name: str) -> None:
        if property_name == "value":
            self.notify_property_changed("value")


class LineLengthModel(Model.PropertyModel[float]):
    def __init__(self, start_model: Model.PropertyModel[Geometry.FloatPoint], end_model: Model.PropertyModel[Geometry.FloatPoint], display_item: DisplayItem.DisplayItem):
        super().__init__()
        self.__start_model = start_model
        self.__end_model = end_model
        display_info = display_item.display_info
        self.__display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_item_listener = Stream.ValueStreamAction(display_item.display_info_stream, ReferenceCounting.weak_partial(self.__class__.__handle_display_info_changed, self))
        self.__start_listener = self.__start_model.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__handle_model_changed, self))
        self.__end_listener = self.__end_model.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__handle_model_changed, self))

    def __get_calibration_and_data_size(self, dimension_index: int) -> DisplayItem.CalibrationAndDataSize:
        if self.__display_calibration_info:
            return self.__display_calibration_info.get_dimension_calibration_and_data_size(dimension_index, uniform=True)
        else:
            return DisplayItem.CalibrationAndDataSize(Calibration.Calibration(), 1)

    def __handle_model_changed(self, property: str) -> None:
        self.notify_property_changed("value")

    def __handle_display_info_changed(self, display_info: DisplayInfo.DisplayInfo | None) -> None:
        display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_calibration_info = display_calibration_info
        self.notify_property_changed("value")

    @property
    def value(self) -> typing.Any:
        start = self.__start_model.value or Geometry.FloatPoint()
        end = self.__end_model.value or Geometry.FloatPoint()
        y_calibration_and_data_size = self.__get_calibration_and_data_size(0)
        x_calibration_and_data_size = self.__get_calibration_and_data_size(1)
        calibrated_start = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(start.y * y_calibration_and_data_size.data_size),
                                               x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(start.x * x_calibration_and_data_size.data_size))
        calibrated_end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(end.y * y_calibration_and_data_size.data_size),
                                             x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(end.x * x_calibration_and_data_size.data_size))
        calibrated_distance = Geometry.distance(calibrated_end, calibrated_start)
        return y_calibration_and_data_size.calibration.convert_calibrated_size_to_str(calibrated_distance)

    @value.setter
    def value(self, target_value: typing.Any) -> None:
        start = self.__start_model.value or Geometry.FloatPoint()
        end = self.__end_model.value or Geometry.FloatPoint()
        y_calibration_and_data_size = self.__get_calibration_and_data_size(0)
        x_calibration_and_data_size = self.__get_calibration_and_data_size(1)
        calibrated_start = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(start.y * y_calibration_and_data_size.data_size),
                                               x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(start.x * x_calibration_and_data_size.data_size))
        calibrated_end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(end.y * y_calibration_and_data_size.data_size),
                                             x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(end.x * x_calibration_and_data_size.data_size))
        delta = calibrated_end - calibrated_start
        angle = -math.atan2(delta.y, delta.x)
        new_calibrated_end = calibrated_start + target_value * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))
        end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_from_calibrated_value(new_calibrated_end.y) / y_calibration_and_data_size.data_size,
                                  x=x_calibration_and_data_size.calibration.convert_from_calibrated_value(new_calibrated_end.x) / x_calibration_and_data_size.data_size)
        self.__end_model.value = end


class LineAngleModel(Model.PropertyModel[float]):
    def __init__(self, start_model: Model.PropertyModel[Geometry.FloatPoint], end_model: Model.PropertyModel[Geometry.FloatPoint], display_item: DisplayItem.DisplayItem):
        super().__init__()
        self.__start_model = start_model
        self.__end_model = end_model
        display_info = display_item.display_info
        self.__display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_item_listener = Stream.ValueStreamAction(display_item.display_info_stream, ReferenceCounting.weak_partial(self.__class__.__handle_display_info_changed, self))
        self.__start_listener = self.__start_model.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__handle_model_changed, self))
        self.__end_listener = self.__end_model.property_changed_event.listen(ReferenceCounting.weak_partial(self.__class__.__handle_model_changed, self))

    def __get_calibration_and_data_size(self, dimension_index: int) -> DisplayItem.CalibrationAndDataSize:
        if self.__display_calibration_info:
            return self.__display_calibration_info.get_dimension_calibration_and_data_size(dimension_index, uniform=True)
        else:
            return DisplayItem.CalibrationAndDataSize(Calibration.Calibration(), 1)

    def __handle_model_changed(self, property: str) -> None:
        self.notify_property_changed("value")

    def __handle_display_info_changed(self, display_info: DisplayInfo.DisplayInfo | None) -> None:
        display_calibration_info = display_info.display_calibration_info if display_info else None
        self.__display_calibration_info = display_calibration_info
        self.notify_property_changed("value")

    @property
    def value(self) -> typing.Any:
        start = self.__start_model.value or Geometry.FloatPoint()
        end = self.__end_model.value or Geometry.FloatPoint()
        y_calibration_and_data_size = self.__get_calibration_and_data_size(0)
        x_calibration_and_data_size = self.__get_calibration_and_data_size(1)
        calibrated_start = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(start.y * y_calibration_and_data_size.data_size),
                                               x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(start.x * x_calibration_and_data_size.data_size))
        calibrated_end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(end.y * y_calibration_and_data_size.data_size),
                                             x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(end.x * x_calibration_and_data_size.data_size))
        calibrated_delta = calibrated_end - calibrated_start
        return RadianToDegreeStringConverter().convert(-math.atan2(calibrated_delta.y, calibrated_delta.x))

    @value.setter
    def value(self, target_value: typing.Any) -> None:
        start = self.__start_model.value or Geometry.FloatPoint()
        end = self.__end_model.value or Geometry.FloatPoint()
        y_calibration_and_data_size = self.__get_calibration_and_data_size(0)
        x_calibration_and_data_size = self.__get_calibration_and_data_size(1)
        calibrated_start = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(start.y * y_calibration_and_data_size.data_size),
                                               x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(start.x * x_calibration_and_data_size.data_size))
        calibrated_end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_to_calibrated_value(end.y * y_calibration_and_data_size.data_size),
                                             x=x_calibration_and_data_size.calibration.convert_to_calibrated_value(end.x * x_calibration_and_data_size.data_size))
        calibrated_distance = Geometry.distance(calibrated_end, calibrated_start)
        angle = RadianToDegreeStringConverter().convert_back(target_value) or 0.0
        new_calibrated_end = calibrated_start + calibrated_distance * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))
        end = Geometry.FloatPoint(y=y_calibration_and_data_size.calibration.convert_from_calibrated_value(new_calibrated_end.y) / y_calibration_and_data_size.data_size,
                                  x=x_calibration_and_data_size.calibration.convert_from_calibrated_value(new_calibrated_end.x) / x_calibration_and_data_size.data_size)
        self.__end_model.value = end


class GraphicsInspectorHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem,
                 graphic: Graphics.Graphic):
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__graphic = graphic
        self._stroke_float_str_converter = Converter.FloatToStringConverter(pass_none=True)
        self._graphic_type_model = Model.PropertyModel[str]()
        self.__set_type_specifics()
        self._graphic_label_model = GraphicPropertyCommandModel[str](document_controller, display_item, graphic, "label", title=_("Change Label"), command_id="change_label")
        self._lock_position_model = GraphicPropertyCommandModel[bool](self.__document_controller, self.__display_item, graphic, "is_position_locked", title=_(f"Change {self._graphic_type_model.value} Position Locked"), command_id=f"change_{self._graphic_type_model.value}_position_locked")
        self._lock_rotation_model = GraphicPropertyCommandModel[bool](self.__document_controller, self.__display_item, graphic, "is_rotation_locked", title=_(f"Change {self._graphic_type_model.value} Rotation Locked"), command_id=f"change_{self._graphic_type_model.value}_rotation_locked")
        self._stroke_color_model = GraphicPropertyCommandModel[str](document_controller, display_item, graphic,"stroke_color", title=_("Change Stroke Color"), command_id="change_stroke_color")
        self._used_stroke_color_model = GraphicPropertyCommandModel[str](document_controller, display_item, graphic,"stroke_color", title=_("Change Stroke Color"), command_id="change_stroke_color", read_property_name="used_stroke_style")
        self._stroke_width_model = GraphicPropertyCommandModel[float](document_controller, display_item, graphic, "stroke_width", title=_("Change Stroke Width"), command_id="change_stroke_width")
        self._fill_color_model = GraphicPropertyCommandModel[str](document_controller, display_item, graphic, "fill_color", title=_("Change Fill Color"), command_id="change_fill_color")
        self._used_fill_color_model = GraphicPropertyCommandModel[str](document_controller, display_item, graphic,"fill_color", title=_("Change Fill Color"), command_id="change_fill_color", read_property_name="used_fill_style")
        self._lock_shape_model = GraphicPropertyCommandModel[bool](self.__document_controller, self.__display_item, graphic,"is_shape_locked", title=_(f"Change {self._graphic_type_model.value} Shape Locked"), command_id=f"change_{self._graphic_type_model.value}_shape_locked")

        u = Declarative.DeclarativeUI()

        title_row = u.create_row(
            u.create_label(text="@binding(_graphic_type_model.value)", width=100),
            u.create_stretch(),
            u.create_line_edit(text="@binding(_graphic_label_model.value)", placeholder_text=_("None"), width=160),
            u.create_spacing(4)
        )

        align_center_icon_data = pkgutil.get_data(__name__, "resources/align_center_48x48.png")
        assert align_center_icon_data is not None
        self._align_center_icon = Bitmap.Bitmap(rgba_bitmap_data=CanvasItem.load_rgba_data_from_bytes(align_center_icon_data, "png"), shape=Geometry.IntSize(width=12, height=12))

        align_row = u.create_row(
            u.create_label(text=_("Align"), text_alignment_vertical="center"),
            u.create_row(
                u.create_push_button(icon="@binding(_align_center_icon)", style="minimal", on_clicked="_align_center_clicked", tool_tip=_("Move Graphic to Center")),
            ),
            u.create_stretch(),
            spacing=12,
            margin_horizontal=6
        )

        pos_shape_row = self.__create_position_and_shape_ui()
        stroke_style_row = self.__create_stroke_style_ui()

        disabled_tooltip_str: typing.Final[str] = _("This does not apply to this graphic type.")

        position_lock_tooltip = str() if self.__graphic.CAN_REPOSITION else disabled_tooltip_str
        shape_lock_tooltip = str() if self.__graphic.CAN_RESHAPE else disabled_tooltip_str
        rotation_lock_tooltip = str() if self.__graphic.CAN_ROTATE else disabled_tooltip_str

        lock_row = u.create_row(
            u.create_label(text=_("Lock"), text_alignment_vertical="center"),
            u.create_check_box(text=_("Position"), checked="@binding(_lock_position_model.value)", enabled=self.__graphic.CAN_REPOSITION, tool_tip=position_lock_tooltip, text_alignment_vertical="center"),
            u.create_check_box(text=_("Shape"), checked="@binding(_lock_shape_model.value)", enabled=self.__graphic.CAN_RESHAPE, tool_tip=shape_lock_tooltip, text_alignment_vertical="center"),
            u.create_check_box(text=_("Rotation"), checked="@binding(_lock_rotation_model.value)", enabled=self.__graphic.CAN_ROTATE, tool_tip=rotation_lock_tooltip, text_alignment_vertical="center"),
            u.create_stretch(),
            spacing=12,
            margin_horizontal=6
        )

        self.ui_view = u.create_column(
            title_row,
            u.create_spacing(4),
            pos_shape_row,
            u.create_spacing(4),
            lock_row,
            u.create_spacing(4),
            align_row,
            u.create_spacing(4),
            stroke_style_row,
            u.create_spacing(12),
            width=280
        )

    def __set_type_specifics(self) -> None:
        if isinstance(self.__graphic, Graphics.PointGraphic):
            self.__shape_and_pos_func = self.__create_point_shape_and_pos
            self._graphic_type_model.value = _("Point")
        elif isinstance(self.__graphic, Graphics.LineProfileGraphic):
            self.__shape_and_pos_func = self.__create_line_profile_shape_and_pos
            self._graphic_type_model.value = _("Line Profile")
        elif isinstance(self.__graphic, Graphics.LineGraphic):
            self.__shape_and_pos_func = self.__create_line_shape_and_pos
            self._graphic_type_model.value = _("Line")
        elif isinstance(self.__graphic, Graphics.RectangleGraphic):
            self.__shape_and_pos_func = self.__create_rectangle_shape_and_pos
            self._graphic_type_model.value = _("Rectangle")
        elif isinstance(self.__graphic, Graphics.EllipseGraphic):
            self.__shape_and_pos_func = self.__create_ellipse_shape_and_pos
            self._graphic_type_model.value = _("Ellipse")
        elif isinstance(self.__graphic, Graphics.IntervalGraphic):
            self.__shape_and_pos_func = self.__create_interval_shape_and_pos
            self._graphic_type_model.value = _("Interval")
        elif isinstance(self.__graphic, Graphics.ChannelGraphic):
            self.__shape_and_pos_func = self.__create_channel_pos
            self._graphic_type_model.value = _("Position")
        elif isinstance(self.__graphic, Graphics.SpotGraphic):
            self.__shape_and_pos_func = self.__create_spot_shape_and_pos
            self._graphic_type_model.value = _("Spot Graphic")
        elif isinstance(self.__graphic, Graphics.WedgeGraphic):
            self.__shape_and_pos_func = self.__create_wedge_shape_and_pos
            self._graphic_type_model.value = _("Angular Graphic")
        elif isinstance(self.__graphic, Graphics.RingGraphic):
            self.__shape_and_pos_func = self.__create_ring_shape_and_pos
            self._graphic_type_model.value = _("Band-Pass Graphic")
        elif isinstance(self.__graphic, Graphics.LatticeGraphic):
            self.__shape_and_pos_func = self.__create_default_shape_and_position_ui
            self._graphic_type_model.value = _("Lattice Graphic")
        else:
            self.__shape_and_pos_func = self.__create_default_shape_and_position_ui
            self._graphic_type_model.value = _("")

    def __create_default_shape_and_position_ui(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        return u.create_column()

    def __create_point_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        position_model = GraphicPropertyCommandModel[tuple[float, ...]](self.__document_controller, self.__display_item, self.__graphic, "position", title=_("Change Position"), command_id="change_point_position")
        self._point_position_x_model = DisplayItemCalibratedDimensionValueModel(position_model, self.__display_item, dimension_index=1, is_size=False)
        self._point_position_y_model = DisplayItemCalibratedDimensionValueModel(position_model, self.__display_item, dimension_index=0, is_size=False)
        return u.create_row(
            u.create_spacing(20),
            u.create_label(text=_("X"), width=26),
            u.create_line_edit(text="@binding(_point_position_x_model.value)", width=98),
            u.create_spacing(8),
            u.create_label(text=_("Y"), width=26),
            u.create_line_edit(text="@binding(_point_position_y_model.value)", width=98),
            u.create_stretch()
        )

    def __create_line_profile_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        display_info = self.__display_item.display_info
        display_calibration_info = display_info.display_calibration_info if display_info else None
        display_data_shape = display_calibration_info.display_data_shape if display_calibration_info else None
        factor = 1.0 / (display_data_shape[0] if display_data_shape is not None else 1)
        line_profile_width_model = GraphicPropertyCommandModel[float](self.__document_controller, self.__display_item, self.__graphic, "width", title=_("Change Width"), command_id="change_line_profile_width")
        self._line_profile_width_model = DisplayItemCalibratedDimensionValueModel(FloatToTuplePropertyElementModel(line_profile_width_model), self.__display_item, dimension_index=0, is_size=True, factor=factor)
        return u.create_column(
            self.__create_line_shape_and_pos(),
            u.create_spacing(4),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Width"), width=52),
                u.create_line_edit(text="@binding(_line_profile_width_model.value)", width=98),
                u.create_stretch()
            )
        )

    def __create_line_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        start_model = GraphicPropertyCommandModel[Geometry.FloatPoint](self.__document_controller, self.__display_item, self.__graphic, "start", title=_("Change Line Start"), command_id="change_line_start")
        end_model = GraphicPropertyCommandModel[Geometry.FloatPoint](self.__document_controller, self.__display_item, self.__graphic, "end", title=_("Change Line End"), command_id="change_line_end")
        start_tuple_model = FloatPointToTuplePropertyModel(start_model)
        end_tuple_model = FloatPointToTuplePropertyModel(end_model)
        self._x0_model = DisplayItemCalibratedDimensionValueModel(start_tuple_model, self.__display_item, dimension_index=1, is_size=False)
        self._y0_model = DisplayItemCalibratedDimensionValueModel(start_tuple_model, self.__display_item, dimension_index=0, is_size=False)
        self._x1_model = DisplayItemCalibratedDimensionValueModel(end_tuple_model, self.__display_item, dimension_index=1, is_size=False)
        self._y1_model = DisplayItemCalibratedDimensionValueModel(end_tuple_model, self.__display_item, dimension_index=0, is_size=False)
        self._length_model = LineLengthModel(start_model, end_model, self.__display_item)
        self._angle_model = LineAngleModel(start_model, end_model, self.__display_item)

        return u.create_column(
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("X0"), width=26),
                u.create_line_edit(text="@binding(_x0_model.value)", width=98),
                u.create_spacing(8),
                u.create_label(text=_("Y0"), width=26),
                u.create_line_edit(text="@binding(_y0_model.value)", width=98),
                u.create_stretch()
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("X1"), width=26),
                u.create_line_edit(text="@binding(_x1_model.value)", width=98),
                u.create_spacing(8),
                u.create_label(text=_("Y1"), width=26),
                u.create_line_edit(text="@binding(_y1_model.value)", width=98),
                u.create_stretch()
            ),
            u.create_spacing(4),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("L"), width=26),
                u.create_line_edit(text="@binding(_length_model.value)", width=98),
                u.create_spacing(8),
                u.create_label(text=_("A"), width=26),
                u.create_line_edit(text="@binding(_angle_model.value)", width=98),
                u.create_stretch()
            )
        )

    def __create_rectangle_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        u = Declarative.DeclarativeUI()
        center_model = GraphicPropertyCommandModel[tuple[float, ...]](self.__document_controller, self.__display_item, self.__graphic, "center", title=_(f"Change {self._graphic_type_model.value} Center"), command_id=f"change_{self._graphic_type_model.value}_center")
        size_model = GraphicPropertyCommandModel[tuple[float, ...]](self.__document_controller, self.__display_item, self.__graphic, "size", title=_(f"Change {self._graphic_type_model.value} Size"), command_id=f"change_{self._graphic_type_model.value}_size")

        self._center_x_model = DisplayItemCalibratedDimensionValueModel(center_model, self.__display_item, dimension_index=1, is_size=False)
        self._center_y_model = DisplayItemCalibratedDimensionValueModel(center_model, self.__display_item, dimension_index=0, is_size=False)
        self._width_model = DisplayItemCalibratedDimensionValueModel(size_model, self.__display_item, dimension_index=1, is_size=True)
        self._height_model = DisplayItemCalibratedDimensionValueModel(size_model, self.__display_item, dimension_index=0, is_size=True)

        self._rotation_model = GraphicPropertyCommandModel[float](self.__document_controller, self.__display_item, self.__graphic, "rotation", title=_(f"Change {self._graphic_type_model.value} Rotation"), command_id=f"change_{self._graphic_type_model.value}_size")

        self._radian_to_degrees_string_converter = RadianToDegreeStringConverter()

        return u.create_column(
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("X"), width=26),
                u.create_line_edit(text="@binding(_center_x_model.value)", width=98),
                u.create_spacing(8),
                u.create_label(text=_("Y"), width=26),
                u.create_line_edit(text="@binding(_center_y_model.value)", width=98),
                u.create_stretch()
            ),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("W"), width=26),
                u.create_line_edit(text="@binding(_width_model.value)", width=98),
                u.create_spacing(8),
                u.create_label(text=_("H"), width=26),
                u.create_line_edit(text="@binding(_height_model.value)", width=98),
                u.create_stretch()
            ),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Rotation (deg)")),
                u.create_spacing(8),
                u.create_line_edit(text="@binding(_rotation_model.value, converter=_radian_to_degrees_string_converter)", width=98),
                u.create_stretch()
            ),
            spacing=4
        )

    def __create_ellipse_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        # same tools as rectangle required
        return self.__create_rectangle_shape_and_pos()

    def __create_interval_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        start_model = GraphicPropertyCommandModel[float](self.__document_controller, self.__display_item, self.__graphic, "start", title=_(f"Change {self._graphic_type_model.value} Start"), command_id=f"change_{self._graphic_type_model.value}_start")
        end_model = GraphicPropertyCommandModel[float](self.__document_controller, self.__display_item, self.__graphic, "end", title=_(f"Change {self._graphic_type_model.value} End"), command_id=f"change_{self._graphic_type_model.value}_end")

        self._start_model = DisplayItemCalibratedDimensionValueModel(FloatToTuplePropertyElementModel(start_model), self.__display_item, dimension_index=-1, is_size=False)
        self._end_model = DisplayItemCalibratedDimensionValueModel(FloatToTuplePropertyElementModel(end_model), self.__display_item, dimension_index=-1, is_size=False)

        u = Declarative.DeclarativeUI()

        return u.create_column(
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Start"), width=52),
                u.create_line_edit(text="@binding(_start_model.value)", width=98),
                u.create_stretch()
            ),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("End"), width=52),
                u.create_line_edit(text="@binding(_end_model.value)", width=98),
                u.create_stretch()
            ),
            spacing=4
        )

    def __create_channel_pos(self) -> Declarative.UIDescriptionResult:
        position_model = GraphicPropertyCommandModel[float](self.__document_controller, self.__display_item, self.__graphic, "position", title=_(f"Change {self._graphic_type_model.value} Position"), command_id=f"change_{self._graphic_type_model.value}_position")

        self._position_model = DisplayItemCalibratedDimensionValueModel(FloatToTuplePropertyElementModel(position_model), self.__display_item, dimension_index=-1, is_size=False)

        u = Declarative.DeclarativeUI()

        return u.create_column(
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Position"), width=52),
                u.create_line_edit(text="@binding(_position_model.value)", width=98),
                u.create_stretch()
            ),
            spacing=4
        )

    def __create_spot_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        # same tools as rectangle required
        return self.__create_rectangle_shape_and_pos()

    def __create_wedge_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        angle_interval_model = GraphicPropertyCommandModel[tuple[float, ...]](self.__document_controller, self.__display_item, self.__graphic, "angle_interval", title=_("Change Angle Interval"), command_id="change_angle_interval")

        self._radian_to_degrees_string_converter = RadianToDegreeStringConverter()
        self._start_angle_model = TupleToFloatPropertyElementModel(angle_interval_model, 0)
        self._end_angle_model = TupleToFloatPropertyElementModel(angle_interval_model, 1)

        u = Declarative.DeclarativeUI()

        return u.create_column(
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Start Angle"), width=60),
                u.create_line_edit(
                    text="@binding(_start_angle_model.value, converter=_radian_to_degrees_string_converter)", width=98),
                u.create_stretch()
            ),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("End Angle"), width=60),
                u.create_line_edit(
                    text="@binding(_end_angle_model.value, converter=_radian_to_degrees_string_converter)", width=98),
                u.create_stretch()
            ),
            spacing=4
        )

    def __on_annular_ring_property_changed(self, property_name: typing.Any) -> None:
        if property_name == "mode":
            new_index = self.__annular_ring_mode_reverse_map.get(str(self.__annular_ring_mode_model.value), 0)
            if self._current_annular_ring_mode_index.value != new_index:
                self._current_annular_ring_mode_index.value = new_index

    def _change_annular_ring_mode(self, widget: Declarative.UIWidget, current_index: int) -> None:
        self.__annular_ring_mode_model.value = self.__annular_ring_mode_ids[current_index]

    def __create_ring_shape_and_pos(self) -> Declarative.UIDescriptionResult:
        radius_1_model = GraphicPropertyCommandModel[float](self.__document_controller, self.__display_item, self.__graphic, "radius_1", title=_("Change Radius 1"), command_id="change_radius_1")
        radius_2_model = GraphicPropertyCommandModel[float](self.__document_controller, self.__display_item, self.__graphic, "radius_2", title=_("Change Radius 2"), command_id="change_radius_2")

        self._radius_1_model = DisplayItemCalibratedDimensionValueModel(FloatToTuplePropertyElementModel(radius_1_model), self.__display_item, dimension_index=0, is_size=True)
        self._radius_2_model = DisplayItemCalibratedDimensionValueModel(FloatToTuplePropertyElementModel(radius_2_model), self.__display_item, dimension_index=0, is_size=True)

        self.__annular_ring_mode_options = [_("Band-Pass"), _("Low-Pass"), _("High-Pass")]
        self.__annular_ring_mode_ids = ["band-pass", "low-pass", "high-pass"]
        self.__annular_ring_mode_reverse_map = {p: i for i, p in enumerate(self.__annular_ring_mode_ids)}

        self.__annular_ring_mode_model = GraphicPropertyCommandModel[str](self.__document_controller, self.__display_item, self.__graphic, "mode", title=_("Change Mode"), command_id="change_mode")

        self._current_annular_ring_mode_index = Model.PropertyModel(
            self.__annular_ring_mode_reverse_map.get(str(self.__annular_ring_mode_model.value), 0))
        self.__annular_ring_property_changed_listener = self.__graphic.property_changed_event.listen(
            ReferenceCounting.weak_partial(GraphicsInspectorHandler.__on_annular_ring_property_changed, self)
        )

        u = Declarative.DeclarativeUI()

        return u.create_column(
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Radius 1"), width=60),
                u.create_line_edit(text="@binding(_radius_1_model.value)", width=98),
                u.create_stretch()
            ),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Radius 2"), width=60),
                u.create_line_edit(text="@binding(_radius_2_model.value)", width=98),
                u.create_stretch()
            ),
            u.create_row(
                u.create_spacing(20),
                u.create_label(text=_("Mode"), width=60),
                u.create_combo_box(items=self.__annular_ring_mode_options,
                                   current_index="@binding(_current_annular_ring_mode_index.value)", on_current_index_changed="_change_annular_ring_mode"),
                u.create_stretch()
            ),
            spacing=4
        )

    def _align_center_clicked(self, widget: typing.Any) -> None:
        action_context = self.__document_controller._get_action_context_for_display_items([self.__display_item], None, graphics=[self.__graphic])
        self.__document_controller.perform_action_in_context("display_panel.center_graphics", action_context)

    def __create_position_and_shape_ui(self) -> Declarative.UIDescriptionResult:
        if self.__shape_and_pos_func is None:
            u = Declarative.DeclarativeUI()
            return u.create_row()
        else:
            return self.__shape_and_pos_func()

    def __create_stroke_style_ui(self) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()

        return u.create_column(
            u.create_row(
                u.create_label(text=_("Stroke Color"), width=80, text_alignment_vertical="vcenter", text_alignment_horizontal="right"),
                u.create_line_edit(text="@binding(_stroke_color_model.value)", placeholder_text=_("None"), width=80),
                {"type": "nionswift.color_chooser", "color": "@binding(_used_stroke_color_model.value)"},
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Stroke Width"), width=80, text_alignment_vertical="vcenter", text_alignment_horizontal="right"),
                u.create_line_edit(text="@binding(_stroke_width_model.value, converter=_stroke_float_str_converter)", placeholder_text="1", width=80),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Fill Color"), width=80, text_alignment_vertical="vcenter", text_alignment_horizontal="right"),
                u.create_line_edit(text="@binding(_fill_color_model.value)", placeholder_text=_("None"), width=80),
                {"type": "nionswift.color_chooser", "color": "@binding(_used_fill_color_model.value)"},
                u.create_stretch(),
                spacing=8
            )
        )

class GraphicsSectionHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem,
                 graphics_model: ListModel.ObservedListModel[DisplayItem.DisplayLayer]):
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self._graphics_model = graphics_model
        self._graphic_handlers: list[GraphicsInspectorHandler] = []
        self._calibration_style_model = Inspector.CalibrationStyleModel(document_controller, display_item, Inspector.DimensionalCalibrationStyleModelAdapter())

        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(
            u.create_column(items="_graphics_model.items", item_component_id="graphic", spacing=4),
            u.create_row(u.create_label(text=_("Display"), width=60), u.create_combo_box(items_ref="@binding(_calibration_style_model.items)", current_index="@binding(_calibration_style_model.index)"), u.create_stretch()),
            u.create_stretch()
        )

    def create_handler(self, component_id: str, container: typing.Optional[Symbolic.ComputationVariable] = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "graphic":
            graphic = typing.cast(Graphics.Graphic, item)
            handler = GraphicsInspectorHandler(self.__document_controller, self.__display_item, graphic)
            self._graphic_handlers.append(handler)
            return handler
        return None


