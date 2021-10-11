"""
See color maps:
    https://sciviscolor.org/
    http://www.kennethmoreland.com/color-advice/
    https://datascience.lanl.gov/colormaps.html
"""

import collections
import colorsys
import dataclasses
import gettext
import json
import pathlib

import numpy
import numpy.typing
import math
import os
import pkgutil
import re
import typing
import xml.etree.ElementTree as ET

_ = gettext.gettext

_LookupDataArray = typing.Any  # numpy.typing.NDArray[typing.Any]
_RGBA8ImageDataType = typing.Any  # numpy.typing.NDArray[typing.Any]
_PointsType = typing.List[typing.Dict[str, typing.Union[float, typing.Tuple[int, int, int]]]]


def interpolate_colors(array: _LookupDataArray, x: int) -> _RGBA8ImageDataType:
    """
    Creates a color map for values in array
    :param array: color map to interpolate
    :param x: number of colors
    :return: interpolated color map
    """
    out_array: typing.List[typing.Tuple[int, int, int]] = []
    for i in range(x):
        if i % (x / (len(array) - 1)) == 0:
            index = i / (x / (len(array) - 1))
            out_array.append(array[int(index)])
        else:
            start_marker = array[math.floor(i / (x / (len(array) - 1)))]
            stop_marker = array[math.ceil(i / (x / (len(array) - 1)))]
            interp_amount = i % (x / (len(array) - 1)) / (x / (len(array) - 1))
            interp_color = numpy.rint(start_marker + ((stop_marker - start_marker) * interp_amount))
            out_array.append(interp_color)
    out_array[-1] = array[-1]
    return numpy.array(out_array).astype(numpy.uint8)


def generate_lookup_array_from_points(points: _PointsType, n: int) -> _RGBA8ImageDataType:
    assert points[0]["x"] == 0.0
    assert points[-1]["x"] == 1.0
    out_array = []
    last_ix = None
    last_rgb = None
    for point in points:
        if "rgb" in point:
            r, g, b = typing.cast(typing.Tuple[int, int, int], point["rgb"])
        else:
            r = round(typing.cast(float, point["r"]) * 255)
            g = round(typing.cast(float, point["g"]) * 255)
            b = round(typing.cast(float, point["b"]) * 255)
        x = typing.cast(float, point["x"])
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255
        assert 0 <= x <= 1
        rgb = numpy.array([b, g, r])
        ix = int(math.floor(x * (n - 1)))
        if last_ix is None:
            out_array.append(numpy.copy(rgb))  # type: ignore
        elif ix > last_ix:
            amount = (rgb - last_rgb) / (ix - last_ix)
            for x in range(ix - last_ix):
                out_array.append(numpy.rint(last_rgb + amount * (x + 1)))
        else:
            assert ix >= last_ix
        last_ix = ix
        last_rgb = numpy.copy(rgb)  # type: ignore
    return numpy.array(out_array).astype(numpy.uint8)


def generate_lookup_array_grayscale() -> _RGBA8ImageDataType:
    out_list = []
    for i in range(256):
        out_list.append([i, i, i])
    return numpy.array(out_list).astype(numpy.uint8)

lookup_arrays = {
    'magma':     [[0, 0, 0],
                  [127, 0, 127],
                  [96, 96, 255],
                  [64, 192, 255],
                  [223, 255, 255]],
    'viridis':   [[32, 32, 64],
                  [160, 160, 64],
                  [208, 208, 0],
                  [144, 255, 32],
                  [0, 255, 255]],
    'plasma':    [[127, 0, 0],
                  [127, 0, 127],
                  [127, 127, 255],
                  [127, 255, 255],
                  [195, 255, 255]],
    'ice':       [[0, 0, 0],
                  [127, 0, 0],
                  [255, 127, 0],
                  [255, 255, 127],
                  [255, 255, 255]]
}

def generate_lookup_array(color_map_id: str) -> _RGBA8ImageDataType:
    return interpolate_colors(numpy.array(lookup_arrays[color_map_id]), 256)

def generate_lookup_array_hsv() -> _RGBA8ImageDataType:
    result_array = []
    for lookup_value in range(256):
        color_values = [x * 255 for x in colorsys.hsv_to_rgb(lookup_value / 300, 1.0, 1.0)]
        result_array.append(color_values)
    return numpy.array(result_array).astype(numpy.uint8)


