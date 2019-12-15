# standard libraries
import copy
import gettext
import math
import uuid
import weakref

# third party libraries
import numpy  # for arange
import typing

# local libraries
from nion.swift.model import Changes
from nion.swift.model import Persistence
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Observable

if typing.TYPE_CHECKING:
    from nion.swift.model import Project


_ = gettext.gettext


def rotate_180_around_center(point, center):
    return 2 * center[0] - point[0], 2 * center[1] - point[1]


def angle_between(n, a, b):
    if a > b:
        return b < n < a
    if a < b:
        return math.pi * 2 > n > b or 0 < n < a
    return False


def angle_diff(start_angle, end_angle):
    if end_angle > start_angle and end_angle - start_angle >= math.pi / 2:
        return (math.pi * 2 - end_angle + start_angle + math.pi * 2000) % (math.pi * 2)
    return (start_angle - end_angle + math.pi * 2000) % (math.pi * 2)


def rotate(point: Geometry.FloatPoint, origin: Geometry.FloatPoint, angle: float) -> Geometry.FloatPoint:
    # rotate point counterclockwise around origin by angle (radians)
    # coordinate system x increasing: left to right; y increasing: top to bottom
    # so sign of y is reversed from regular rotation equations, then reversed again on return
    delta = point - origin
    angle_sin = math.sin(angle)
    angle_cos = math.cos(angle)
    return origin + Geometry.FloatPoint(x=delta.x * angle_cos + delta.y * angle_sin,
                                        y=delta.y * angle_cos - delta.x * angle_sin)


def get_length_for_angle(angle: float, bounds: typing.Tuple[float, float]):
    top_right = math.atan2(bounds[1], bounds[0])
    top_left = math.pi - math.atan2(bounds[1], bounds[0])
    bottom_left = math.pi + math.atan2(bounds[1], bounds[0])
    bottom_right = 2 * math.pi - math.atan2(bounds[1], bounds[0])
    if bottom_right <= angle <= math.pi * 2 or top_right >= angle:
        return (bounds[0] / 2) / math.cos(angle)
    if top_right <= angle <= top_left:
        return (bounds[1] / 2) / math.sin(angle)
    if top_left <= angle <= bottom_left:
        return -(bounds[0] / 2) / math.cos(angle)
    if bottom_left <= angle <= bottom_right:
        return -(bounds[1] / 2) / math.sin(angle)


def get_corners(bounds):
    top_right = math.atan2(bounds[0], bounds[1])
    top_left = math.pi - math.atan2(bounds[0], bounds[1])
    bottom_left = math.pi + math.atan2(bounds[0], bounds[1])
    bottom_right = 2 * math.pi - math.atan2(bounds[0], bounds[1])
    return [top_left, bottom_left, top_right, bottom_right]


def get_slope_eq(x, y, angle):
    if (1/2) * math.pi < angle <= math.pi  * (3/2):
        return y >= numpy.tan(-angle) * x
    return y <= numpy.tan(-angle) * x


def extend_line(origin, point, pixels):
    delta = point - origin
    angle = math.atan2(delta.y, delta.x)
    delta_extended = delta + pixels * Geometry.FloatPoint(y=math.sin(angle), x=math.cos(angle))
    return origin + delta_extended


def adjust_rectangle_like(mapping, rotation, is_center_constant_by_default, original, current, part, modifiers, constraints) -> typing.Tuple[Geometry.FloatRect, float]:
    # NOTE: all sizes/points are assumed to be in image coordinates
    o = mapping.map_point_widget_to_image(original)
    p = mapping.map_point_widget_to_image(current)
    delta = p - o if not part[0].startswith("inverted") else o - p
    part_name = part[0] if not part[0].startswith("inverted") else part[0][9:]
    old_rotation = part[2]
    old_origin = mapping.map_point_image_norm_to_image(part[1][0])
    old_size = mapping.map_point_image_norm_to_image(part[1][1])
    old_rect = Geometry.FloatRect(origin=old_origin, size=old_size)
    data_shape = Geometry.FloatSize(height=mapping.data_shape[0], width=mapping.data_shape[1])
    # find the minimum distance of center from origin and bottom corner of data
    min_from_origin = min(old_rect.center.y, old_rect.center.x)
    min_from_full = min(data_shape.height - old_rect.center.y, data_shape.width - old_rect.center.x)
    # now calculate the min/max v/h by adding/subtracting those values from bottom-right
    min_value = min(min_from_origin, min_from_full)
    min_point0 = Geometry.FloatPoint(y=min_value, x=min_value)
    # min_point = old_rect.center - min_point0
    # max_point = old_rect.center + min_point0
    min_v = old_rect.center.y - min_value
    min_h = old_rect.center.x - min_value
    max_v = old_rect.center.y + min_value
    max_h = old_rect.center.x + min_value
    max_abs_delta_v = min(old_rect.center.y, data_shape.height - old_rect.center.y)
    max_abs_delta_h = min(old_rect.center.x, data_shape.width - old_rect.center.x)
    new_bounds = Geometry.FloatRect(origin=old_origin, size=old_size)
    new_rotation = rotation
    if part_name == "top-left" and not "shape" in constraints:  # top left
        delta = rotate(delta, Geometry.FloatPoint(), -rotation)
        new_top_left = old_rect.top_left + delta
        if (bool(modifiers.alt) != bool(is_center_constant_by_default)) or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = Geometry.FloatSize.make(old_rect.center - new_top_left)
                if half_size.height > half_size.width:  # size will be width
                    new_top_left = old_rect.center - Geometry.FloatPoint(y=half_size.width, x=half_size.width)
                else:  # size will be height
                    new_top_left = old_rect.center - Geometry.FloatPoint(y=half_size.height, x=half_size.height)
                if "bounds" in constraints and rotation == 0.0:
                    # now constrain the top-left value
                    new_top_left = Geometry.FloatPoint(y=min(max(new_top_left.y, min_v), max_v), x=min(max(new_top_left.x, min_h), max_h))
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints and rotation == 0.0:
                    new_top_left = Geometry.FloatPoint(y=min(max(new_top_left.y, old_rect.center.y - max_abs_delta_v), old_rect.center.y + max_abs_delta_v), x=min(max(new_top_left.x, old_rect.center.x - max_abs_delta_h), old_rect.center.x + max_abs_delta_h))
            # c + (c - t), c + (c - l)
            new_bottom_right = 2 * old_rect.center - new_top_left
            new_bounds = Geometry.FloatRect(origin=new_top_left, size=new_bottom_right - new_top_left)
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints and rotation == 0.0:
                    # find the minimum distance of bottom-right from origin and opposite corner of data
                    min_from_00 = min(old_rect.bottom, old_rect.right)
                    min_from_11 = min(data_shape.height - old_rect.bottom, data_shape.width - old_rect.right)
                    # now calculate the min/max v/h by adding/subtracting those values from bottom-right
                    min_v = old_rect.bottom - min_from_00
                    max_v = old_rect.bottom + min_from_11
                    min_h = old_rect.right - min_from_00
                    max_h = old_rect.right + min_from_11
                    # now constrain the top-left value
                    new_top_left = Geometry.FloatPoint(y=min(max(new_top_left.y, min_v), max_v), x=min(max(new_top_left.x, min_h), max_h))
                # shape constrained to square; hold bottom right constant
                if old_rect.bottom - new_top_left.y < old_rect.right - new_top_left.x:  # size will be width
                    new_top_left = Geometry.FloatPoint(y=old_rect.bottom - (old_rect.right - new_top_left.x), x=new_top_left.x)
                else:  # size will be height
                    new_top_left = Geometry.FloatPoint(y=new_top_left.y, x=old_rect.right - (old_rect.bottom - new_top_left.y))
            else:
                # shape not constrained; hold bottom right constant
                if "bounds" in constraints and rotation == 0.0:
                    new_top_left = Geometry.FloatPoint(y=min(max(new_top_left.y, 0.0), data_shape.height), x=min(max(new_top_left.x, 0.0), data_shape.width))
            new_bounds = Geometry.FloatRect(origin=new_top_left, size=old_rect.bottom_right - new_top_left)
            rotation_offset = rotate(new_bounds.bottom_right, new_bounds.center, rotation) - rotate(old_rect.bottom_right, old_rect.center, rotation)
            new_bounds -= rotation_offset
    elif part_name == "top-right" and not "shape" in constraints:  # top right
        delta = rotate(delta, Geometry.FloatPoint(), -rotation)
        new_top_right = old_rect.top_right + delta
        if (bool(modifiers.alt) != bool(is_center_constant_by_default)) or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = Geometry.FloatSize(height=old_rect.center.y - new_top_right.y, width=new_top_right.x - old_rect.center.x)
                if half_size.height > half_size.width:  # size will be width
                    new_top_right = old_rect.center - Geometry.FloatPoint(y=-half_size.width, x=half_size.width)
                else:  # size will be height
                    new_top_right = old_rect.center - Geometry.FloatPoint(y=-half_size.height, x=half_size.height)
                if "bounds" in constraints:
                    # now constrain the top-right value
                    new_top_right = Geometry.FloatPoint(y=min(max(new_top_right.y, min_v), max_v), x=min(max(new_top_right.x, min_h), max_h))
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints:
                    new_top_right = Geometry.FloatPoint(y=min(max(new_top_right.y, old_rect.center.y - max_abs_delta_v), old_rect.center.y + max_abs_delta_v), x=min(max(new_top_right.x, old_rect.center.x - max_abs_delta_h), old_rect.center.x + max_abs_delta_h))
            # c + (c - t), c - (r - c)
            new_bottom_left = 2 * old_rect.center - new_top_right
            new_bounds = Geometry.FloatRect(origin=new_top_right, size=new_bottom_left - new_top_right)
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints:
                    # find the minimum distance of bottom-left from bottom-left and opposite corner of data
                    min_from_10 = min(data_shape.height - old_rect.bottom, old_rect.left)
                    min_from_01 = min(old_rect.bottom, data_shape.width - old_rect.left)
                    # now calculate the min/max v/h by adding/subtracting those values from bottom-left
                    min_v = old_rect.bottom - min_from_01
                    max_v = old_rect.bottom + min_from_10
                    min_h = old_rect.left - min_from_10
                    max_h = old_rect.left + min_from_01
                    # now constrain the top-left value
                    new_top_right = Geometry.FloatPoint(y=min(max(new_top_right.y, min_v), max_v), x=min(max(new_top_right.x, min_h), max_h))
                # shape constrained to square; hold bottom left constant
                if old_rect.bottom - new_top_right.y < new_top_right.x - old_rect.left:  # size will be width
                    new_top_right = Geometry.FloatPoint(y=old_rect.bottom - (new_top_right.x - old_rect.left), x=new_top_right.x)
                else:  # size will be height
                    new_top_right = Geometry.FloatPoint(y=new_top_right.y, x=old_rect.left + (old_rect.bottom - new_top_right.y))
            else:
                # shape not constrained; hold bottom left constant
                if "bounds" in constraints:
                    new_top_right = Geometry.FloatPoint(y=min(max(new_top_right.y, 0.0), data_shape.height), x=min(max(new_top_right.x, 0.0), data_shape.width))
            new_bounds = Geometry.FloatRect(origin=Geometry.FloatPoint(y=new_top_right.y, x=old_rect.left), size=Geometry.FloatSize(height=old_rect.bottom - new_top_right.y, width=new_top_right.x - old_rect.left))
            rotation_offset = rotate(new_bounds.bottom_left, new_bounds.center, rotation) - rotate(old_rect.bottom_left, old_rect.center, rotation)
            new_bounds -= rotation_offset
    elif part_name == "bottom-right" and not "shape" in constraints:  # bottom right
        delta = rotate(delta, Geometry.FloatPoint(), -rotation)
        new_bottom_right = old_rect.bottom_right + delta
        if (bool(modifiers.alt) != bool(is_center_constant_by_default)) or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = Geometry.FloatSize.make(new_bottom_right - old_rect.center)
                if half_size.height > half_size.width:  # size will be width
                    new_bottom_right = old_rect.center + Geometry.FloatPoint(y=half_size.width, x=half_size.width)
                else:  # size will be height
                    new_bottom_right = old_rect.center + Geometry.FloatPoint(y=half_size.height, x=half_size.height)
                if "bounds" in constraints:
                    # now constrain the bottom-right value
                    new_bottom_right = Geometry.FloatPoint(y=min(max(new_bottom_right.y, min_v), max_v), x=min(max(new_bottom_right.x, min_h), max_h))
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints:
                    new_bottom_right = Geometry.FloatPoint(y=min(max(new_bottom_right.y, old_rect.center.y - max_abs_delta_v), old_rect.center.y + max_abs_delta_v), x=min(max(new_bottom_right.x, old_rect.center.x - max_abs_delta_h), old_rect.center.x + max_abs_delta_h))
            # c - (b - c), c - (r - c)
            new_top_left = 2 * old_rect.center - new_bottom_right
            new_bounds = Geometry.FloatRect(origin=new_top_left, size=new_bottom_right - new_top_left)
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints:
                    # find the minimum distance of bottom-right from bottom-right and opposite corner of data
                    min_from_00 = min(old_rect.top, old_rect.left)
                    min_from_11 = min(data_shape.height - old_rect.top, data_shape.width - old_rect.left)
                    # now calculate the min/max v/h by adding/subtracting those values from top-right
                    min_v = old_rect.top - min_from_00
                    max_v = old_rect.top + min_from_11
                    min_h = old_rect.left - min_from_00
                    max_h = old_rect.left + min_from_11
                    # now constrain the bottom-left value
                    new_bottom_right = Geometry.FloatPoint(y=min(max(new_bottom_right.y, min_v), max_v), x=min(max(new_bottom_right.x, min_h), max_h))
                # shape constrained to square; hold top left constant
                if new_bottom_right.y - old_rect.top < new_bottom_right.x - old_rect.left:  # size will be width
                    new_bottom_right = Geometry.FloatPoint(y=old_rect.top + (new_bottom_right.x - old_rect.left), x=new_bottom_right.x)
                else:  # size will be height
                    new_bottom_right = Geometry.FloatPoint(y=new_bottom_right.y, x=old_rect.left + (new_bottom_right.y - old_rect.top))
            else:
                # shape not constrained; hold top right constant
                if "bounds" in constraints:
                    new_bottom_right = Geometry.FloatPoint(y=min(max(new_bottom_right.y, 0.0), data_shape.height), x=min(max(new_bottom_right.x, 0.0), data_shape.width))
            new_bounds = Geometry.FloatRect(origin=old_rect.top_left, size=new_bottom_right - old_rect.top_left)
            rotation_offset = rotate(new_bounds.top_left, new_bounds.center, rotation) - rotate(old_rect.top_left, old_rect.center, rotation)
            new_bounds -= rotation_offset
    elif part_name == "bottom-left" and not "shape" in constraints:  # bottom left
        delta = rotate(delta, Geometry.FloatPoint(), -rotation)
        new_bottom_left = old_rect.bottom_left + delta
        if (bool(modifiers.alt) != bool(is_center_constant_by_default)) or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = Geometry.FloatSize(height=new_bottom_left.y - old_rect.center.y, width=old_rect.center.x - new_bottom_left.x)
                if half_size.height > half_size.width:  # size will be width
                    new_bottom_left = old_rect.center + Geometry.FloatPoint(y=half_size.width, x=-half_size.width)
                else:  # size will be height
                    new_bottom_left = old_rect.center + Geometry.FloatPoint(y=half_size.height, x=-half_size.height)
                if "bounds" in constraints:
                    # now constrain the bottom-left value
                    new_bottom_left = Geometry.FloatPoint(y=min(max(new_bottom_left.y, min_v), max_v), x=min(max(new_bottom_left.x, min_h), max_h))
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints:
                    new_bottom_left = Geometry.FloatPoint(y=min(max(new_bottom_left.y, old_rect.center.y - max_abs_delta_v), old_rect.center.y + max_abs_delta_v), x=min(max(new_bottom_left.x, old_rect.center.x - max_abs_delta_h), old_rect.center.x + max_abs_delta_h))
            # c - (b - c), c + (c - l)
            new_top_right = 2 * old_rect.center - new_bottom_left
            new_bounds = Geometry.FloatRect(origin=Geometry.FloatPoint(y=new_top_right.y, x=new_bottom_left.x), size=Geometry.FloatSize(height=new_bottom_left.y - new_top_right.y, width=new_top_right.x - new_bottom_left.x))
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints:
                    # find the minimum distance of top-right from top-right and opposite corner of data
                    min_from_01 = min(old_rect.top, data_shape.width - old_rect.right)
                    min_from_10 = min(data_shape.height - old_rect.top, old_rect.right)
                    # now calculate the min/max v/h by adding/subtracting those values from top-right
                    min_v = old_rect.top - min_from_01
                    max_v = old_rect.top + min_from_10
                    min_h = old_rect.right - min_from_10
                    max_h = old_rect.right + min_from_01
                    # now constrain the top-left value
                    new_bottom_left = Geometry.FloatPoint(y=min(max(new_bottom_left.y, min_v), max_v), x=min(max(new_bottom_left.x, min_h), max_h))
                # shape constrained to square; hold top right constant
                if new_bottom_left.y - old_rect.top < old_rect.right - new_bottom_left.x:  # size will be width
                    new_bottom_left = Geometry.FloatPoint(y=old_rect.top + (old_rect.right - new_bottom_left.x), x=new_bottom_left.x)
                else:  # size will be height
                    new_bottom_left = Geometry.FloatPoint(y=new_bottom_left.y, x=old_rect.right - (new_bottom_left.y - old_rect.top))
            else:
                # shape not constrained; hold top right constant
                if "bounds" in constraints:
                    new_bottom_left = Geometry.FloatPoint(y=min(max(new_bottom_left.y, 0.0), data_shape.height), x=min(max(new_bottom_left.x, 0.0), data_shape.width))
            new_bounds = Geometry.FloatRect(origin=Geometry.FloatPoint(y=old_rect.top, x=new_bottom_left.x), size=Geometry.FloatSize(height=new_bottom_left.y - old_rect.top, width=old_rect.right - new_bottom_left.x))
            rotation_offset = rotate(new_bounds.top_right, new_bounds.center, rotation) - rotate(old_rect.top_right, old_rect.center, rotation)
            new_bounds -= rotation_offset
    elif part_name == "rotate" and not "rotation" in constraints:
        original_delta = o - old_rect.center
        current_delta = p - old_rect.center
        original_angle = math.atan2(-original_delta.y, original_delta.x)
        current_angle = math.atan2(-current_delta.y, current_delta.x)
        new_rotation = old_rotation + (current_angle - original_angle)
        if modifiers.shift:
            new_rotation = 2 * math.pi * int(8 * (new_rotation / (2 * math.pi)) + 0.5) / 8
    elif (part_name == "all" or "shape" in constraints) and not "position" in constraints:
        if modifiers.shift:
            if abs(delta.y) > abs(delta.x):
                origin = Geometry.FloatPoint(y=old_rect.top + delta.y, x=old_rect.left)
            else:
                origin = Geometry.FloatPoint(y=old_rect.top, x=old_rect.left + delta.x)
        else:
            origin = old_rect.top_left + delta
        if "bounds" in constraints:
            origin = min(max(origin.y, 0.0), data_shape.height - old_rect.height), min(max(origin.x, 0.0), data_shape.width - old_rect.width)
        new_bounds = Geometry.FloatRect(origin=origin, size=old_size)
    return (mapping.map_point_image_to_image_norm(new_bounds.origin), mapping.map_size_image_to_image_norm(new_bounds.size)), new_rotation


