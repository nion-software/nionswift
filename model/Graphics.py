# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import copy
import gettext
import logging
import math
import uuid

# third party libraries
import numpy  # for arange

# local libraries
from nion.ui import Geometry
from nion.ui import Observable


_ = gettext.gettext


def adjust_rectangle_like(mapping, original, current, part, modifiers, constraints):
    # NOTE: all sizes/points are assumed to be in image coordinates
    o = mapping.map_point_widget_to_image(original)
    p = mapping.map_point_widget_to_image(current)
    delta = (p[0] - o[0], p[1] - o[1])
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
    if part[0] == "top-left" and not "shape" in constraints:  # top left
        new_top_left = old_top + delta[0], old_left + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift:
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
            if modifiers.shift:
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
    elif part[0] == "top-right" and not "shape" in constraints:  # top right
        new_top_right = old_top + delta[0], old_right + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift:
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
            if modifiers.shift:
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
    elif part[0] == "bottom-right" and not "shape" in constraints:  # bottom right
        new_bottom_right = old_bottom + delta[0], old_right + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift:
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
            if modifiers.shift:
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
    elif part[0] == "bottom-left" and not "shape" in constraints:  # bottom left
        new_bottom_left = old_bottom + delta[0], old_left + delta[1]
        if modifiers.alt or "position" in constraints:
            if modifiers.shift:
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
            if modifiers.shift:
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
    elif (part[0] == "all" or "shape" in constraints) and not "position" in constraints:
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
class Graphic(Observable.Observable, Observable.Broadcaster, Observable.ManagedObject):
    def __init__(self, type):
        super(Graphic, self).__init__()
        self.define_type(type)
        self.define_property("color", "#F00", changed=self._property_changed)
        self.define_property("label", changed=self._property_changed)
        self.define_property("is_position_locked", False, changed=self._property_changed)
        self.define_property("is_shape_locked", False, changed=self._property_changed)
        self.define_property("is_bounds_constrained", False, changed=self._property_changed)
        self.__region = None
        self.about_to_be_removed_event = Observable.Event()
        self.label_padding = 4
        self.label_font = "normal 11px serif"
    def about_to_be_removed(self):
        self.about_to_be_removed_event.fire()
    def _property_changed(self, name, value):
        self.notify_set_property(name, value)
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
    # test whether points are close
    def test_point(self, p1, p2, radius):
        return math.sqrt(pow(p1[0]-p2[0], 2)+pow(p1[1]-p2[1], 2)) < radius
    # closest point on line
    def get_closest_point_on_line(self, start, end, p):
        c = (p[0] - start[0], p[1] - start[1])
        v = (end[0] - start[0], end[1] - start[1])
        length = math.sqrt(pow(v[0],2) + pow(v[1],2))
        v = (v[0] / length, v[1] / length)
        t = v[0] * c[0] + v[1] * c[1]
        if t < 0:
            return start
        if t > length:
            return end
        return (start[0] + v[0] * t, start[1] + v[1] * t)
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
            bounds = Geometry.FloatRect.from_center_and_size(text_pos, Geometry.FloatSize(width=font_metrics.width + padding * 2, height=font_metrics.height + padding * 2))
            return self.test_inside_bounds(bounds, test_point, 2)
        return False
    def draw_ellipse(self, ctx, cx, cy, rx, ry):
        ctx.save()
        ra = 0.0  # rotation angle
        ctx.begin_path()
        for i in numpy.arange(0, 2*math.pi, 0.1):
            x = cx - (ry * 0.5 * math.sin(i)) * math.sin(ra * math.pi) + (rx * 0.5 * math.cos(i)) * math.cos(ra * math.pi)
            y = cy + (rx * 0.5 * math.cos(i)) * math.sin(ra * math.pi) + (ry * 0.5 * math.sin(i)) * math.cos(ra * math.pi)
            if i == 0:
                ctx.move_to(x, y)
            else:
                ctx.line_to(x, y)
        ctx.close_path()
        ctx.stroke()
        ctx.restore()
    def draw_marker(self, ctx, p):
        ctx.save()
        ctx.fill_style = '#00FF00'
        ctx.begin_path()
        ctx.move_to(p[1] - 3, p[0] - 3)
        ctx.line_to(p[1] + 3, p[0] - 3)
        ctx.line_to(p[1] + 3, p[0] + 3)
        ctx.line_to(p[1] - 3, p[0] + 3)
        ctx.close_path()
        ctx.fill()
        ctx.restore()
    def draw_label(self, ctx, get_font_metrics_fn, mapping):
        if self.label:
            padding = self.label_padding
            font = self.label_font
            font_metrics = get_font_metrics_fn(font, self.label)
            text_pos = self.label_position(mapping, font_metrics, padding)
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
    def notify_set_property(self, key, value):
        super(Graphic, self).notify_set_property(key, value)
        self.notify_listeners("graphic_changed", self)
    def nudge(self, mapping, delta):
        raise NotImplementedError()
    def notify_remove_region_graphic(self):
        self.notify_listeners("remove_region_graphic", self)  # goes to region
    def label_position(self, mapping, font_metrics, padding):
        raise NotImplementedError()


