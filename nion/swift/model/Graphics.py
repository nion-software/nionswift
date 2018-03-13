# standard libraries
import copy
import gettext
import math
import weakref

# third party libraries
import numpy  # for arange
import typing

# local libraries
from nion.utils import Event
from nion.utils import Geometry
from nion.utils import Observable
from nion.utils import Persistence

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


def adjust_rectangle_like(mapping, original, current, part, modifiers, constraints):
    # NOTE: all sizes/points are assumed to be in image coordinates
    o = mapping.map_point_widget_to_image(original)
    p = mapping.map_point_widget_to_image(current)
    delta = (p[0] - o[0], p[1] - o[1]) if not part[0].startswith("inverted") else (o[0] - p[0], o[1] - p[1])
    part_name = part[0] if not part[0].startswith("inverted") else part[0][9:]
    old_origin = mapping.map_point_image_norm_to_image(part[1][0])
    old_size = mapping.map_point_image_norm_to_image(part[1][1])
    old_top = old_origin[0]
    old_left = old_origin[1]
    old_height = old_size[0]
    old_width = old_size[1]
    old_center = old_top + 0.5 * old_height, old_left + 0.5 * old_width
    old_bottom = old_top + old_height
    old_right = old_left + old_width
    data_height = mapping.data_shape[0]
    data_width = mapping.data_shape[1]
    # find the minimum distance of center from origin and bottom corner of data
    min_from_origin = min(old_center[0], old_center[1])
    min_from_full = min(data_height - old_center[0], data_width - old_center[1])
    # now calculate the min/max v/h by adding/subtracting those values from bottom-right
    min_v = old_center[0] - min(min_from_origin, min_from_full)
    max_v = old_center[0] + min(min_from_origin, min_from_full)
    min_h = old_center[1] - min(min_from_origin, min_from_full)
    max_h = old_center[1] + min(min_from_origin, min_from_full)
    max_abs_delta_v = min(old_center[0], mapping.data_shape[0] - old_center[0])
    max_abs_delta_h = min(old_center[1], mapping.data_shape[1] - old_center[1])
    new_bounds = (old_origin, old_size)
    if part_name == "top-left" and not "shape" in constraints:  # top left
        new_top_left = old_top + delta[0], old_left + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = old_center[0] - new_top_left[0], old_center[1] - new_top_left[1]
                if half_size[0] > half_size[1]:  # size will be width
                    new_top_left = old_center[0] - half_size[1], old_center[1] - half_size[1]
                else:  # size will be height
                    new_top_left = old_center[0] - half_size[0], old_center[1] - half_size[0]
                if "bounds" in constraints:
                    # now constrain the top-left value
                    new_top_left = min(max(new_top_left[0], min_v), max_v), min(max(new_top_left[1], min_h), max_h)
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints:
                    new_top_left = min(max(new_top_left[0], old_center[0] - max_abs_delta_v), old_center[0] + max_abs_delta_v), min(max(new_top_left[1], old_center[1] - max_abs_delta_h), old_center[1] + max_abs_delta_h)
            # c + (c - t), c + (c - l)
            new_bottom_right = 2*old_center[0] - new_top_left[0], 2*old_center[1] - new_top_left[1]
            new_bounds = new_top_left, (new_bottom_right[0] - new_top_left[0], new_bottom_right[1] - new_top_left[1])
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints:
                    # find the minimum distance of bottom-right from origin and opposite corner of data
                    min_from_00 = min(old_bottom, old_right)
                    min_from_11 = min(data_height - old_bottom, data_width - old_right)
                    # now calculate the min/max v/h by adding/subtracting those values from bottom-right
                    min_v = old_bottom - min_from_00
                    max_v = old_bottom + min_from_11
                    min_h = old_right - min_from_00
                    max_h = old_right + min_from_11
                    # now constrain the top-left value
                    new_top_left = min(max(new_top_left[0], min_v), max_v), min(max(new_top_left[1], min_h), max_h)
                # shape constrained to square; hold bottom right constant
                if old_bottom - new_top_left[0] < old_right - new_top_left[1]:  # size will be width
                    new_top_left = old_bottom - (old_right - new_top_left[1]), new_top_left[1]
                else:  # size will be height
                    new_top_left = new_top_left[0], old_right - (old_bottom - new_top_left[0])
            else:
                # shape not constrained; hold bottom right constant
                if "bounds" in constraints:
                    new_top_left = min(max(new_top_left[0], 0.0), mapping.data_shape[0]), min(max(new_top_left[1], 0.0), mapping.data_shape[1])
            new_bounds = new_top_left, (old_bottom - new_top_left[0], old_right - new_top_left[1])
    elif part_name == "top-right" and not "shape" in constraints:  # top right
        new_top_right = old_top + delta[0], old_right + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = old_center[0] - new_top_right[0], new_top_right[1] - old_center[1]
                if half_size[0] > half_size[1]:  # size will be width
                    new_top_right = old_center[0] - half_size[1], old_center[1] + half_size[1]
                else:  # size will be height
                    new_top_right = old_center[0] - half_size[0], old_center[1] + half_size[0]
                if "bounds" in constraints:
                    # now constrain the top-right value
                    new_top_right = min(max(new_top_right[0], min_v), max_v), min(max(new_top_right[1], min_h), max_h)
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints:
                    new_top_right = min(max(new_top_right[0], old_center[0] - max_abs_delta_v), old_center[0] + max_abs_delta_v), min(max(new_top_right[1], old_center[1] - max_abs_delta_h), old_center[1] + max_abs_delta_h)
            # c + (c - t), c - (r - c)
            new_bottom_left = 2*old_center[0] - new_top_right[0], 2*old_center[1] - new_top_right[1]
            new_bounds = (new_top_right[0], new_bottom_left[1]), (new_bottom_left[0] - new_top_right[0], new_top_right[1] - new_bottom_left[1])
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints:
                    # find the minimum distance of bottom-left from bottom-left and opposite corner of data
                    min_from_10 = min(data_height - old_bottom, old_left)
                    min_from_01 = min(old_bottom, data_width - old_left)
                    # now calculate the min/max v/h by adding/subtracting those values from bottom-left
                    min_v = old_bottom - min_from_01
                    max_v = old_bottom + min_from_10
                    min_h = old_left - min_from_10
                    max_h = old_left + min_from_01
                    # now constrain the top-left value
                    new_top_right = min(max(new_top_right[0], min_v), max_v), min(max(new_top_right[1], min_h), max_h)
                # shape constrained to square; hold bottom left constant
                if old_bottom - new_top_right[0] < new_top_right[1] - old_left:  # size will be width
                    new_top_right = old_bottom - (new_top_right[1] - old_left), new_top_right[1]
                else:  # size will be height
                    new_top_right = new_top_right[0], old_left + (old_bottom - new_top_right[0])
            else:
                # shape not constrained; hold bottom left constant
                if "bounds" in constraints:
                    new_top_right = min(max(new_top_right[0], 0.0), mapping.data_shape[0]), min(max(new_top_right[1], 0.0), mapping.data_shape[1])
            new_bounds = (new_top_right[0], old_left), (old_bottom - new_top_right[0], new_top_right[1] - old_left)
    elif part_name == "bottom-right" and not "shape" in constraints:  # bottom right
        new_bottom_right = old_bottom + delta[0], old_right + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = new_bottom_right[0] - old_center[0], new_bottom_right[1] - old_center[1]
                if half_size[0] > half_size[1]:  # size will be width
                    new_bottom_right = old_center[0] + half_size[1], old_center[1] + half_size[1]
                else:  # size will be height
                    new_bottom_right = old_center[0] + half_size[0], old_center[1] + half_size[0]
                if "bounds" in constraints:
                    # now constrain the bottom-left value
                    new_bottom_right = min(max(new_bottom_right[0], min_v), max_v), min(max(new_bottom_right[1], min_h), max_h)
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints:
                    new_bottom_right = min(max(new_bottom_right[0], old_center[0] - max_abs_delta_v), old_center[0] + max_abs_delta_v), min(max(new_bottom_right[1], old_center[1] - max_abs_delta_h), old_center[1] + max_abs_delta_h)
            # c - (b - c), c - (r - c)
            new_top_left = 2*old_center[0] - new_bottom_right[0], 2*old_center[1] - new_bottom_right[1]
            new_bounds = new_top_left, (new_bottom_right[0] - new_top_left[0], new_bottom_right[1] - new_top_left[1])
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints:
                    # find the minimum distance of bottom-right from bottom-right and opposite corner of data
                    min_from_00 = min(old_top, old_left)
                    min_from_11 = min(data_height - old_top, data_width - old_left)
                    # now calculate the min/max v/h by adding/subtracting those values from top-right
                    min_v = old_top - min_from_00
                    max_v = old_top + min_from_11
                    min_h = old_left - min_from_00
                    max_h = old_left + min_from_11
                    # now constrain the bottom-left value
                    new_bottom_right = min(max(new_bottom_right[0], min_v), max_v), min(max(new_bottom_right[1], min_h), max_h)
                # shape constrained to square; hold top left constant
                if new_bottom_right[0] - old_top < new_bottom_right[1] - old_left:  # size will be width
                    new_bottom_right = old_top + (new_bottom_right[1] - old_left), new_bottom_right[1]
                else:  # size will be height
                    new_bottom_right = new_bottom_right[0], old_left + (new_bottom_right[0] - old_top)
            else:
                # shape not constrained; hold top right constant
                if "bounds" in constraints:
                    new_bottom_right = min(max(new_bottom_right[0], 0.0), mapping.data_shape[0]), min(max(new_bottom_right[1], 0.0), mapping.data_shape[1])
            new_bounds = (old_top, old_left), (new_bottom_right[0] - old_top, new_bottom_right[1] - old_left)
    elif part_name == "bottom-left" and not "shape" in constraints:  # bottom left
        new_bottom_left = old_bottom + delta[0], old_left + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift or "square" in constraints:
                # shape constrained to square; hold center constant
                half_size = new_bottom_left[0] - old_center[0], old_center[1] - new_bottom_left[1]
                if half_size[0] > half_size[1]:  # size will be width
                    new_bottom_left = old_center[0] + half_size[1], old_center[1] - half_size[1]
                else:  # size will be height
                    new_bottom_left = old_center[0] + half_size[0], old_center[1] - half_size[0]
                if "bounds" in constraints:
                    # now constrain the bottom-left value
                    new_bottom_left = min(max(new_bottom_left[0], min_v), max_v), min(max(new_bottom_left[1], min_h), max_h)
            else:
                # shape not constrained; hold center constant
                if "bounds" in constraints:
                    new_bottom_left = min(max(new_bottom_left[0], old_center[0] - max_abs_delta_v), old_center[0] + max_abs_delta_v), min(max(new_bottom_left[1], old_center[1] - max_abs_delta_h), old_center[1] + max_abs_delta_h)
            # c - (b - c), c + (c - l)
            new_top_right = 2*old_center[0] - new_bottom_left[0], 2*old_center[1] - new_bottom_left[1]
            new_bounds = (new_top_right[0], new_bottom_left[1]), (new_bottom_left[0] - new_top_right[0], new_top_right[1] - new_bottom_left[1])
        else:
            if modifiers.shift or "square" in constraints:
                if "bounds" in constraints:
                    # find the minimum distance of top-right from top-right and opposite corner of data
                    min_from_01 = min(old_top, data_width - old_right)
                    min_from_10 = min(data_height - old_top, old_right)
                    # now calculate the min/max v/h by adding/subtracting those values from top-right
                    min_v = old_top - min_from_01
                    max_v = old_top + min_from_10
                    min_h = old_right - min_from_10
                    max_h = old_right + min_from_01
                    # now constrain the top-left value
                    new_bottom_left = min(max(new_bottom_left[0], min_v), max_v), min(max(new_bottom_left[1], min_h), max_h)
                # shape constrained to square; hold top right constant
                if new_bottom_left[0] - old_top < old_right - new_bottom_left[1]:  # size will be width
                    new_bottom_left = old_top + (old_right - new_bottom_left[1]), new_bottom_left[1]
                else:  # size will be height
                    new_bottom_left = new_bottom_left[0], old_right - (new_bottom_left[0] - old_top)
            else:
                # shape not constrained; hold top right constant
                if "bounds" in constraints:
                    new_bottom_left = min(max(new_bottom_left[0], 0.0), mapping.data_shape[0]), min(max(new_bottom_left[1], 0.0), mapping.data_shape[1])
            new_bounds = (old_top, new_bottom_left[1]), (new_bottom_left[0] - old_top, old_right - new_bottom_left[1])
    elif (part_name == "all" or "shape" in constraints) and not "position" in constraints:
        if modifiers.shift:
            if delta[0] > delta[1]:
                origin = old_top + delta[0], old_left
            else:
                origin = old_top, old_left + delta[1]
        else:
            origin = old_top + delta[0], old_left + delta[1]
        if "bounds" in constraints:
            origin = min(max(origin[0], 0.0), data_height - old_height), min(max(origin[1], 0.0), data_width - old_width)
        new_bounds = origin, old_size
    return mapping.map_point_image_to_image_norm(new_bounds[0]), mapping.map_size_image_to_image_norm(new_bounds[1])


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
        self.__container_weak_ref = None
        self.about_to_be_removed_event = Event.Event()
        self._about_to_be_removed = False
        self._closed = False
        self.define_type(type)
        self.define_property("graphic_id", None, changed=self._property_changed, validate=lambda s: str(s) if s else None)
        self.define_property("color", "#F80", changed=self._property_changed)
        self.define_property("label", changed=self._property_changed, validate=lambda s: str(s) if s else None)
        self.define_property("is_position_locked", False, changed=self._property_changed)
        self.define_property("is_shape_locked", False, changed=self._property_changed)
        self.define_property("is_bounds_constrained", False, changed=self._property_changed)
        self.__region = None
        self.graphic_changed_event = Event.Event()
        self.label_padding = 4
        self.label_font = "normal 11px serif"

    def close(self):
        assert self._about_to_be_removed
        assert not self._closed
        self._closed = True
        self.__container_weak_ref = None

    @property
    def container(self):
        return self.__container_weak_ref()

    def about_to_be_inserted(self, container):
        assert self.__container_weak_ref is None
        self.__container_weak_ref = weakref.ref(container)

    def about_to_be_removed(self):
        # called before close and before item is removed from its container
        self.about_to_be_removed_event.fire()
        assert not self._about_to_be_removed
        self._about_to_be_removed = True
        self.__container_weak_ref = None

    def insert_model_item(self, container, name, before_index, item):
        if self.__container_weak_ref:
            self.container.insert_model_item(container, name, before_index, item)
        else:
            container.insert_item(name, before_index, item)

    def remove_model_item(self, container, name, item, *, safe: bool=False) -> typing.Optional[typing.Sequence]:
        if self.__container_weak_ref:
            return self.container.remove_model_item(container, name, item, safe=safe)
        else:
            container.remove_item(name, item)
            return None

    def clone(self) -> "Graphic":
        graphic = copy.deepcopy(self)
        graphic.uuid = self.uuid
        return graphic

    def mime_data_dict(self) -> dict:
        return {
            "type": self.type,
            "color": self.color,
            "label": self.label,
            "is_position_locked": self.is_position_locked,
            "is_shape_locked": self.is_shape_locked,
            "is_bounds_constrained": self.is_bounds_constrained,
        }

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        self.color = graphic_dict.get("color", self.color)
        self.label = graphic_dict.get("label", self.label)
        self.is_position_locked = graphic_dict.get("is_position_locked", self.is_position_locked)
        self.is_shape_locked = graphic_dict.get("is_shape_locked", self.is_shape_locked)
        self.is_bounds_constrained = graphic_dict.get("is_bounds_constrained", self.is_bounds_constrained)

    def _property_changed(self, name, value):
        self.notify_property_changed(name)

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

    def draw_ellipse(self, ctx, cx, cy, rx, ry):
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
            ctx.stroke()
            ctx.fill()

    def draw_marker(self, ctx, p):
        with ctx.saver():
            ctx.fill_style = '#00FF00'
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
                ctx.stroke_style = self.color
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