def draw_ellipse(ctx, cx, cy, rx, ry, stroke_style, fill_style):
    with ctx.saver():
        ra = 0.0  # rotation angle
        ctx.begin_path()
        for i in numpy.arange(0, 2 * math.pi, 0.1):
            x = cx - (ry * 0.5 * math.sin(i)) * math.sin(ra * math.pi) + (rx * 0.5 * math.cos(i)) * math.cos(
                ra * math.pi)
            y = cy + (rx * 0.5 * math.cos(i)) * math.sin(ra * math.pi) + (ry * 0.5 * math.sin(i)) * math.cos(
                ra * math.pi)
            if i == 0:
                ctx.move_to(x, y)
            else:
                ctx.line_to(x, y)
        ctx.close_path()
        ctx.stroke_style = stroke_style
        ctx.stroke()
        ctx.fill_style = fill_style
        ctx.fill()


def draw_arrow(ctx, p1, p2, arrow_size=8):
    angle = math.atan2(p2[0] - p1[0], p2[1] - p1[1])
    ctx.move_to(p2[1], p2[0])
    ctx.line_to(p2[1] - arrow_size * math.cos(angle - math.pi / 6), p2[0] - arrow_size * math.sin(angle - math.pi / 6))
    ctx.move_to(p2[1], p2[0])
    ctx.line_to(p2[1] - arrow_size * math.cos(angle + math.pi / 6), p2[0] - arrow_size * math.sin(angle + math.pi / 6))


class NullModifiers(object):
    def __init__(self):
        self.shift = False
        self.only_shift = False
        self.control = False
        self.only_control = False
        self.alt = False
        self.only_alt = False
        self.option = False
        self.only_option = False
        self.meta = False
        self.only_meta = False
        self.keypad = False
        self.only_keypad = False


# A Graphic object describes visible content, such as a shape, bitmap, video, or a line of text.
class Graphic(Observable.Observable, Persistence.PersistentObject):

    def __init__(self, type):
        super().__init__()
        self.about_to_cascade_delete_event = Event.Event()
        self.define_type(type)
        self.define_property("graphic_id", None, changed=self._property_changed, validate=lambda s: str(s) if s else None)
        self.define_property("source_specifier", changed=self.__source_specifier_changed, key="source_uuid")
        self.define_property("stroke_color", None, changed=self._property_changed)
        self.define_property("fill_color", None, changed=self._property_changed)
        self.define_property("label", changed=self._property_changed, validate=lambda s: str(s) if s else None)
        self.define_property("is_position_locked", False, changed=self._property_changed)
        self.define_property("is_shape_locked", False, changed=self._property_changed)
        self.define_property("is_bounds_constrained", False, changed=self._property_changed)
        self.define_property("role", None, changed=self._property_changed)
        self.__region = None
        self.graphic_changed_event = Event.Event()
        self.label_padding = 4
        self.label_font = "normal 11px serif"
        self.__source_proxy = self.create_item_proxy()

    def close(self) -> None:
        self.__source_proxy.close()
        self.__source_proxy = None
        super().close()

    @property
    def project(self) -> "Project.Project":
        return typing.cast("Project.Project", self.container.container) if self.container else None

    def create_proxy(self) -> Persistence.PersistentObjectProxy:
        return self.project.create_item_proxy(item=self)

    @property
    def item_specifier(self) -> Persistence.PersistentObjectSpecifier:
        return Persistence.PersistentObjectSpecifier(item_uuid=self.uuid, context_uuid=self.project.uuid)

    def prepare_cascade_delete(self) -> typing.List:
        cascade_items = list()
        self.about_to_cascade_delete_event.fire(cascade_items)
        return cascade_items

    def insert_model_item(self, container, name, before_index, item):
        if self.container:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> Changes.UndeleteLog:
        if self.container:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return Changes.UndeleteLog()

    def clone(self) -> "Graphic":
        graphic = copy.deepcopy(self)
        graphic.uuid = self.uuid
        return graphic

    def mime_data_dict(self) -> dict:
        return {
            "type": self.type,
            "stroke_color": self.stroke_color,
            "fill_color": self.fill_color,
            "label": self.label,
            "is_position_locked": self.is_position_locked,
            "is_shape_locked": self.is_shape_locked,
            "is_bounds_constrained": self.is_bounds_constrained,
        }

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        self.stroke_color = graphic_dict.get("stroke_color", self.stroke_color)
        self.fill_color = graphic_dict.get("fill_color", self.fill_color)
        self.label = graphic_dict.get("label", self.label)
        self.is_position_locked = graphic_dict.get("is_position_locked", self.is_position_locked)
        self.is_shape_locked = graphic_dict.get("is_shape_locked", self.is_shape_locked)
        self.is_bounds_constrained = graphic_dict.get("is_bounds_constrained", self.is_bounds_constrained)

    def read_properties_from_dict(self, d: typing.Mapping):
        d = dict(d)
        stroke_color = d.pop("color", "#F80")
        if stroke_color != "#F80":
            d["stroke_color"] = stroke_color
        self.read_from_mime_data(d)

    @property
    def source(self):
        return self.__source_proxy.item

    @source.setter
    def source(self, source):
        self.__source_proxy.item = source
        self.source_specifier = source.project.create_specifier(source).write() if source else None

    def __source_specifier_changed(self, name: str, d: typing.Dict) -> None:
        self.__source_proxy.item_specifier = Persistence.PersistentObjectSpecifier.read(d)

    def _property_changed(self, name, value):
        self.notify_property_changed(name)

    @property
    def used_role(self) -> typing.Optional[str]:
        return self.role

    @property
    def used_stroke_style(self) -> typing.Optional[str]:
        if self.stroke_color:
            return self.stroke_color
        if self.used_role == "fourier_mask":
            return "#F08"
        elif self.used_role == "mask":
            return "#00F"
        return "#F80"

    @property
    def used_fill_style(self) -> typing.Optional[str]:
        if self.fill_color:
            return self.fill_color
        if self.used_role == "fourier_mask":
            return "rgba(255, 0, 127, 0.1)"
        elif self.used_role == "mask":
            return "rgba(0, 0, 255, 0.1)"
        return None

    @property
    def color(self) -> typing.Optional[str]:
        return self.used_stroke_style

    @color.setter
    def color(self, value: typing.Optional[str]) -> None:
        self.stroke_color = value

    @property
    def region(self):
        return self.__region

    def set_region(self, region):
        self.__region = region

    @property
    def _constraints(self):
        constraints = set()
        if self.is_position_locked:
            constraints.add("position")
        if self.is_shape_locked:
            constraints.add("shape")
        if self.is_bounds_constrained:
            constraints.add("bounds")
        return constraints

    def get_mask(self, data_shape: typing.Sequence[int]) -> numpy.ndarray:
        return numpy.zeros(data_shape)

    # test whether points are close
    def test_point(self, p1, p2, radius):
        return math.sqrt(pow(p1[0] - p2[0], 2) + pow(p1[1] - p2[1], 2)) < radius

    # closest point on line
    def get_closest_point_on_line(self, start, end, p):
        c = (p[0] - start[0], p[1] - start[1])
        v = (end[0] - start[0], end[1] - start[1])
        length = math.sqrt(pow(v[0], 2) + pow(v[1], 2))
        if length > 0:
            v = (v[0] / length, v[1] / length)
            t = v[0] * c[0] + v[1] * c[1]
            if t < 0:
                return start
            if t > length:
                return end
            return (start[0] + v[0] * t, start[1] + v[1] * t)
        else:
            return start

    # test whether point is close to line
    def test_line(self, start, end, p, radius):
        cp = self.get_closest_point_on_line(start, end, p)
        return math.sqrt(pow(p[0] - cp[0], 2) + pow(p[1] - cp[1], 2)) < radius

    def test_inside_bounds(self, bounds, p, radius):
        return p[0] > bounds[0][0] and p[0] <= bounds[0][0] + bounds[1][0] and p[1] > bounds[0][1] and p[1] <= bounds[0][1] + bounds[1][1]

    def test_label(self, get_font_metrics_fn, mapping, test_point):
        if self.label:
            padding = self.label_padding
            font = self.label_font
            font_metrics = get_font_metrics_fn(font, self.label)
            text_pos = self.label_position(mapping, font_metrics, padding)
            if text_pos is not None:
                bounds = Geometry.FloatRect.from_center_and_size(text_pos, Geometry.FloatSize(width=font_metrics.width + padding * 2, height=font_metrics.height + padding * 2))
                return self.test_inside_bounds(bounds, test_point, 2)
        return False

    def draw_marker(self, ctx, p, fill_style=None):
        with ctx.saver():
            ctx.fill_style = fill_style if fill_style else '#00FF00'
            ctx.begin_path()
            ctx.move_to(p[1] - 3, p[0] - 3)
            ctx.line_to(p[1] + 3, p[0] - 3)
            ctx.line_to(p[1] + 3, p[0] + 3)
            ctx.line_to(p[1] - 3, p[0] + 3)
            ctx.close_path()
            ctx.fill()

    def draw_label(self, ctx, get_font_metrics_fn, mapping):
        if self.label:
            padding = self.label_padding
            font = self.label_font
            font_metrics = get_font_metrics_fn(font, self.label)
            text_pos = self.label_position(mapping, font_metrics, padding)
            with ctx.saver():
                ctx.begin_path()
                ctx.move_to(text_pos.x - font_metrics.width * 0.5 - padding,
                            text_pos.y - font_metrics.height * 0.5 - padding)
                ctx.line_to(text_pos.x + font_metrics.width * 0.5 + padding,
                            text_pos.y - font_metrics.height * 0.5 - padding)
                ctx.line_to(text_pos.x + font_metrics.width * 0.5 + padding,
                            text_pos.y + font_metrics.height * 0.5 + padding)
                ctx.line_to(text_pos.x - font_metrics.width * 0.5 - padding,
                            text_pos.y + font_metrics.height * 0.5 + padding)
                ctx.close_path()
                ctx.fill_style = "rgba(255, 255, 255, 0.6)"
                ctx.fill()
                ctx.stroke_style = self.used_stroke_style
                ctx.stroke()
                ctx.font = font
                ctx.text_baseline = "middle"
                ctx.text_align = "center"
                ctx.fill_style = "#000"
                ctx.fill_text(self.label, text_pos.x, text_pos.y)

    def notify_property_changed(self, key):
        super().notify_property_changed(key)
        self.graphic_changed_event.fire()

    def nudge(self, mapping, delta):
        raise NotImplementedError()

    def label_position(self, mapping, font_metrics, padding):
        raise NotImplementedError()