class RectangleTypeGraphic(Graphic):
    def __init__(self, type, title):
        super(RectangleTypeGraphic, self).__init__(type)
        self.title = title
        self.define_property("bounds", ((0.0, 0.0), (1.0, 1.0)), validate=self.__validate_bounds, changed=self.__bounds_changed)

    # accessors

    def __validate_bounds(self, value):
        # normalize
        if value[1][0] < 0:  # height is negative
            value = ((value[0][0] + value[1][0], value[0][1]), (-value[1][0], value[1][1]))
        if value[1][1] < 0:  # width is negative
            value = ((value[0][0], value[0][1] + value[1][1]), (value[1][0], -value[1][1]))
        return tuple(copy.deepcopy(value))

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

    # test point hit
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        # top left
        if not move_only and self.test_point(origin, test_point, 4):
            return "top-left"
        # top right
        if not move_only and self.test_point((origin[0], origin[1] + size[1]), test_point, 4):
            return "top-right"
        # bottom right
        if not move_only and self.test_point((origin[0] + size[0], origin[1] + size[1]), test_point, 4):
            return "bottom-right"
        # bottom left
        if not move_only and self.test_point((origin[0] + size[0], origin[1]), test_point, 4):
            return "bottom-left"
        # center
        if self.test_inside_bounds((origin, size), test_point, 4):
            return "all"
        # didn't find anything
        return None

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
        super(RectangleGraphic, self).__init__("rect-graphic", _("Rectangle"))
    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        ctx.save()
        ctx.begin_path()
        ctx.move_to(origin[1], origin[0])
        ctx.line_to(origin[1] + size[1], origin[0])
        ctx.line_to(origin[1] + size[1], origin[0] + size[0])
        ctx.line_to(origin[1], origin[0] + size[0])
        ctx.close_path()
        ctx.line_width = 1
        ctx.stroke_style = self.color
        ctx.stroke()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            # draw center marker
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x - 0.5*mark_size, mid_y)
                ctx.line_to(mid_x + 0.5*mark_size, mid_y)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x, mid_y - 0.5*mark_size)
                ctx.line_to(mid_x, mid_y + 0.5*mark_size)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()


class EllipseGraphic(RectangleTypeGraphic):
    def __init__(self):
        super(EllipseGraphic, self).__init__("ellipse-graphic", _("Ellipse"))
    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        ctx.save()
        ctx.line_width = 1
        ctx.stroke_style = self.color
        self.draw_ellipse(ctx, origin[1] + size[1]*0.5, origin[0] + size[0]*0.5, size[1], size[0])
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            # draw center marker
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x - 0.5*mark_size, mid_y)
                ctx.line_to(mid_x + 0.5*mark_size, mid_y)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x, mid_y - 0.5*mark_size)
                ctx.line_to(mid_x, mid_y + 0.5*mark_size)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()


class LineTypeGraphic(Graphic):
    def __init__(self, type, title):
        super(LineTypeGraphic, self).__init__(type)
        self.title = title
        def read_vector(managed_property, properties):
            # read the vector defined by managed_property from the properties dict.
            start = properties.get("start", (0.0, 0.0))
            end = properties.get("end", (1.0, 1.0))
            return start, end
        def write_vector(managed_property, properties, value):
            # write the vector (value) defined by managed_property to the properties dict.
            properties["start"] = value[0]
            properties["end"] = value[1]
        # vector is stored in image normalized coordinates
        self.define_property("vector", ((0.0, 0.0), (1.0, 1.0)), changed=self.__vector_changed, reader=read_vector, writer=write_vector, validate=lambda value: (tuple(value[0]), tuple(value[1])))
        self.define_property("start_arrow_enabled", False, changed=self._property_changed, validate=lambda value: bool(value))
        self.define_property("end_arrow_enabled", False, changed=self._property_changed, validate=lambda value: bool(value))
    # accessors
    def __get_start(self):
        return self.vector[0]
    def __set_start(self, start):
        self.vector = start, self.vector[1]
    start = property(__get_start, __set_start)
    def __get_end(self):
        return self.vector[1]
    def __set_end(self, end):
        self.vector = self.vector[0], end
    end = property(__get_end, __set_end)
    # dependent properties
    def __vector_changed(self, name, value):
        self._property_changed(name, value)
        self.notify_set_property("start", value[0])
        self.notify_set_property("end", value[1])
    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        # start point
        if not move_only and self.test_point(p1, test_point, 4):
            return "start"
        # end point
        if not move_only and self.test_point(p2, test_point, 4):
            return "end"
        # along the line
        if self.test_line(p1, p2, test_point, 4):
            return "all"
        # didn't find anything
        return None
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
        elif part[0] == "all" or "shape" in constraints:
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
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())
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
        super(LineGraphic, self).__init__("line-graphic", _("Line"))
    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        ctx.save()
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
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)