@dataclasses.dataclass
class ColorMap:
    name: str
    data: _RGBA8ImageDataType


color_maps: typing.Dict[str, ColorMap] = dict()

color_maps["grayscale"] = ColorMap(_("Grayscale"), generate_lookup_array_grayscale())
color_maps["magma"] = ColorMap(_("Magma"), generate_lookup_array('magma'))
color_maps["hsv"] = ColorMap(_("HSV"), generate_lookup_array_hsv())
color_maps["viridis"] = ColorMap(_("Viridis"), generate_lookup_array('viridis'))
color_maps["plasma"] = ColorMap(_("Plasma"), generate_lookup_array('plasma'))
color_maps["ice"] = ColorMap(_("Ice"), generate_lookup_array('ice'))


def load_color_maps(color_maps_dir: pathlib.Path) -> None:
    for root, dirs, files in os.walk(color_maps_dir):
        for file in files:
            if not file.startswith("."):
                try:
                    if file.endswith(".json"):
                        with open(os.path.join(root, file), "r") as f:
                            color_map_json = json.load(f)
                            color_maps[color_map_json["id"]] = ColorMap(color_map_json["name"], generate_lookup_array_from_points(color_map_json["points"], 256))
                    elif file.endswith(".xml"):
                        tree = ET.parse(os.path.join(root, file))
                        assert tree.getroot().tag == "ColorMaps"
                        color_map_tree = list(tree.getroot())[0]
                        assert color_map_tree.tag == "ColorMap"
                        raw_points = [point_tree.attrib for point_tree in color_map_tree]
                        points: _PointsType = list()
                        for raw_point in raw_points:
                            if "x" in raw_point:
                                points.append({"x": float(raw_point['x']), "r": float(raw_point['r']), "g": float(raw_point['g']), "b": float(raw_point['b'])})
                        name = file[:-4]
                        color_map_id = name.lower()
                        color_map_id = re.sub(r"[^\w\s]", '', color_map_id)
                        color_map_id = re.sub(r"\s+", '-', color_map_id)
                        color_maps[color_map_id] = ColorMap(name, generate_lookup_array_from_points(points, 256))
                        """
                        # this section can be used to generate .json from .xml color tables
                        points2 = [{"x": point['x'], "rgb": [round(point['r'] * 255), round(point['g'] * 255), round(point['b'] * 255)]} for point in points]
                        s = ""
                        s += '{' + '\n'
                        s += f'  "id": "{color_map_id}",' + '\n'
                        s += f'  "name": "{name}",' + '\n'
                        s += '  "points": [' + '\n'
                        bro = '{'
                        brc = '}'
                        for point2 in points2[:-1]:
                            s += f'    {bro}"x": {point2["x"]}, "rgb": [{point2["rgb"][0]}, {point2["rgb"][1]}, {point2["rgb"][2]}]{brc},' + '\n'
                        point2 = points2[-1]
                        s += f'    {bro}"x": {point2["x"]}, "rgb": [{point2["rgb"][0]}, {point2["rgb"][1]}, {point2["rgb"][2]}]{brc}' + '\n'
                        s += '  ]' + '\n'
                        s += '}' + '\n'
                        print(s)
                        # d = {"id": color_map_id, "name": name, "points": points2}
                        # print(json.dumps(d, indent=2))
                        """
                except Exception as e:
                    import traceback
                    traceback.print_exc()


def load_color_map_resource(resource_path: str) -> None:
    bytes = pkgutil.get_data(__name__, resource_path)
    assert bytes is not None
    color_map_json = json.loads(bytes)
    color_maps[color_map_json["id"]] = ColorMap(color_map_json["name"], generate_lookup_array_from_points(color_map_json["points"], 256))


load_color_map_resource("resources/color_maps/black_body.json")
load_color_map_resource("resources/color_maps/extended_black_body.json")
load_color_map_resource("resources/color_maps/extended_kindlmann.json")
load_color_map_resource("resources/color_maps/kindlmann.json")


def get_color_map_data_by_id(color_map_id: str) -> _RGBA8ImageDataType:
    return color_maps.get(color_map_id, color_maps["grayscale"]).data