class MissingGraphic(Graphic):
    def __init__(self, type):
        super().__init__(type)

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        pass


class RectangleTypeGraphic(Graphic):
    def __init__(self, type, title):
        super().__init__(type)
        self.title = title
        self.define_property("bounds", ((0.0, 0.0), (1.0, 1.0)), validate=self.__validate_bounds, changed=self.__bounds_changed)
        self.define_property("rotation", 0.0, changed=self._property_changed)

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["bounds"] = self.bounds
        d["rotation"] = self.rotation
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.bounds = graphic_dict.get("bounds", self.bounds)
        self.rotation = graphic_dict.get("rotation", self.rotation)

    # accessors

    def __validate_bounds(self, value):
        # normalize
        if value[1][0] < 0:  # height is negative
            value = ((value[0][0] + value[1][0], value[0][1]), (-value[1][0], value[1][1]))
        if value[1][1] < 0:  # width is negative
            value = ((value[0][0], value[0][1] + value[1][1]), (value[1][0], -value[1][1]))
        return (value[0][0], value[0][1]), (value[1][0], value[1][1])

    def __bounds_changed(self, name, value):
        self._property_changed(name, value)
        self._property_changed("center", self.center)
        self._property_changed("size", self.size)

    # dependent property center
    @property
    def center(self):
        return self.bounds[0][0] + self.size[0] * 0.5, self.bounds[0][1] + self.size[1] * 0.5

    @center.setter
    def center(self, center):
        self.bounds = ((center[0] - self.size[0] * 0.5, center[1] - self.size[1] * 0.5), self.size)

    # dependent property size
    @property
    def size(self):
        return self.bounds[1]

    @size.setter
    def size(self, size):
        # keep center the same
        old_origin = self.bounds[0]
        old_size = self.bounds[1]
        origin = old_origin[0] - (size[0] - old_size[0]) * 0.5, old_origin[1] - (size[1] - old_size[1]) * 0.5
        self.bounds = (origin, size)

    @property
    def _bounds(self):  # useful for testing
        center = self.center
        size = self.size
        return Geometry.FloatRect(origin=(center[0] - size[0] * 0.5, center[1] - size[1] * 0.5), size=size)

    @_bounds.setter
    def _bounds(self, bounds):
        self.center = bounds[0][0] + bounds[1][0] * 0.5, bounds[0][1] + bounds[1][1] * 0.5
        self.size = bounds[1]

    @property
    def _rotated_top_left(self):  # useful for testing
        return rotate(self._bounds.top_left, self._bounds.center, self.rotation)

    @property
    def _rotated_top_right(self):  # useful for testing
        return rotate(self._bounds.top_right, self._bounds.center, self.rotation)

    @property
    def _rotated_bottom_right(self):  # useful for testing
        return rotate(self._bounds.bottom_right, self._bounds.center, self.rotation)

    @property
    def _rotated_bottom_left(self):  # useful for testing
        return rotate(self._bounds.bottom_left, self._bounds.center, self.rotation)

    def get_mask(self, data_shape: typing.Sequence[int]) -> numpy.ndarray:
        mask = numpy.zeros(data_shape)
        bounds_int = ((int(data_shape[0] * self.bounds[0][0]), int(data_shape[1] * self.bounds[0][1])),
                      (int(data_shape[0] * self.bounds[1][0]), int(data_shape[1] * self.bounds[1][1])))
        if self.rotation:
            a, b = bounds_int[0][0] + bounds_int[1][0] * 0.5, bounds_int[0][1] + bounds_int[1][1] * 0.5
            y, x = numpy.ogrid[-a:data_shape[0] - a, -b:data_shape[1] - b]
            angle_sin = math.sin(self.rotation)
            angle_cos = math.cos(self.rotation)
            mask_eq = (numpy.fabs(x * angle_cos - y * angle_sin) / (bounds_int[1][1] / 2) <= 1) & (numpy.fabs(y * angle_cos + x * angle_sin) / (bounds_int[1][0] / 2) <= 1)
            mask[mask_eq] = 1
        else:
            mask[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0] + 1,
                 bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1] + 1] = 1
        return mask

    # test point hit
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        test_point = Geometry.FloatPoint.make(test_point)
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        rect = Geometry.FloatRect(origin=origin, size=size)
        top_left = rect.top_left
        top_right = rect.top_right
        bottom_right = rect.bottom_right
        bottom_left = rect.bottom_left
        center = rect.center
        if self.rotation:
            top_left = rotate(top_left, center, self.rotation)
            top_right = rotate(top_right, center, self.rotation)
            bottom_left = rotate(bottom_left, center, self.rotation)
            bottom_right = rotate(bottom_right, center, self.rotation)
        test_point_unrotated = rotate(Geometry.FloatPoint(y=test_point.y, x=test_point.x), center, -self.rotation)
        # top left
        if self.test_point(top_left, test_point, 4):
            return "top-left", True
        # top right
        if self.test_point(top_right, test_point, 4):
            return "top-right", True
        # bottom right
        if self.test_point(bottom_right, test_point, 4):
            return "bottom-right", True
        # bottom left
        if self.test_point(bottom_left, test_point, 4):
            return "bottom-left", True
        # rotate top left
        if self.test_point(extend_line(center, top_left, 14), test_point, 6):
            return "rotate", True
        # rotate top right
        if self.test_point(extend_line(center, top_right, 14), test_point, 6):
            return "rotate", True
        # rotate bottom right
        if self.test_point(extend_line(center, bottom_right, 14), test_point, 6):
            return "rotate", True
        # rotate bottom left
        if self.test_point(extend_line(center, bottom_left, 14), test_point, 6):
            return "rotate", True
        # top line
        if self.test_line(top_left, top_right, test_point, 4):
            return "all", True
        # bottom line
        if self.test_line(bottom_left, bottom_right, test_point, 4):
            return "all", True
        # left line
        if self.test_line(top_left, bottom_left, test_point, 4):
            return "all", True
        # right line
        if self.test_line(top_right, bottom_right, test_point, 4):
            return "all", True
        # center
        if self.test_inside_bounds((origin, size), test_point_unrotated, 4):
            return "all", False
        # label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", False
        # didn't find anything
        return None, None

    def begin_drag(self):
        return (self.bounds, self.rotation)

    def end_drag(self, part_data):
        pass

    # rectangle
    def adjust_part(self, mapping, original, current, part, modifiers):
        raise NotImplementedError()

    def nudge(self, mapping, delta):
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        original = (origin[0] + size[0] * 0.5, origin[1] + size[1] * 0.5)
        current = (original[0] + delta[0], original[1] + delta[1])
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        raise NotImplementedError()


class RectangleGraphic(RectangleTypeGraphic):
    def __init__(self):
        super().__init__("rect-graphic", _("Rectangle"))

    # rectangle
    def adjust_part(self, mapping, original, current, part, modifiers):
        bounds, rotation = adjust_rectangle_like(mapping, self.rotation, False, original, current, part, modifiers, self._constraints)
        if bounds != self.bounds:
            self.bounds = bounds
        if rotation != self.rotation:
            self.rotation = rotation

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        rect = Geometry.FloatRect(origin=origin, size=size)
        top_left = rect.top_left
        top_right = rect.top_right
        bottom_right = rect.bottom_right
        bottom_left = rect.bottom_left
        center = rect.center
        if self.rotation:
            top_left = rotate(top_left, center, self.rotation)
            top_right = rotate(top_right, center, self.rotation)
            bottom_left = rotate(bottom_left, center, self.rotation)
            bottom_right = rotate(bottom_right, center, self.rotation)
        with ctx.saver():
            if self.rotation:
                ctx.translate(center.x, center.y)
                ctx.rotate(-self.rotation)
                ctx.translate(-center.x, -center.y)
            ctx.begin_path()
            ctx.move_to(origin[1], origin[0])
            ctx.line_to(origin[1] + size[1], origin[0])
            ctx.line_to(origin[1] + size[1], origin[0] + size[0])
            ctx.line_to(origin[1], origin[0] + size[0])
            ctx.line_to(origin[1], origin[0])
            ctx.move_to(center.x, rect.top + 10)
            ctx.line_to(center.x, rect.top + 2)
            draw_arrow(ctx, Geometry.FloatPoint(y=rect.top + 10, x=center.x), Geometry.FloatPoint(y=rect.top + 2, x=center.x), arrow_size=4)
            ctx.close_path()
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.stroke()
            ctx.fill_style = self.used_fill_style
            ctx.fill()
        if is_selected:
            self.draw_marker(ctx, top_left)
            self.draw_marker(ctx, top_right)
            self.draw_marker(ctx, bottom_right)
            self.draw_marker(ctx, bottom_left)
            with ctx.saver():
                if self.rotation:
                    ctx.translate(center.x, center.y)
                    ctx.rotate(-self.rotation)
                    ctx.translate(-center.x, -center.y)
                # draw center marker
                mark_size = 8
                if size[0] > mark_size:
                    mid_x = center.x
                    mid_y = center.y
                    ctx.begin_path()
                    ctx.move_to(mid_x - 0.5 * mark_size, mid_y)
                    ctx.line_to(mid_x + 0.5 * mark_size, mid_y)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
                    ctx.fill_style = self.used_fill_style
                    ctx.fill()
                if size[1] > mark_size:
                    mid_x = origin[1] + 0.5 * size[1]
                    mid_y = origin[0] + 0.5 * size[0]
                    ctx.begin_path()
                    ctx.move_to(mid_x, mid_y - 0.5 * mark_size)
                    ctx.line_to(mid_x, mid_y + 0.5 * mark_size)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
                    ctx.fill_style = self.used_fill_style
                    ctx.fill()
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        bounds = Geometry.FloatRect.make(self.bounds)
        p = Geometry.FloatPoint.make(mapping.map_point_image_norm_to_widget(bounds.top_left))
        return p + Geometry.FloatPoint(-font_metrics.height * 0.5 - padding * 2, font_metrics.width * 0.5)