class LineProfileGraphic(LineTypeGraphic):
    def __init__(self):
        super(LineProfileGraphic, self).__init__("line-profile-graphic", _("Line Profile"))
        self.define_property("width", 1.0, changed=self._property_changed, validate=lambda value: float(value))
    # accessors
    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        ctx.save()
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
        if self.width > 1.0:
            half_width = self.width * 0.5
            length = math.sqrt(math.pow(p2[0] - p1[0],2) + math.pow(p2[1] - p1[1], 2))
            dy = (p2[0] - p1[0]) / length
            dx = (p2[1] - p1[1]) / length
            ctx.save()
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
            ctx.restore()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)


class PointTypeGraphic(Graphic):
    def __init__(self, type, title):
        super(PointTypeGraphic, self).__init__(type)
        self.title = title
        # start and end points are stored in image normalized coordinates
        self.define_property("position", (0.5, 0.5), changed=self._property_changed, validate=lambda value: tuple(value))
    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        cross_hair_size = 12
        p = mapping.map_point_image_norm_to_widget(self.position)
        bounds = Geometry.FloatRect.from_center_and_size(p, Geometry.FloatSize(width=cross_hair_size*2, height=cross_hair_size*2))
        if self.test_inside_bounds(bounds, test_point, 2):
            return "all"
        # check the label
        if self.test_label(get_font_metrics_fn, mapping, test_point):
            return "all"
        # didn't find anything
        return None
    def begin_drag(self):
        return (self.position, )
    def end_drag(self, part_data):
        pass
    def adjust_part(self, mapping, original, current, part, modifiers):
        if part[0] == "all":
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
            if "bounds" in self._constraints:
                pos = min(max(pos[0], 0.0), 1.0), min(max(pos[1], 0.0), 1.0)
            self.position = pos
    def nudge(self, mapping, delta):
        pos_image = mapping.map_point_image_norm_to_image(self.position)
        original = pos_image
        current = original + delta
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())
    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        raise NotImplementedError()


class PointGraphic(PointTypeGraphic):
    def __init__(self):
        super(PointGraphic, self).__init__("point-graphic", _("Point"))
        self.cross_hair_size = 12
    def draw(self, ctx, get_font_metrics_fn, mapping, is_selected=False):
        p = mapping.map_point_image_norm_to_widget(self.position)
        ctx.save()
        try:
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
        finally:
            ctx.restore()
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
        super(IntervalGraphic, self).__init__("interval-graphic")
        self.title = _("Interval")
        # start and end points are stored in channel normalized coordinates
        def read_interval(managed_property, properties):
            # read the interval defined by managed_property from the properties dict.
            start = properties.get("start", 0.0)
            end = properties.get("end", 1.0)
            return start, end
        def write_interval(managed_property, properties, value):
            # write the interval (value) defined by managed_property to the properties dict.
            properties["start"] = value[0]
            properties["end"] = value[1]
        # interval is stored in image normalized coordinates
        self.define_property("interval", (0.0, 1.0), changed=self.__interval_changed, reader=read_interval, writer=write_interval, validate=lambda value: tuple(value))
    # accessors
    def __get_start(self):
        return self.interval[0]
    def __set_start(self, start):
        self.interval = start, self.interval[1]
    start = property(__get_start, __set_start)
    def __get_end(self):
        return self.interval[1]
    def __set_end(self, end):
        self.interval = self.interval[0], end
    end = property(__get_end, __set_end)
    # dependent properties
    def __interval_changed(self, name, value):
        self._property_changed(name, value)
        self.notify_set_property("start", value[0])
        self.notify_set_property("end", value[1])
    # test is required for Graphic interface
    def test(self, mapping, get_font_metrics_fn, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p1 = mapping.map_point_channel_norm_to_widget(self.start)
        p2 = mapping.map_point_channel_norm_to_widget(self.end)
        # start point
        if not move_only and abs(test_point.x - p1) < 4:
            return "start"
        # end point
        if not move_only and abs(test_point.x - p2) < 4:
            return "end"
        # along the line
        if test_point.x > p1 - 4 and test_point.x < p2 + 4:
            return "all"
        # didn't find anything
        return None
    def begin_drag(self):
        return (self.start, self.end)
    def end_drag(self, part_data):
        if self.end < self.start:
            self.start, self.end = self.end, self.start
    def adjust_part(self, mapping, original, current, part, modifiers):
        o = mapping.map_point_widget_to_channel_norm(original)
        p = mapping.map_point_widget_to_channel_norm(current)
        if part[0] == "start":
            self.start = p
        elif part[0] == "end":
            self.end = p
        elif part[0] == "all":
            self.interval = (part[1] + (p - o), part[2] + (p - o))
    def nudge(self, mapping, delta):
        end_channel = mapping.map_point_channel_norm_to_channel(self.end)
        start_channel = mapping.map_point_channel_norm_to_channel(self.start)
        original = (end_channel + start_channel) * 0.5
        current = original + delta
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())


def factory(lookup_id):
    build_map = {
        "line-graphic": LineGraphic,
        "rect-graphic": RectangleGraphic,
        "ellipse-graphic": EllipseGraphic,
        "point-graphic": PointGraphic,
        "interval-graphic": IntervalGraphic,
    }
    type = lookup_id("type")
    return build_map[type]() if type in build_map else None