class RectangleTypeGraphic(Graphic):
    def __init__(self, type, title):
        super().__init__(type)
        self.title = title
        self.define_property("bounds", ((0.0, 0.0), (1.0, 1.0)), validate=self.__validate_bounds, changed=self.__bounds_changed)

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["bounds"] = self.bounds
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
        self.bounds = graphic_dict.get("bounds", self.bounds)

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
        mask[bounds_int[0][0]:bounds_int[0][0] + bounds_int[1][0] + 1,
             bounds_int[0][1]:bounds_int[0][1] + bounds_int[1][1] + 1] = 1
        return mask

    # test point hit
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
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
            return "all", False
        # label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all", False
        # didn't find anything
        return None, None

    def begin_drag(self):
        return (self.bounds, )

    def end_drag(self, part_data):
        pass

    # rectangle
    def adjust_part(self, mapping, original, current, part, modifiers):
        self.bounds = adjust_rectangle_like(mapping, original, current, part, modifiers, self._constraints)

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

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        with ctx.saver():
            ctx.begin_path()
            ctx.move_to(origin[1], origin[0])
            ctx.line_to(origin[1] + size[1], origin[0])
            ctx.line_to(origin[1] + size[1], origin[0] + size[0])
            ctx.line_to(origin[1], origin[0] + size[0])
            ctx.close_path()
            ctx.line_width = 1
            ctx.stroke_style = self.color
            ctx.stroke()
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            # draw center marker
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5 * size[1]
                mid_y = origin[0] + 0.5 * size[0]
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(mid_x - 0.5 * mark_size, mid_y)
                    ctx.line_to(mid_x + 0.5 * mark_size, mid_y)
                    ctx.stroke_style = self.color
                    ctx.stroke()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5 * size[1]
                mid_y = origin[0] + 0.5 * size[0]
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(mid_x, mid_y - 0.5 * mark_size)
                    ctx.line_to(mid_x, mid_y + 0.5 * mark_size)
                    ctx.stroke_style = self.color
                    ctx.stroke()
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
        mask_eq = x*x / ((bounds_int[1][1] / 2) * (bounds_int[1][1] / 2)) + y*y / ((bounds_int[1][0] / 2) * (bounds_int[1][0] / 2)) <= 1
        mask[mask_eq] = 1
        return mask

    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        with ctx.saver():
            ctx.line_width = 1
            ctx.stroke_style = self.color
            self.draw_ellipse(ctx, origin[1] + size[1] * 0.5, origin[0] + size[0] * 0.5, size[1], size[0])
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            # draw center marker
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5 * size[1]
                mid_y = origin[0] + 0.5 * size[0]
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(mid_x - 0.5 * mark_size, mid_y)
                    ctx.line_to(mid_x + 0.5 * mark_size, mid_y)
                    ctx.stroke_style = self.color
                    ctx.stroke()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5 * size[1]
                mid_y = origin[0] + 0.5 * size[0]
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(mid_x, mid_y - 0.5 * mark_size)
                    ctx.line_to(mid_x, mid_y + 0.5 * mark_size)
                    ctx.stroke_style = self.color
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

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
        self.vector = graphic_dict.get("vector", self.vector)
        self.start_arrow_enabled = graphic_dict.get("start_arrow_enabled", self.start_arrow_enabled)
        self.end_arrow_enabled = graphic_dict.get("end_arrow_enabled", self.end_arrow_enabled)

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

    def draw_arrow(self, ctx, p1, p2):
        arrow_size = 8
        angle = math.atan2(p2[0] - p1[0], p2[1] - p1[1])
        ctx.move_to(p2[1], p2[0])
        ctx.line_to(p2[1] - arrow_size * math.cos(angle - math.pi / 6), p2[0] - arrow_size * math.sin(angle - math.pi / 6))
        ctx.move_to(p2[1], p2[0])
        ctx.line_to(p2[1] - arrow_size * math.cos(angle + math.pi / 6), p2[0] - arrow_size * math.sin(angle + math.pi / 6))

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
                self.draw_arrow(ctx, p2, p1)
            if self.end_arrow_enabled:
                self.draw_arrow(ctx, p1, p2)
            ctx.line_width = 1
            ctx.stroke_style = self.color
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
        # self.interval_descriptors = [{"interval": (0.1, 0.3), "color": "#F00"}, {"interval": (0.7, 0.74), "color": "#0F0"}]

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["line_width"] = self.width
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
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
                self.draw_arrow(ctx, p2, p1)
            if self.end_arrow_enabled:
                self.draw_arrow(ctx, p1, p2)
            ctx.line_width = 1
            ctx.stroke_style = self.color
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
                    ctx.stroke_style = self.color
                    ctx.stroke()
            for interval_descriptor in self.interval_descriptors:
                interval = interval_descriptor.get("interval")
                color = interval_descriptor.get("color", self.color)
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

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
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
            ctx.stroke_style = self.color
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

        # interval is stored in image normalized coordinates
        self.define_property("interval", (0.0, 1.0), changed=self.__interval_changed, reader=read_interval, writer=write_interval, validate=lambda value: tuple(value))

    def mime_data_dict(self) -> dict:
        d = super().mime_data_dict()
        d["interval"] = self.interval
        return d

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
        self.interval = graphic_dict.get("interval", self.interval)

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

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
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

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
        self.bounds = graphic_dict.get("bounds", self.bounds)

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
        return (self.bounds,)

    def end_drag(self, part_data):
        pass

    # rectangle
    def adjust_part(self, mapping, original, current, part, modifiers):
        constraints = self._constraints
        if part[0] not in ("all", "inverted-all"):
            constraints = constraints.union({"position", "square"})
        self.bounds = adjust_rectangle_like(mapping, original, current, part, modifiers, constraints)

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
            ctx.stroke_style = self.color
            ctx.fill_style = "rgba(255, 0, 127, 0.1)"
            cx0 = origin[1] + size[1] * 0.5
            cy0 = origin[0] + size[0] * 0.5
            self.draw_ellipse(ctx, cx0, cy0, size[1], size[0])
            ctx.stroke_style = self.color
            ctx.fill_style = "rgba(255, 0, 127, 0.1)"
            cx1 = 2 * center[1] - cx0
            cy1 = 2 * center[0] - cy0
            self.draw_ellipse(ctx, cx1, cy1, size[1], size[0])
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
                    ctx.stroke_style = self.color
                    ctx.stroke()
                    ctx.begin_path()
                    ctx.move_to(mid_x1 - 0.5 * mark_size, mid_y1)
                    ctx.line_to(mid_x1 + 0.5 * mark_size, mid_y1)
                    ctx.stroke_style = self.color
                    ctx.stroke()
            if size[1] > mark_size:
                mid_x0 = origin[1] + 0.5 * size[1]
                mid_y0 = origin[0] + 0.5 * size[0]
                mid_y1, mid_x1 = rotate_180_around_center((mid_y0, mid_x0), center)
                with ctx.saver():
                    ctx.begin_path()
                    ctx.move_to(mid_x0, mid_y0 - 0.5 * mark_size)
                    ctx.line_to(mid_x0, mid_y0 + 0.5 * mark_size)
                    ctx.stroke_style = self.color
                    ctx.stroke()
                    ctx.begin_path()
                    ctx.move_to(mid_x1, mid_y1 - 0.5 * mark_size)
                    ctx.line_to(mid_x1, mid_y1 + 0.5 * mark_size)
                    ctx.stroke_style = self.color
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

        def validate_angles(value: typing.Tuple[float, float]) -> typing.Tuple[typing.Tuple[float], typing.Tuple[float]]:
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

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
        self.angle_interval = graphic_dict.get("angle_interval", self.angle_interval)

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
                ctx.stroke_style = self.color
                ctx.fill_style = "rgba(255, 0, 127, 0.1)"
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

    def read_from_mime_data(self, graphic_dict: typing.Mapping, is_same_source: bool) -> None:
        super().read_from_mime_data(graphic_dict, is_same_source)
        self.radius_1 = graphic_dict.get("radius_1", self.radius_1)
        self.radius_2 = graphic_dict.get("radius_2", self.radius_2)
        self.mode = graphic_dict.get("mode", self.mode)

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
            ctx.stroke_style = self.color
            self.draw_ellipse(ctx, center[1], center[0], radius_1_widget[1] * 2, radius_1_widget[0] * 2)
            if is_selected:
                self.draw_marker(ctx, (center[0] + radius_1_widget[0], center[1]))
                self.draw_marker(ctx, (center[0] - radius_1_widget[0], center[1]))
                self.draw_marker(ctx, (center[0], center[1] + radius_1_widget[1]))
                self.draw_marker(ctx, (center[0], center[1] - radius_1_widget[1]))
            if not self.mode == "low-pass" and not self.mode == "high-pass":
                ctx.line_width = 1
                ctx.stroke_style = self.color
                self.draw_ellipse(ctx, center[1], center[0], radius_2_widget[1] * 2, radius_2_widget[0] * 2)
                if is_selected:
                    self.draw_marker(ctx, (center[0] + radius_2_widget[0], center[1]))
                    self.draw_marker(ctx, (center[0] - radius_2_widget[0], center[1]))
                    self.draw_marker(ctx, (center[0], center[1] + radius_2_widget[1]))
                    self.draw_marker(ctx, (center[0], center[1] - radius_2_widget[1]))
            # draw 2 thick arcs
            ctx.fill_style = "rgba(255, 0, 127, 0.1)"
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
        "ring-graphic": RingGraphic
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