class EllipseGraphic(RectangleTypeGraphic):
    def __init__(self):
        super().__init__("ellipse-graphic", _("Ellipse"))

    def get_mask(self, data_shape: typing.Sequence[int]) -> numpy.ndarray:
        mask = numpy.zeros(data_shape)
        bounds_int = ((int(data_shape[0] * self.bounds[0][0]), int(data_shape[1] * self.bounds[0][1])),
                      (int(data_shape[0] * self.bounds[1][0]), int(data_shape[1] * self.bounds[1][1])))
        a, b = bounds_int[0][0] + bounds_int[1][0] * 0.5, bounds_int[0][1] + bounds_int[1][1] * 0.5
        y, x = numpy.ogrid[-a:data_shape[0] - a, -b:data_shape[1] - b]
        if self.rotation:
            angle_sin = math.sin(self.rotation)
            angle_cos = math.cos(self.rotation)
            mask_eq = ((x * angle_cos - y * angle_sin) ** 2) / ((bounds_int[1][1] / 2) * (bounds_int[1][1] / 2)) + ((y * angle_cos + x * angle_sin) ** 2) / ((bounds_int[1][0] / 2) * (bounds_int[1][0] / 2)) <= 1
        else:
            mask_eq = x*x / ((bounds_int[1][1] / 2) * (bounds_int[1][1] / 2)) + y*y / ((bounds_int[1][0] / 2) * (bounds_int[1][0] / 2)) <= 1
        mask[mask_eq] = 1
        return mask

    # rectangle
    def adjust_part(self, mapping, original, current, part, modifiers):
        bounds, rotation = adjust_rectangle_like(mapping, self.rotation, True, original, current, part, modifiers, self._constraints)
        if bounds != self.bounds:
            self.bounds = bounds
        if rotation != self.rotation:
            self.rotation = rotation

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        rect = Geometry.FloatRect(origin=origin, size=size)
        top_left = rect.top_left
        top_right = rect.top_right
        bottom_right = rect.bottom_right
        bottom_left = rect.bottom_left
        center = rect.center
        if self.rotation:
            top_left = rotate(top_left, center, self.rotation)
            top_right = rotate(top_right, center, self.rotation)
            bottom_left = rotate(bottom_left, center, self.rotation)
            bottom_right = rotate(bottom_right, center, self.rotation)
        with ctx.saver():
            if self.rotation:
                ctx.translate(center.x, center.y)
                ctx.rotate(-self.rotation)
                ctx.translate(-center.x, -center.y)
            ctx.line_width = 1
            draw_ellipse(ctx, origin[1] + size[1] * 0.5, origin[0] + size[0] * 0.5, size[1], size[0], self.used_stroke_style, self.used_fill_style)
            ctx.begin_path()
            ctx.move_to(center.x, rect.top + 10)
            ctx.line_to(center.x, rect.top + 2)
            draw_arrow(ctx, Geometry.FloatPoint(y=rect.top + 10, x=center.x), Geometry.FloatPoint(y=rect.top + 2, x=center.x), arrow_size=4)
            ctx.close_path()
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.stroke()
            ctx.fill_style = self.used_fill_style
            ctx.fill()
        if is_selected:
            self.draw_marker(ctx, top_left)
            self.draw_marker(ctx, top_right)
            self.draw_marker(ctx, bottom_right)
            self.draw_marker(ctx, bottom_left)
            # draw center marker
            with ctx.saver():
                if self.rotation:
                    ctx.translate(center.x, center.y)
                    ctx.rotate(-self.rotation)
                    ctx.translate(-center.x, -center.y)
                mark_size = 8
                if size[0] > mark_size:
                    mid_x = origin[1] + 0.5 * size[1]
                    mid_y = origin[0] + 0.5 * size[0]
                    ctx.begin_path()
                    ctx.move_to(mid_x - 0.5 * mark_size, mid_y)
                    ctx.line_to(mid_x + 0.5 * mark_size, mid_y)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
                if size[1] > mark_size:
                    mid_x = origin[1] + 0.5 * size[1]
                    mid_y = origin[0] + 0.5 * size[0]
                    ctx.begin_path()
                    ctx.move_to(mid_x, mid_y - 0.5 * mark_size)
                    ctx.line_to(mid_x, mid_y + 0.5 * mark_size)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        bounds = Geometry.FloatRect.make(self.bounds)
        p = Geometry.FloatPoint.make(mapping.map_point_image_norm_to_widget(Geometry.FloatPoint(bounds.top, bounds.center.x)))
        return p + Geometry.FloatPoint(-font_metrics.height * 0.5 - padding * 2, 0.0)


class LineTypeGraphic(Graphic):
    def __init__(self, type, title):
        super().__init__(type)
        self.title = title

        def read_vector(persistent_property, properties):
            # read the vector defined by persistent_property from the properties dict.
            start = properties.get("start", (0.0, 0.0))
            end = properties.get("end", (1.0, 1.0))
            return start, end

        def write_vector(persistent_property, properties, value):
            # write the vector (value) defined by persistent_property to the properties dict.
            properties["start"] = value[0]
            properties["end"] = value[1]

        # vector is stored in image normalized coordinates
        self.define_property("vector", ((0.0, 0.0), (1.0, 1.0)), changed=self.__vector_changed, reader=read_vector, writer=write_vector, validate=lambda value: (tuple(value[0]), tuple(value[1])))
        self.define_property("start_arrow_enabled", False, changed=self._property_changed, validate=lambda value: bool(value))
        self.define_property("end_arrow_enabled", False, changed=self._property_changed, validate=lambda value: bool(value))

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["vector"] = self.vector
        d["start_arrow_enabled"] = self.start_arrow_enabled
        d["end_arrow_enabled"] = self.start_arrow_enabled
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.vector = graphic_dict.get("vector", self.vector)
        self.start_arrow_enabled = graphic_dict.get("start_arrow_enabled", self.start_arrow_enabled)
        self.end_arrow_enabled = graphic_dict.get("end_arrow_enabled", self.end_arrow_enabled)

    def read_properties_from_dict(self, d: typing.Mapping):
        super().read_from_mime_data(d)
        start = d.get("start", self.vector[0])
        end = d.get("end", self.vector[1])
        self.vector = (start, end)

    @property
    def start(self):
        return self.vector[0]

    @start.setter
    def start(self, value):
        self.vector = value, self.vector[1]

    @property
    def end(self):
        return self.vector[1]

    @end.setter
    def end(self, value):
        self.vector = self.vector[0], value

    @property
    def _start(self):
        return Geometry.FloatPoint.make(self.start)

    @_start.setter
    def _start(self, value):
        self.start = value

    @property
    def _end(self):
        return Geometry.FloatPoint.make(self.end)

    @_end.setter
    def _end(self, value):
        self.end = value

    @property
    def length(self):
        return Geometry.distance(self.start, self.end)

    @length.setter
    def length(self, value):
        angle = self.angle
        self.end = Geometry.FloatPoint.make(self.start) + value * Geometry.FloatSize(height=-math.sin(angle), width=math.cos(angle))

    @property
    def angle(self):
        delta = Geometry.FloatPoint.make(self.end) - Geometry.FloatPoint.make(self.start)
        return -math.atan2(delta.y, delta.x)

    @angle.setter
    def angle(self, value):
        self.end = Geometry.FloatPoint.make(self.start) + self.length * Geometry.FloatSize(height=-math.sin(value), width=math.cos(value))

    # dependent properties
    def __vector_changed(self, name, value):
        self._property_changed(name, value)
        self.notify_property_changed("start")
        self.notify_property_changed("end")
        self.notify_property_changed("length")
        self.notify_property_changed("angle")

    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        # start point
        if self.test_point(p1, test_point, 4):
            return "start", True
        # end point
        if self.test_point(p2, test_point, 4):
            return "end", True
        # along the line
        if self.test_line(p1, p2, test_point, 4):
            return "all", True
        # label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", False
        # didn't find anything
        return None, None

    def begin_drag(self):
        return (self.start, self.end)

    def end_drag(self, part_data):
        pass

    def adjust_part(self, mapping, original, current, part, modifiers):
        o_image = mapping.map_point_widget_to_image(original)
        p_image = mapping.map_point_widget_to_image(current)
        end_image = mapping.map_point_image_norm_to_image(self.end)
        start_image = mapping.map_point_image_norm_to_image(self.start)
        constraints = self._constraints
        if part[0] == "start" and not "shape" in constraints:
            dy = p_image[0] - end_image[0]
            dx = p_image[1] - end_image[1]
            if modifiers.shift:
                angle_degrees = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_degrees > 60:
                    p_image = (p_image[0], end_image[1])
                elif angle_degrees > 30:
                    if angle_degrees > 45:
                        if dx * dy > 0:
                            p_image = (p_image[0], end_image[1] + dy)
                        else:
                            p_image = (p_image[0], end_image[1] - dy)
                    else:
                        if dx * dy > 0:
                            p_image = (end_image[0] + dx, p_image[1])
                        else:
                            p_image = (end_image[0] - dx, p_image[1])
                else:
                    p_image = (end_image[0], p_image[1])
            start = mapping.map_point_image_to_image_norm(p_image)
            if "bounds" in constraints:
                start = min(max(start[0], 0.0), 1.0), min(max(start[1], 0.0), 1.0)
            self.start = start
        elif part[0] == "end" and not "shape" in constraints:
            dy = p_image[0] - start_image[0]
            dx = p_image[1] - start_image[1]
            if modifiers.shift:
                angle_degrees = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_degrees > 60:
                    p_image = (p_image[0], start_image[1])
                elif angle_degrees > 30:
                    if angle_degrees > 45:
                        if dx * dy > 0:
                            p_image = (p_image[0], start_image[1] + dy)
                        else:
                            p_image = (p_image[0], start_image[1] - dy)
                    else:
                        if dx * dy > 0:
                            p_image = (start_image[0] + dx, p_image[1])
                        else:
                            p_image = (start_image[0] - dx, p_image[1])
                else:
                    p_image = (start_image[0], p_image[1])
            end = mapping.map_point_image_to_image_norm(p_image)
            if "bounds" in constraints:
                end = min(max(end[0], 0.0), 1.0), min(max(end[1], 0.0), 1.0)
            self.end = end
        elif part[0] in ["all", "line"] or "shape" in constraints:
            o = mapping.map_point_widget_to_image_norm(original)
            p = mapping.map_point_widget_to_image_norm(current)
            delta_v = p[0] - o[0]
            delta_h = p[1] - o[1]
            y0 = part[1][0]
            x0 = part[1][1]
            y1 = part[2][0]
            x1 = part[2][1]
            if "bounds" in constraints:
                delta_v = min(max(delta_v, -y0), 1.0 - y0)
                delta_v = min(max(delta_v, -y1), 1.0 - y1)
                delta_h = min(max(delta_h, -x0), 1.0 - x0)
                delta_h = min(max(delta_h, -x1), 1.0 - x1)
            start = (y0 + delta_v, x0 + delta_h)
            end = (y1 + delta_v, x1 + delta_h)
            self.vector = start, end

    def nudge(self, mapping, delta):
        end_image = mapping.map_point_image_norm_to_image(self.end)
        start_image = mapping.map_point_image_norm_to_image(self.start)
        original = ((end_image[0] + start_image[0]) * 0.5, (end_image[1] + start_image[1]) * 0.5)
        current = (original[0] + delta[0], original[1] + delta[1])
        self.adjust_part(mapping, original, current, ("all",) + self.begin_drag(), NullModifiers())

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        raise NotImplementedError()


class LineGraphic(LineTypeGraphic):
    def __init__(self):
        super().__init__("line-graphic", _("Line"))

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        with ctx.saver():
            ctx.begin_path()
            ctx.move_to(p1[1], p1[0])
            ctx.line_to(p2[1], p2[0])
            if self.start_arrow_enabled:
                draw_arrow(ctx, p2, p1)
            if self.end_arrow_enabled:
                draw_arrow(ctx, p1, p2)
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.stroke()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        return Geometry.FloatPoint(y=(p1.y + p2.y) * 0.5, x=(p1.x + p2.x) * 0.5)


class LineProfileGraphic(LineTypeGraphic):
    def __init__(self):
        super().__init__("line-profile-graphic", _("Line Profile"))
        self.define_property("width", 1.0, changed=self._property_changed, validate=lambda value: float(value))
        self.define_property("interval_descriptors", list(), changed=self._property_changed)
        self.end_arrow_enabled = True

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["line_width"] = self.width
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.width = graphic_dict.get("line_width", self.width)

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        w = mapping.map_size_image_to_widget((self.width, 0))[0]
        with ctx.saver():
            ctx.begin_path()
            ctx.move_to(p1[1], p1[0])
            ctx.line_to(p2[1], p2[0])
            if self.start_arrow_enabled:
                draw_arrow(ctx, p2, p1)
            if self.end_arrow_enabled:
                draw_arrow(ctx, p1, p2)
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.stroke()
            length = math.sqrt(math.pow(p2[0] - p1[0],2) + math.pow(p2[1] - p1[1], 2))
            dy = (p2[0] - p1[0]) / length if length > 0 else 0.0
            dx = (p2[1] - p1[1]) / length if length > 0 else 0.0
            if w > 1.0:
                half_width = w * 0.5
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(p1[1] + dy * half_width, p1[0] - dx * half_width)
                    ctx.line_to(p2[1] + dy * half_width, p2[0] - dx * half_width)
                    ctx.line_to(p2[1] - dy * half_width, p2[0] + dx * half_width)
                    ctx.line_to(p1[1] - dy * half_width, p1[0] + dx * half_width)
                    ctx.close_path()
                    ctx.line_width = 1
                    ctx.line_dash = 2
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
            for interval_descriptor in self.interval_descriptors:
                interval = interval_descriptor.get("interval")
                color = interval_descriptor.get("color", self.stroke_color)
                interval_marker_half_width = 4
                if interval:
                    with ctx.saver():
                        pa = p1.x + length * interval[0] * dx, p1.y + length * interval[0] * dy
                        pb = p1.x + length * interval[1] * dx, p1.y + length * interval[1] * dy
                        ctx.begin_path()
                        ctx.move_to(pa[0] + dy * interval_marker_half_width, pa[1] - dx * interval_marker_half_width)
                        ctx.line_to(pa[0] - dy * interval_marker_half_width, pa[1] + dx * interval_marker_half_width)
                        ctx.move_to(pb[0] + dy * interval_marker_half_width, pb[1] - dx * interval_marker_half_width)
                        ctx.line_to(pb[0] - dy * interval_marker_half_width, pb[1] + dx * interval_marker_half_width)
                        ctx.line_width = 1
                        ctx.stroke_style = color
                        ctx.stroke()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        return Geometry.FloatPoint(y=(p1.y + p2.y) * 0.5, x=(p1.x + p2.x) * 0.5)


class PointTypeGraphic(Graphic):
    def __init__(self, type, title):
        super().__init__(type)
        self.title = title
        # start and end points are stored in image normalized coordinates
        self.define_property("position", (0.5, 0.5), changed=self._property_changed, validate=lambda value: tuple(value))

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["position"] = self.position
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.position = graphic_dict.get("position", self.position)

    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        cross_hair_size = 12
        p = mapping.map_point_image_norm_to_widget(self.position)
        bounds = Geometry.FloatRect.from_center_and_size(p, Geometry.FloatSize(width=cross_hair_size * 2,
                                                                               height=cross_hair_size * 2))
        if self.test_inside_bounds(bounds, test_point, 2):
            return "all", True
        # check the label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", False
        # didn't find anything
        return None, None

    def begin_drag(self):
        return (self.position,)

    def end_drag(self, part_data):
        pass

    def adjust_part(self, mapping, original, current, part, modifiers):
        if part[0] in ["all", "point"]:
            o = mapping.map_point_widget_to_image_norm(original)
            p = mapping.map_point_widget_to_image_norm(current)
            delta_v = p[0] - o[0]
            delta_h = p[1] - o[1]
            if modifiers.shift:
                if abs(delta_v) > abs(delta_h):
                    pos = part[1][0] + delta_v, part[1][1]
                else:
                    pos = part[1][0], part[1][1] + delta_h
            else:
                pos = part[1][0] + delta_v, part[1][1] + delta_h
            constraints = self._constraints
            if "bounds" in constraints:
                pos = min(max(pos[0], 0.0), 1.0), min(max(pos[1], 0.0), 1.0)
            if "position" not in constraints:
                self.position = pos

    def nudge(self, mapping, delta):
        pos_image = mapping.map_point_image_norm_to_image(self.position)
        original = pos_image
        current = original + delta
        self.adjust_part(mapping, original, current, ("all",) + self.begin_drag(), NullModifiers())

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        raise NotImplementedError()

    @property
    def _position(self):
        return Geometry.FloatPoint.make(self.position)

    @_position.setter
    def _position(self, value):
        self.position = value


class PointGraphic(PointTypeGraphic):
    def __init__(self):
        super().__init__("point-graphic", _("Point"))
        self.cross_hair_size = 12

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        p = mapping.map_point_image_norm_to_widget(self.position)
        with ctx.saver():
            ctx.begin_path()
            cross_hair_size = self.cross_hair_size
            inner_size = 4
            ctx.move_to(p.x - cross_hair_size, p.y)
            ctx.line_to(p.x - inner_size, p.y)
            ctx.move_to(p.x + inner_size, p.y)
            ctx.line_to(p.x + cross_hair_size, p.y)
            ctx.move_to(p.x, p.y - cross_hair_size)
            ctx.line_to(p.x, p.y - inner_size)
            ctx.move_to(p.x, p.y + inner_size)
            ctx.line_to(p.x, p.y + cross_hair_size)
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.stroke()
            self.draw_label(ctx, get_font_metrics_fn, mapping)
        if is_selected:
            self.draw_marker(ctx, p + Geometry.FloatPoint(cross_hair_size, cross_hair_size))
            self.draw_marker(ctx, p + Geometry.FloatPoint(cross_hair_size, -cross_hair_size))
            self.draw_marker(ctx, p + Geometry.FloatPoint(-cross_hair_size, cross_hair_size))
            self.draw_marker(ctx, p + Geometry.FloatPoint(-cross_hair_size, -cross_hair_size))

    def label_position(self, mapping, font_metrics, padding):
        p = Geometry.FloatPoint.make(mapping.map_point_image_norm_to_widget(self.position))
        return p + Geometry.FloatPoint(-self.cross_hair_size - font_metrics.height * 0.5 - padding * 2, 0.0)


class IntervalGraphic(Graphic):
    def __init__(self):
        super().__init__("interval-graphic")
        self.title = _("Interval")
        # start and end points are stored in channel normalized coordinates
        def read_interval(persistent_property, properties):
            # read the interval defined by persistent_property from the properties dict.
            start = properties.get("start", 0.0)
            end = properties.get("end", 1.0)
            return start, end

        def write_interval(persistent_property, properties, value):
            # write the interval (value) defined by persistent_property to the properties dict.
            properties["start"] = value[0]
            properties["end"] = value[1]

        def validate_interval(interval) -> typing.Tuple[float, float]:
            if interval is not None:
                return float(interval[0]), float(interval[1])
            return (0.0, 1.0)

        # interval is stored in image normalized coordinates
        self.define_property("interval", (0.0, 1.0), changed=self.__interval_changed, reader=read_interval, writer=write_interval, validate=validate_interval)

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["interval"] = self.interval
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.interval = graphic_dict.get("interval", self.interval)

    def read_properties_from_dict(self, d: typing.Mapping):
        super().read_from_mime_data(d)
        start = d.get("start", self.interval[0])
        end = d.get("end", self.interval[1])
        self.interval = (start, end)

    @property
    def start(self):
        return self.interval[0]

    @start.setter
    def start(self, value):
        self.interval = value, self.interval[1]

    @property
    def end(self):
        return self.interval[1]

    @end.setter
    def end(self, value):
        self.interval = self.interval[0], value

    def __interval_changed(self, name, value):
        self._property_changed(name, value)
        self.notify_property_changed("start")
        self.notify_property_changed("end")

    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p1 = mapping.map_point_channel_norm_to_widget(self.start)
        p2 = mapping.map_point_channel_norm_to_widget(self.end)
        # start point
        if abs(test_point.x - p1) < 4:
            return "start", True
        # end point
        if abs(test_point.x - p2) < 4:
            return "end", True
        # along the line
        if test_point.x > p1 - 4 and test_point.x < p2 + 4:
            return "all", False
        # label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", False
        # didn't find anything
        return None, None

    def begin_drag(self):
        return (self.start, self.end)

    def end_drag(self, part_data):
        if self.end < self.start:
            self.start, self.end = self.end, self.start

    def adjust_part(self, mapping, original, current, part, modifiers):
        o = mapping.map_point_widget_to_channel_norm(original)
        p = mapping.map_point_widget_to_channel_norm(current)
        constraints = self._constraints
        if part[0] == "start" and "shape" not in constraints:
            self.start = p
        elif part[0] == "end" and "shape" not in constraints:
            self.end = p
        elif part[0] == "all" and "position" not in constraints:
            self.interval = (part[1] + (p - o), part[2] + (p - o))

    def nudge(self, mapping, delta):
        end_channel = mapping.map_point_channel_norm_to_channel(self.end)
        start_channel = mapping.map_point_channel_norm_to_channel(self.start)
        original = Geometry.FloatPoint(y=0.0, x=(end_channel + start_channel) * 0.5)
        current = original + delta
        self.adjust_part(mapping, original, current, ("all",) + self.begin_drag(), NullModifiers())

    def label_position(self, mapping, font_metrics, padding):
        return None


class ChannelGraphic(Graphic):
    def __init__(self):
        super().__init__("channel-graphic")
        self.title = _("Channel")
        # channel is stored in image normalized coordinates
        self.define_property("position", 0.5, changed=self.__channel_changed, validate=lambda value: float(value))

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["position"] = self.position
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.position = graphic_dict.get("position", self.position)

    def __channel_changed(self, name, value):
        self._property_changed(name, value)

    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p = mapping.map_point_channel_norm_to_widget(self.position)
        if abs(test_point.x - p) < 4:
            return "all", True
        # label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", False
        # didn't find anything
        return None, None

    def begin_drag(self):
        return (self.position,)

    def end_drag(self, part_data):
        pass

    def adjust_part(self, mapping, original, current, part, modifiers):
        o = mapping.map_point_widget_to_channel_norm(original)
        p = mapping.map_point_widget_to_channel_norm(current)
        constraints = self._constraints
        if part[0] == "all" and "position" not in constraints:
            self.position = part[1] + (p - o)

    def nudge(self, mapping, delta):
        position_channel = mapping.map_point_channel_norm_to_channel(self.position)
        original = Geometry.FloatPoint(y=0.0, x=position_channel)
        current = original + delta
        self.adjust_part(mapping, original, current, ("all",) + self.begin_drag(), NullModifiers())

    def label_position(self, mapping, font_metrics, padding):
        return None


class SpotGraphic(Graphic):
    def __init__(self):
        super().__init__("spot-graphic")
        self.title = _("Spot")
        self.define_property("bounds", ((0.0, 0.0), (1.0, 1.0)), validate=self.__validate_bounds, changed=self.__bounds_changed)

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["bounds"] = self.bounds
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.bounds = graphic_dict.get("bounds", self.bounds)

    @property
    def used_role(self) -> typing.Optional[str]:
        return "fourier_mask"

    # accessors

    def __validate_bounds(self, value):
        # normalize
        if value[1][0] < 0:  # height is negative
            value = ((value[0][0] + value[1][0], value[0][1]), (-value[1][0], value[1][1]))
        if value[1][1] < 0:  # width is negative
            value = ((value[0][0], value[0][1] + value[1][1]), (value[1][0], -value[1][1]))
        return (value[0][0], value[0][1]), (value[1][0], value[1][1])

    def __bounds_changed(self, name, value):
        self._property_changed(name, value)
        self._property_changed("center", self.center)
        self._property_changed("size", self.size)

    # dependent property center
    @property
    def center(self):
        return self.bounds[0][0] + self.size[0] * 0.5, self.bounds[0][1] + self.size[1] * 0.5

    @center.setter
    def center(self, center):
        self.bounds = ((center[0] - self.size[0] * 0.5, center[1] - self.size[1] * 0.5), self.size)

    # dependent property size
    @property
    def size(self):
        return self.bounds[1]

    @size.setter
    def size(self, size):
        # keep center the same
        old_origin = self.bounds[0]
        old_size = self.bounds[1]
        origin = old_origin[0] - (size[0] - old_size[0]) * 0.5, old_origin[1] - (size[1] - old_size[1]) * 0.5
        self.bounds = (origin, size)

    @property
    def _bounds(self):  # useful for testing
        center = self.center
        size = self.size
        return Geometry.FloatRect(origin=(center[0] - size[0] * 0.5, center[1] - size[1] * 0.5), size=size)

    @_bounds.setter
    def _bounds(self, bounds):
        self.center = bounds[0][0] + bounds[1][0] * 0.5, bounds[0][1] + bounds[1][1] * 0.5
        self.size = bounds[1]

    def get_mask(self, data_shape: typing.Sequence[int]) -> numpy.ndarray:
        mask = numpy.zeros(data_shape)
        bounds_int = ((int(data_shape[0] * self.bounds[0][0]), int(data_shape[1] * self.bounds[0][1])),
                      (int(data_shape[0] * self.bounds[1][0]), int(data_shape[1] * self.bounds[1][1])))

        if bounds_int[1][0] <= 0 or bounds_int[1][1] <= 0:
            return mask

        a, b = bounds_int[0][0] + bounds_int[1][0] * 0.5, bounds_int[0][1] + bounds_int[1][1] * 0.5
        y, x = numpy.ogrid[-a:data_shape[0] - a, -b:data_shape[1] - b]
        mask_eq1 = x * x / ((bounds_int[1][1] / 2) * (bounds_int[1][1] / 2)) + y * y / ((bounds_int[1][0] / 2) * (bounds_int[1][0] / 2)) <= 1

        rotated_origin = rotate_180_around_center(self.bounds[0], (0.5, 0.5))
        bounds_int = ((int(data_shape[0] * rotated_origin[0]), int(data_shape[1] * rotated_origin[1])),
                      (int(data_shape[0] * self.bounds[1][0]), int(data_shape[1] * self.bounds[1][1])))

        a, b = bounds_int[0][0] - bounds_int[1][0] * 0.5, bounds_int[0][1] - bounds_int[1][1] * 0.5
        y, x = numpy.ogrid[-a:data_shape[0] - a, -b:data_shape[1] - b]
        mask_eq2 = x * x / ((bounds_int[1][1] / 2) * (bounds_int[1][1] / 2)) + y * y / ((bounds_int[1][0] / 2) * (bounds_int[1][0] / 2)) <= 1

        mask[mask_eq1] = 1
        mask[mask_eq2] = 1
        return mask

    # test point hit
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        center = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        top_left = origin
        top_right = origin[0], origin[1] + size[1]
        bottom_right = origin[0] + size[0], origin[1] + size[1]
        bottom_left = origin[0] + size[0], origin[1]
        # top left
        if self.test_point(origin, test_point, 4):
            return "top-left", True
        # top right
        if self.test_point(top_right, test_point, 4):
            return "top-right", True
        # bottom right
        if self.test_point(bottom_right, test_point, 4):
            return "bottom-right", True
        # bottom left
        if self.test_point(bottom_left, test_point, 4):
            return "bottom-left", True
        rotated_center = rotate_180_around_center(origin, center)
        if self.test_point((rotated_center[0] - size[0], rotated_center[1] - size[1]), test_point, 4):
            return "inverted-bottom-right", True
        if self.test_point((rotated_center[0] - size[0], rotated_center[1]), test_point, 4):
            return "inverted-bottom-left", True
        if self.test_point((rotated_center[0], rotated_center[1] - size[1]), test_point, 4):
            return "inverted-top-right", True
        if self.test_point((rotated_center[0], rotated_center[1]), test_point, 4):
            return "inverted-top-left", True
        # top line
        if self.test_line(top_left, top_right, test_point, 4):
            return "all", True
        # bottom line
        if self.test_line(bottom_left, bottom_right, test_point, 4):
            return "all", True
        # left line
        if self.test_line(top_left, bottom_left, test_point, 4):
            return "all", True
        # right line
        if self.test_line(top_right, bottom_right, test_point, 4):
            return "all", True
        # center
        if self.test_inside_bounds((origin, size), test_point, 4):
            return "all", True

        if self.test_inside_bounds(((rotated_center[0] - size[0], rotated_center[1] - size[1]), (size[0], size[1])), test_point, 4):
            return "inverted-all", True

        # label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", True
        # didn't find anything
        return None, None

    def begin_drag(self):
        return (self.bounds, 0.0)

    def end_drag(self, part_data):
        pass

    # rectangle
    def adjust_part(self, mapping, original, current, part, modifiers):
        constraints = self._constraints
        if part[0] not in ("all", "inverted-all"):
            constraints = constraints.union({"position", "square"})
        self.bounds, _ = adjust_rectangle_like(mapping, 0.0, False, original, current, part, modifiers, constraints)

    def nudge(self, mapping, delta):
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        original = (origin[0] + size[0] * 0.5, origin[1] + size[1] * 0.5)
        current = (original[0] + delta[0], original[1] + delta[1])
        self.adjust_part(mapping, original, current, ("all",) + self.begin_drag(), NullModifiers())

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        center = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        with ctx.saver():
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.fill_style = self.used_fill_style
            cx0 = origin[1] + size[1] * 0.5
            cy0 = origin[0] + size[0] * 0.5
            draw_ellipse(ctx, cx0, cy0, size[1], size[0], self.used_stroke_style, self.used_fill_style)
            ctx.stroke_style = self.used_stroke_style
            ctx.fill_style = self.used_fill_style
            cx1 = 2 * center[1] - cx0
            cy1 = 2 * center[0] - cy0
            draw_ellipse(ctx, cx1, cy1, size[1], size[0], self.used_stroke_style, self.used_fill_style)
        if is_selected:
            self.draw_marker(ctx, rotate_180_around_center(origin, center))  # bottom right
            self.draw_marker(ctx, rotate_180_around_center((origin[0] + size[0], origin[1]), center))  # top right
            self.draw_marker(ctx, rotate_180_around_center((origin[0] + size[0], origin[1] + size[1]), center))  # top left
            self.draw_marker(ctx, rotate_180_around_center((origin[0], origin[1] + size[1]), center))  # bottom left

            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            # draw center marker
            mark_size = 8
            if size[0] > mark_size:
                mid_x0 = origin[1] + 0.5 * size[1]
                mid_y0 = origin[0] + 0.5 * size[0]
                mid_y1, mid_x1 = rotate_180_around_center((mid_y0, mid_x0), center)
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(mid_x0 - 0.5 * mark_size, mid_y0)
                    ctx.line_to(mid_x0 + 0.5 * mark_size, mid_y0)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
                    ctx.begin_path()
                    ctx.move_to(mid_x1 - 0.5 * mark_size, mid_y1)
                    ctx.line_to(mid_x1 + 0.5 * mark_size, mid_y1)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
            if size[1] > mark_size:
                mid_x0 = origin[1] + 0.5 * size[1]
                mid_y0 = origin[0] + 0.5 * size[0]
                mid_y1, mid_x1 = rotate_180_around_center((mid_y0, mid_x0), center)
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(mid_x0, mid_y0 - 0.5 * mark_size)
                    ctx.line_to(mid_x0, mid_y0 + 0.5 * mark_size)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
                    ctx.begin_path()
                    ctx.move_to(mid_x1, mid_y1 - 0.5 * mark_size)
                    ctx.line_to(mid_x1, mid_y1 + 0.5 * mark_size)
                    ctx.stroke_style = self.used_stroke_style
                    ctx.stroke()
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        bounds = Geometry.FloatRect.make(self.bounds)
        p = Geometry.FloatPoint.make(mapping.map_point_image_norm_to_widget(Geometry.FloatPoint(bounds.top, bounds.center.x)))
        return p + Geometry.FloatPoint(-font_metrics.height * 0.5 - padding * 2, 0.0)


class WedgeGraphic(Graphic):
    def __init__(self):
        super().__init__("wedge-graphic")
        self.title = _("Wedge")

        def validate_angles(value: typing.Tuple[float, float]) -> typing.Tuple[float, float]:
            start_angle = float(value[0])
            end_angle =  float(value[1])
            return start_angle, end_angle

        self.__first_drag = True
        self.__inverted_drag = False
        self.define_property("angle_interval", (0.0, math.pi), validate=validate_angles, changed=self._property_changed)

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["angle_interval"] = self.angle_interval
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.angle_interval = graphic_dict.get("angle_interval", self.angle_interval)

    @property
    def used_role(self) -> typing.Optional[str]:
        return "fourier_mask"

    @property
    def start_angle(self) -> float:
        return self.angle_interval[0]

    @start_angle.setter
    def start_angle(self, value: float) -> None:
        self.angle_interval = (value, self.angle_interval[1])

    @property
    def end_angle(self) -> float:
        return self.angle_interval[1]

    @end_angle.setter
    def end_angle(self, value: float) -> None:
        self.angle_interval = (self.angle_interval[0], value)

    @property
    def __start_angle_internal(self) -> float:
        return self.start_angle + (math.pi * 2) if self.start_angle < 0 else self.start_angle

    @__start_angle_internal.setter
    def __start_angle_internal(self, value: float) -> None:
        if value < math.pi:
            self.start_angle = value
        else:
            self.start_angle = value - 2 * math.pi

    @property
    def __end_angle_internal(self) -> float:
        return self.end_angle + (math.pi * 2) if self.end_angle < 0 else self.end_angle

    @__end_angle_internal.setter
    def __end_angle_internal(self, value: float) -> None:
        if value < math.pi:
            self.end_angle = value
        else:
            self.end_angle = value - 2 * math.pi

    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point: typing.Tuple[float], move_only: bool) -> typing.Tuple[str, bool]:
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        length = 10000  # safe line length
        center = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        start_line_endpoint = (center[0] + length * math.cos(self.__start_angle_internal + math.pi / 2), center[1] + length * math.sin(self.__start_angle_internal + math.pi / 2))
        end_line_endpoint = (center[0] + length * math.cos(self.__end_angle_internal + math.pi / 2), center[1] + length * math.sin(self.__end_angle_internal + math.pi / 2))
        start_angle_inverted = (self.__start_angle_internal + math.pi) % (math.pi * 2)
        end_angle_inverted = (self.__end_angle_internal + math.pi) % (math.pi * 2)
        start_line_endpoint_inverted = (center[0] + length * math.cos(start_angle_inverted + math.pi / 2),
                                        center[1] + length * math.sin(start_angle_inverted + math.pi / 2))
        end_line_endpoint_inverted = (center[0] + length * math.cos(end_angle_inverted + math.pi / 2),
                                      center[1] + length * math.sin(end_angle_inverted + math.pi / 2))
        angle_from_origin = math.pi - math.atan2(center[0] - test_point[0], center[1] - test_point[1])
        if self.test_line(center, start_line_endpoint, test_point, 4):
            return "start-angle", True
        if self.test_line(center, end_line_endpoint, test_point, 4):
            return "end-angle", True
        if self.test_line(center, start_line_endpoint_inverted, test_point, 4):
            return "inverted-start-angle", True
        if self.test_line(center, end_line_endpoint_inverted, test_point, 4):
            return "inverted-end-angle", True
        if angle_between(angle_from_origin, self.__end_angle_internal, self.__start_angle_internal):
            return "all", True
        if angle_between(angle_from_origin, end_angle_inverted, start_angle_inverted):
            return "inverted-all", True

        # didn't find anything
        return None, None

    def begin_drag(self):
        return self.__start_angle_internal, self.__end_angle_internal

    def end_drag(self, part_data):
        self.__first_drag = False

    def adjust_part(self, mapping, original, current, part, modifiers):
        start_angle_original = part[1]
        end_angle_original = part[2]
        center = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        o_angle = math.pi - math.atan2(center[0] - original[0], center[1] - original[1])
        c_angle = math.pi - math.atan2(center[0] - current[0], center[1] - current[1])
        d_angle = angle_diff(o_angle, c_angle)
        if d_angle > math.pi:
            d_angle = -(math.pi * 2 - d_angle)
        inverted = self.__inverted_drag
        constraints = self._constraints
        if (part[0] == "end-angle" and not inverted) or (part[0] == "inverted-end-angle" and inverted):
            self.__end_angle_internal = c_angle
        elif (part[0] == "start-angle" and not inverted) or (part[0] == "inverted-start-angle" and inverted):
            self.__start_angle_internal = c_angle
        elif part[0] == "all" or part[0] == "inverted-all":
            dtheta = o_angle - c_angle
            self.__start_angle_internal = start_angle_original - dtheta
            self.__end_angle_internal = end_angle_original - dtheta
        elif (part[0] == "inverted-end-angle" and not inverted) or (part[0] == "end-angle" and inverted):
            self.__end_angle_internal = (c_angle + math.pi) % (math.pi * 2)
        elif (part[0] == "inverted-start-angle" and not inverted) or (part[0] == "start-angle" and inverted):
            self.__start_angle_internal = (c_angle + math.pi) % (math.pi * 2)

        diff = angle_diff(self.__end_angle_internal, self.__start_angle_internal)
        if diff > math.pi or diff < 0:
            if part[0].endswith("end-angle"):
                self.__end_angle_internal = self.__start_angle_internal
            else:
                self.__start_angle_internal = self.__end_angle_internal
            self.__inverted_drag = not self.__inverted_drag
        return None, None

    def get_mask(self, data_shape: typing.Sequence[int]) -> numpy.ndarray:
        mask1 = numpy.zeros(data_shape)
        mask2 = numpy.zeros(data_shape)
        bounds_int = ((0, 0), (int(data_shape[0]), int(data_shape[1])))
        a, b = bounds_int[0][0] + bounds_int[1][0] * 0.5, bounds_int[0][1] + bounds_int[1][1] * 0.5
        y, x = numpy.ogrid[-a:data_shape[0] - a, -b:data_shape[1] - b]
        mask1[get_slope_eq(x, y, self.__start_angle_internal)] = 1
        mask1[get_slope_eq(x, y, self.__end_angle_internal)] = 0
        mask1[int(bounds_int[1][0] / 2), int(bounds_int[1][0] / 2)] = 1
        mask2[get_slope_eq(x, y, (self.__start_angle_internal + math.pi) % (math.pi * 2))] = 1
        mask2[get_slope_eq(x, y, (self.__end_angle_internal + math.pi) % (math.pi * 2))] = 0
        return numpy.logical_or(mask1, mask2)

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        center = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        size = mapping.map_size_image_norm_to_widget((1.0, 1.0))
        start_length = get_length_for_angle(self.__start_angle_internal, (size[1], size[0]))
        end_length = get_length_for_angle(self.__end_angle_internal, (size[1], size[0]))
        with ctx.saver():
            for start_angle, end_angle in ((self.__start_angle_internal, self.__end_angle_internal), ((self.__start_angle_internal + math.pi) % (math.pi * 2), (self.__end_angle_internal + math.pi) % (math.pi * 2))):
                ctx.begin_path()
                end_line_endpoint = (center[1] + end_length * math.sin(end_angle + math.pi / 2),center[0] + end_length * math.cos(end_angle + math.pi / 2))
                start_line_endpoint = (center[1] + start_length * math.sin(start_angle + math.pi / 2), center[0] + start_length * math.cos(start_angle + math.pi / 2))
                ctx.move_to(*end_line_endpoint)
                ctx.line_to(center[1], center[0])
                ctx.line_to(*start_line_endpoint)
                corners_to_connect = sorted([x for x in get_corners(size) if angle_between(x, end_angle, start_angle)])
                if len(corners_to_connect) == 2 and corners_to_connect[1] - corners_to_connect[0] > math.pi:
                    temp = corners_to_connect[0]
                    corners_to_connect[0] = corners_to_connect[1]
                    corners_to_connect[1] = temp
                for corner_angle in corners_to_connect:
                    corner_length = get_length_for_angle(corner_angle, (size[1], size[0]))
                    corner_endpoint = (center[1] + corner_length * math.sin(corner_angle + math.pi / 2), center[0] + corner_length * math.cos(corner_angle + math.pi / 2))
                    ctx.line_to(*corner_endpoint)
                ctx.line_to(*end_line_endpoint)
                ctx.line_width = 1
                ctx.stroke_style = self.used_stroke_style
                ctx.fill_style = self.used_fill_style
                ctx.fill()
                ctx.stroke()
        if is_selected:
            self.draw_marker(ctx, center)
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        p1 = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        return Geometry.FloatPoint(y=p1.y, x=p1.x)


class RingGraphic(Graphic):
    def __init__(self):
        super().__init__("ring-graphic")
        self.title = _("Annular Ring")

        def validate_angles(value: float) -> float:
            return abs(float(value))

        self.define_property("radius_1", 0.2, validate=validate_angles, changed=self._property_changed)
        self.define_property("radius_2", 0.2, validate=validate_angles, changed=self._property_changed)
        self.define_property("mode", "band-pass", changed=self._property_changed)

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["radius_1"] = self.radius_1
        d["radius_2"] = self.radius_2
        d["mode"] = self.mode
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.radius_1 = graphic_dict.get("radius_1", self.radius_1)
        self.radius_2 = graphic_dict.get("radius_2", self.radius_2)
        self.mode = graphic_dict.get("mode", self.mode)

    @property
    def used_role(self) -> typing.Optional[str]:
        return "fourier_mask"

    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point: typing.Tuple[float, float], move_only: bool) -> typing.Tuple[str, bool]:
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        top_marker_outer = mapping.map_point_image_norm_to_widget((0.5, 0.5 - self.radius_1))
        left_marker_outer = mapping.map_point_image_norm_to_widget((0.5 - self.radius_1, 0.5))
        right_marker_outer = mapping.map_point_image_norm_to_widget((0.5 + self.radius_1, 0.5))
        bottom_marker_outer = mapping.map_point_image_norm_to_widget((0.5, 0.5 + self.radius_1))
        top_marker_inner = mapping.map_point_image_norm_to_widget((0.5, 0.5 - self.radius_2))
        left_marker_inner = mapping.map_point_image_norm_to_widget((0.5 - self.radius_2, 0.5))
        right_marker_inner = mapping.map_point_image_norm_to_widget((0.5 + self.radius_2, 0.5))
        bottom_marker_inner = mapping.map_point_image_norm_to_widget((0.5, 0.5 + self.radius_2))
        image_norm_test_point = mapping.map_point_widget_to_image_norm(test_point)
        test_radius = math.sqrt((image_norm_test_point[0] - 0.5) ** 2 + (image_norm_test_point[1] - 0.5) ** 2)
        if self.test_point(top_marker_outer, test_point, 4):
            return "radius_1", True
        if self.test_point(bottom_marker_outer, test_point, 4):
            return "radius_1", True
        if self.test_point(left_marker_outer, test_point, 4):
            return "radius_1", True
        if self.test_point(right_marker_outer, test_point, 4):
            return "radius_1", True
        if self.mode == "band-pass":
            if self.test_point(top_marker_inner, test_point, 4):
                return "radius_2", True
            if self.test_point(bottom_marker_inner, test_point, 4):
                return "radius_2", True
            if self.test_point(left_marker_inner, test_point, 4):
                return "radius_2", True
            if self.test_point(right_marker_inner, test_point, 4):
                return "radius_2", True
        if self.mode == "band-pass":
            outer = self.radius_1 if self.radius_1 > self.radius_2 else self.radius_2
            inner = self.radius_1 if self.radius_1 < self.radius_2 else self.radius_2
            if test_radius < outer and test_radius > inner:
                return "all", True
        elif self.mode == "high-pass":
            if test_radius < self.radius_1:
                return "all", True
        elif self.mode == "low-pass":
            if test_radius > self.radius_1:
                return "all", True

        # didn't find anything
        return None, None

    def begin_drag(self):
        return self.radius_1, self.radius_2

    def end_drag(self, part_data):
        pass

    def adjust_part(self, mapping, original, current, part, modifiers):
        current_norm = mapping.map_point_widget_to_image_norm(current)
        radius = math.sqrt((current_norm[1] - 0.5) ** 2 + (current_norm[0] - 0.5) ** 2)
        if part[0] == "radius_1":
            self.radius_1 = radius
        if part[0] == "radius_2":
            self.radius_2 = radius
        return None, None

    def get_mask(self, data_shape: typing.Tuple[int]):
        mask = numpy.zeros(data_shape, dtype=numpy.float)
        bounds_int = ((0, 0), (int(data_shape[0]), int(data_shape[1])))
        a, b = bounds_int[0][0] + bounds_int[1][0] * 0.5, bounds_int[0][1] + bounds_int[1][1] * 0.5
        y, x = numpy.ogrid[-a:data_shape[0] - a, -b:data_shape[1] - b]
        outer_radius = self.radius_1 if self.radius_1 > self.radius_2 else self.radius_2
        inner_radius = self.radius_1 if self.radius_1 < self.radius_2 else self.radius_2
        outer_eq = x * x + y * y <= (bounds_int[1][0] * outer_radius) ** 2
        inner_eq = x * x + y * y <= (bounds_int[1][0] * inner_radius) ** 2
        if self.mode == "band-pass":
            mask[outer_eq] = 1
            mask[inner_eq] = 0
        elif self.mode == "low-pass":
            not_outer_eq = numpy.logical_not(outer_eq)
            mask[not_outer_eq] = 1
        elif self.mode == "high-pass":
            mask[inner_eq] = 1
        else:
            mask = numpy.ones(data_shape)
        return mask

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        center = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        bounds0 = mapping.map_point_image_norm_to_widget((0.0, 0.0))
        bounds1 = mapping.map_point_image_norm_to_widget((1.0, 1.0))
        radius_1_widget = mapping.map_size_image_norm_to_widget((self.radius_1, self.radius_1))
        radius_2_widget = mapping.map_size_image_norm_to_widget((self.radius_2, self.radius_2))
        with ctx.saver():
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            draw_ellipse(ctx, center[1], center[0], radius_1_widget[1] * 2, radius_1_widget[0] * 2, self.used_stroke_style, self.used_fill_style)
            if is_selected:
                self.draw_marker(ctx, (center[0] + radius_1_widget[0], center[1]))
                self.draw_marker(ctx, (center[0] - radius_1_widget[0], center[1]))
                self.draw_marker(ctx, (center[0], center[1] + radius_1_widget[1]))
                self.draw_marker(ctx, (center[0], center[1] - radius_1_widget[1]))
            if not self.mode == "low-pass" and not self.mode == "high-pass":
                ctx.line_width = 1
                ctx.stroke_style = self.used_stroke_style
                draw_ellipse(ctx, center[1], center[0], radius_2_widget[1] * 2, radius_2_widget[0] * 2, self.used_stroke_style, self.used_fill_style)
                if is_selected:
                    self.draw_marker(ctx, (center[0] + radius_2_widget[0], center[1]))
                    self.draw_marker(ctx, (center[0] - radius_2_widget[0], center[1]))
                    self.draw_marker(ctx, (center[0], center[1] + radius_2_widget[1]))
                    self.draw_marker(ctx, (center[0], center[1] - radius_2_widget[1]))
            # draw 2 thick arcs
            ctx.fill_style = self.used_fill_style
            # ctx.stroke_style = "#0000FF"
            # ra = 0.0  # rotation angle
            if self.mode == "band-pass":
                ctx.begin_path()
                for i in numpy.arange(0, 2 * math.pi, 0.1):
                    x = center[1] + radius_1_widget[1] * math.cos(i)
                    y = center[0] + radius_1_widget[0] * math.sin(i)
                    if i == 0:
                        ctx.move_to(x, y)
                    else:
                        ctx.line_to(x, y)
                for i in numpy.arange(0, 2 * math.pi, 0.1):
                    x = center[1] + radius_2_widget[1] * math.cos(2 * math.pi - i)
                    y = center[0] + radius_2_widget[0] * math.sin(2 * math.pi - i)
                    if i == 0:
                        ctx.move_to(x, y)
                    else:
                        ctx.line_to(x, y)
                ctx.close_path()
                ctx.fill()
            elif self.mode == "low-pass":
                ctx.begin_path()
                for i in numpy.arange(0, 2 * math.pi, 0.1):
                    x = center[1] + radius_1_widget[1] * math.cos(i)
                    y = center[0] + radius_1_widget[0] * math.sin(i)
                    if i == 0:
                        ctx.move_to(x, y)
                    else:
                        ctx.line_to(x, y)
                ctx.line_to(bounds1[1], center[0])
                ctx.line_to(bounds1[1], bounds1[0])
                ctx.line_to(bounds0[1], bounds1[0])
                ctx.line_to(bounds0[1], bounds0[0])
                ctx.line_to(bounds1[1], bounds0[0])
                ctx.line_to(bounds1[1], center[0])
                ctx.line_to(center[1] + radius_1_widget[1] * math.cos(6.2), center[0] + radius_1_widget[0] * math.sin(6.2))
                ctx.close_path()
                ctx.fill()
            elif self.mode == "high-pass":
                ctx.begin_path()
                for i in numpy.arange(0, 2 * math.pi, 0.1):
                    x = center[1] + radius_1_widget[1] * math.cos(i)
                    y = center[0] + radius_1_widget[0] * math.sin(i)
                    if i == 0:
                        ctx.move_to(x, y)
                    else:
                        ctx.line_to(x, y)
                ctx.close_path()
                ctx.fill()
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        p1 = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        return Geometry.FloatPoint(y=p1.y, x=p1.x)


class LatticeGraphic(Graphic):
    def __init__(self):
        super().__init__("lattice-graphic")
        self.title = _("Lattice")
        self.define_property("u_pos", (0.5, 0.75), validate=lambda value: tuple(value), changed=self._property_changed)
        self.define_property("v_pos", (0.25, 0.5), validate=lambda value: tuple(value), changed=self._property_changed)
        self.define_property("u_count", 1, changed=self._property_changed)
        self.define_property("v_count", 1, changed=self._property_changed)
        self.define_property("radius", 0.1, changed=self._property_changed)

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["u_pos"] = self.u_pos
        d["v_pos"] = self.v_pos
        d["radius"] = self.radius
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping) -> None:
        super().read_from_mime_data(graphic_dict)
        self.u_pos = graphic_dict.get("u_pos", self.u_pos)
        self.v_pos = graphic_dict.get("v_pos", self.v_pos)
        self.radius = graphic_dict.get("radius", self.radius)

    @property
    def used_role(self) -> typing.Optional[str]:
        return "fourier_mask"

    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point: typing.Tuple[float], move_only: bool) -> typing.Tuple[str, bool]:
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        start = mapping.map_point_image_norm_to_widget(Geometry.FloatPoint(x=0.5, y=0.5))
        u_end = mapping.map_point_image_norm_to_widget(Geometry.FloatPoint.make(self.u_pos))
        v_end = mapping.map_point_image_norm_to_widget(Geometry.FloatPoint.make(self.v_pos))
        # print(f"test {u_end} {v_end} {test_point}")

        radius = self.radius
        size = mapping.map_size_image_norm_to_widget(Geometry.FloatSize(width=radius * 2, height=radius * 2))
        u_bounds = Geometry.FloatRect.from_center_and_size(u_end, size)
        v_bounds = Geometry.FloatRect.from_center_and_size(v_end, size)

        # test u, v centers
        if self.test_point(u_bounds.center, test_point, 4):
            return "u-all", True
        if self.test_point(v_bounds.center, test_point, 4):
            return "v-all", True

        # test u-corners
        if self.test_point(u_bounds.top_left, test_point, 4):
            return "u-top-left", True
        if self.test_point(u_bounds.top_right, test_point, 4):
            return "u-top-right", True
        if self.test_point(u_bounds.bottom_left, test_point, 4):
            return "u-bottom-left", True
        if self.test_point(u_bounds.bottom_right, test_point, 4):
            return "u-bottom-right", True

        # test v-corners
        if self.test_point(v_bounds.top_left, test_point, 4):
            return "v-top-left", True
        if self.test_point(v_bounds.top_right, test_point, 4):
            return "v-top-right", True
        if self.test_point(v_bounds.bottom_left, test_point, 4):
            return "v-bottom-left", True
        if self.test_point(v_bounds.bottom_right, test_point, 4):
            return "v-bottom-right", True

        # test u-boundary
        if self.test_line(u_bounds.top_left, u_bounds.top_right, test_point, 4):
            return "u-all", True
        if self.test_line(u_bounds.bottom_left, u_bounds.bottom_right, test_point, 4):
            return "u-all", True
        if self.test_line(u_bounds.top_left, u_bounds.bottom_left, test_point, 4):
            return "u-all", True
        if self.test_line(u_bounds.top_right, u_bounds.bottom_right, test_point, 4):
            return "u-all", True

        # test v-boundary
        if self.test_line(v_bounds.top_left, v_bounds.top_right, test_point, 4):
            return "v-all", True
        if self.test_line(v_bounds.bottom_left, v_bounds.bottom_right, test_point, 4):
            return "v-all", True
        if self.test_line(v_bounds.top_left, v_bounds.bottom_left, test_point, 4):
            return "v-all", True
        if self.test_line(v_bounds.top_right, v_bounds.bottom_right, test_point, 4):
            return "v-all", True

        # test u, v interiors
        if self.test_inside_bounds(u_bounds, test_point, 4):
            return "u-all", True
        if self.test_inside_bounds(v_bounds, test_point, 4):
            return "v-all", True

        # start point
        if self.test_point(start, test_point, 4):
            return "all", True

        # along the lines
        if self.test_line(start, u_end, test_point, 4):
            return "all", True
        if self.test_line(start, v_end, test_point, 4):
            return "all", True

        # label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", False

        # didn't find anything
        return None, None

    def begin_drag(self):
        return self.u_pos, self.v_pos, self.radius

    def end_drag(self, part_data):
        self.__first_drag = False

    def adjust_part(self, mapping, original, current, part, modifiers):
        p_image = mapping.map_point_widget_to_image(current)
        p_norm = Geometry.FloatPoint.make(mapping.map_point_widget_to_image_norm(current))
        o_norm = Geometry.FloatPoint.make(mapping.map_point_widget_to_image_norm(original))
        delta = p_norm - o_norm
        start_image = mapping.map_point_image_norm_to_image((0.5, 0.5))
        constraints = self._constraints

        radius = part[3]
        size = Geometry.FloatSize(width=radius * 2, height=radius * 2)

        if part[0] == "u-all" and not "shape" in constraints:
            dy = p_image[0] - start_image[0]
            dx = p_image[1] - start_image[1]
            if modifiers.shift:
                angle_degrees = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_degrees > 60:
                    p_image = (p_image[0], start_image[1])
                elif angle_degrees > 30:
                    if angle_degrees > 45:
                        if dx * dy > 0:
                            p_image = (p_image[0], start_image[1] + dy)
                        else:
                            p_image = (p_image[0], start_image[1] - dy)
                    else:
                        if dx * dy > 0:
                            p_image = (start_image[0] + dx, p_image[1])
                        else:
                            p_image = (start_image[0] - dx, p_image[1])
                else:
                    p_image = (start_image[0], p_image[1])
                u_pos = mapping.map_point_image_to_image_norm(p_image)
            else:
                u_pos = Geometry.FloatPoint.make(part[1]) + delta
            if "bounds" in constraints:
                u_pos = min(max(u_pos[0], 0.0), 1.0), min(max(u_pos[1], 0.0), 1.0)
            self.u_pos = u_pos
        elif part[0] == "v-all" and not "shape" in constraints:
            dy = p_image[0] - start_image[0]
            dx = p_image[1] - start_image[1]
            if modifiers.shift:
                angle_degrees = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_degrees > 60:
                    p_image = (p_image[0], start_image[1])
                elif angle_degrees > 30:
                    if angle_degrees > 45:
                        if dx * dy > 0:
                            p_image = (p_image[0], start_image[1] + dy)
                        else:
                            p_image = (p_image[0], start_image[1] - dy)
                    else:
                        if dx * dy > 0:
                            p_image = (start_image[0] + dx, p_image[1])
                        else:
                            p_image = (start_image[0] - dx, p_image[1])
                else:
                    p_image = (start_image[0], p_image[1])
                v_pos = mapping.map_point_image_to_image_norm(p_image)
            else:
                v_pos = Geometry.FloatPoint.make(part[2]) + delta
            if "bounds" in constraints:
                v_pos = min(max(v_pos[0], 0.0), 1.0), min(max(v_pos[1], 0.0), 1.0)
            self.v_pos = v_pos
        elif part[0].startswith("u-") and not "shape" in constraints:
            part_constraints = constraints.union({"position", "square"})
            u_bounds = Geometry.FloatRect.from_center_and_size(part[1], size)
            sub_part = part[0][2:], u_bounds, 0
            part_bounds, _ = adjust_rectangle_like(mapping, 0.0, False, original, current, sub_part, modifiers, part_constraints)
            part_bounds = Geometry.FloatRect.make(part_bounds)
            self.radius = abs(part_bounds.height / 2)
        elif part[0].startswith("v-") and not "shape" in constraints:
            part_constraints = constraints.union({"position", "square"})
            v_bounds = Geometry.FloatRect.from_center_and_size(part[2], size)
            sub_part = part[0][2:], v_bounds, 0
            part_bounds, _ = adjust_rectangle_like(mapping, 0.0, False, original, current, sub_part, modifiers, part_constraints)
            part_bounds = Geometry.FloatRect.make(part_bounds)
            self.radius = abs(part_bounds.height / 2)

        return None, None

    def get_mask(self, data_shape: typing.Sequence[int]) -> numpy.ndarray:
        try:
            mask = numpy.zeros(data_shape)

            start = Geometry.FloatPoint(x=0.5, y=0.5)
            u_pos = Geometry.FloatPoint.make(self.u_pos)
            v_pos = Geometry.FloatPoint.make(self.v_pos)
            radius = self.radius
            size = Geometry.FloatSize(width=radius * 2, height=radius * 2)

            bounds = Geometry.FloatRect.from_tlbr(0, 0, 1, 1).inset(-radius, -radius)
            mx = 0
            drawn = True
            while drawn and mx < 32:
                drawn = False
                for ui in range(-mx, mx + 1):
                    for vi in range(-mx, mx + 1):
                        if ui == -mx or ui == mx or vi == -mx or vi == mx:
                            p = start + ui * (u_pos - start) + vi * (v_pos - start)
                            if bounds.contains_point(p):

                                bounds_int = ((int(data_shape[0] * (p[0] - radius)), int(data_shape[1] * (p[1] - radius))),
                                              (int(data_shape[0] * size[0]), int(data_shape[1] * size[1])))

                                if bounds_int[1][0] > 0 and bounds_int[1][1] > 0:
                                    a, b = bounds_int[0][0] + bounds_int[1][0] * 0.5, bounds_int[0][1] + bounds_int[1][1] * 0.5
                                    y, x = numpy.ogrid[-a:data_shape[0] - a, -b:data_shape[1] - b]
                                    mask_eq1 = x * x / ((bounds_int[1][1] / 2) * (bounds_int[1][1] / 2)) + y * y / ((bounds_int[1][0] / 2) * (bounds_int[1][0] / 2)) <= 1

                                    mask[mask_eq1] = 1

                                drawn = True
                mx += 1

            return mask
        except Exception as e:
            print(e)

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        start = Geometry.FloatPoint(x=0.5, y=0.5)
        u_pos = Geometry.FloatPoint.make(self.u_pos)
        v_pos = Geometry.FloatPoint.make(self.v_pos)
        radius = self.radius
        size = Geometry.FloatSize(width=radius * 2, height=radius * 2)
        start_widget = mapping.map_point_image_norm_to_widget(start)
        u_pos_widget = mapping.map_point_image_norm_to_widget(u_pos)
        v_pos_widget = mapping.map_point_image_norm_to_widget(v_pos)
        size_widget = mapping.map_size_image_norm_to_widget(size)
        with ctx.saver():
            ctx.begin_path()
            ctx.move_to(start_widget[1], start_widget[0])
            ctx.line_to(u_pos_widget[1], u_pos_widget[0])
            draw_arrow(ctx, start_widget, u_pos_widget)
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.stroke()
            ctx.fill_style = self.used_fill_style
            draw_ellipse(ctx, u_pos_widget.x, u_pos_widget.y, size_widget[1], size_widget[0], self.used_stroke_style, self.used_fill_style)
        with ctx.saver():
            ctx.begin_path()
            ctx.move_to(start_widget[1], start_widget[0])
            ctx.line_to(v_pos_widget[1], v_pos_widget[0])
            draw_arrow(ctx, start_widget, v_pos_widget)
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.stroke()
            ctx.fill_style = self.used_fill_style
            draw_ellipse(ctx, v_pos_widget.x, v_pos_widget.y, size_widget[1], size_widget[0], self.used_stroke_style, self.used_fill_style)

        # uv_pos = u_pos + (v_pos - start)
        # uv_pos_widget = mapping.map_point_image_norm_to_widget(uv_pos)
        # with ctx.saver():
        #     ctx.begin_path()
        #     ctx.move_to(start_widget[1], start_widget[0])
        #     ctx.line_to(uv_pos_widget[1], uv_pos_widget[0])
        #     draw_arrow(ctx, start_widget, uv_pos_widget)
        #     ctx.line_width = 1
        #     ctx.stroke_style = self.used_color
        #     ctx.stroke()

        bounds = Geometry.FloatRect.from_tlbr(0, 0, 1, 1).inset(-radius, -radius)
        with ctx.saver():
            ctx.line_width = 1
            ctx.stroke_style = self.used_stroke_style
            ctx.fill_style = self.used_fill_style
            mx = 0
            drawn = True
            while drawn and mx < 32:
                drawn = False
                for ui in range(-mx, mx + 1):
                    for vi in range(-mx, mx + 1):
                        if (ui == 1 and vi == 0) or (ui == 0 and vi == 1):
                            continue
                        if ui == -mx or ui == mx or vi == -mx or vi == mx:
                            p = start + ui * (u_pos - start) + vi * (v_pos - start)
                            if bounds.contains_point(p):
                                p_widget = mapping.map_point_image_norm_to_widget(p)
                                draw_ellipse(ctx, p_widget.x, p_widget.y, size_widget[1], size_widget[0], self.used_stroke_style, self.used_fill_style)
                                drawn = True
                mx += 1

        if is_selected:
            self.draw_marker(ctx, start_widget)
            self.draw_marker(ctx, u_pos_widget)
            self.draw_marker(ctx, v_pos_widget)
            self.draw_marker(ctx, (u_pos_widget.y - size_widget.y/2, u_pos_widget.x - size_widget.x/2))
            self.draw_marker(ctx, (u_pos_widget.y - size_widget.y/2, u_pos_widget.x + size_widget.x/2))
            self.draw_marker(ctx, (u_pos_widget.y + size_widget.y/2, u_pos_widget.x + size_widget.x/2))
            self.draw_marker(ctx, (u_pos_widget.y + size_widget.y/2, u_pos_widget.x - size_widget.x/2))
            self.draw_marker(ctx, (v_pos_widget.y - size_widget.y/2, v_pos_widget.x - size_widget.x/2))
            self.draw_marker(ctx, (v_pos_widget.y - size_widget.y/2, v_pos_widget.x + size_widget.x/2))
            self.draw_marker(ctx, (v_pos_widget.y + size_widget.y/2, v_pos_widget.x + size_widget.x/2))
            self.draw_marker(ctx, (v_pos_widget.y + size_widget.y/2, v_pos_widget.x - size_widget.x/2))
        self.draw_label(ctx, get_font_metrics_fn, mapping)

    def label_position(self, mapping, font_metrics, padding):
        p1 = mapping.map_point_image_norm_to_widget((0.5, 0.5))
        return Geometry.FloatPoint(y=p1.y, x=p1.x)


def factory(lookup_id):
    build_map = {
        "line-graphic": LineGraphic,
        "line-profile-graphic": LineProfileGraphic,
        "rect-graphic": RectangleGraphic,
        "ellipse-graphic": EllipseGraphic,
        "point-graphic": PointGraphic,
        "interval-graphic": IntervalGraphic,
        "channel-graphic": ChannelGraphic,
        "spot-graphic": SpotGraphic,
        "wedge-graphic": WedgeGraphic,
        "ring-graphic": RingGraphic,
        "lattice-graphic": LatticeGraphic,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else MissingGraphic(type)
