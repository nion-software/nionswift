"""
See color maps:
    https://sciviscolor.org/
    http://www.kennethmoreland.com/color-advice/
    https://datascience.lanl.gov/colormaps.html
"""

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
import xml.etree.ElementTree

from nion.utils import Registry

_ = gettext.gettext

_LookupDataArray = numpy.typing.NDArray[typing.Any]
_RGBA8ImageDataType = numpy.typing.NDArray[typing.Any]
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
    out_array: typing.List[numpy.typing.NDArray[typing.Any]] = []
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
        rgb: numpy.typing.NDArray[typing.Any] = numpy.array([b, g, r])
        ix = int(math.floor(x * (n - 1)))
        if last_ix is None:
            out_array.append(numpy.copy(rgb))
        elif ix > last_ix:
            amount = (rgb - last_rgb) / (ix - last_ix)
            for x in range(ix - last_ix):
                out_array.append(numpy.rint(last_rgb + amount * (x + 1)))
        else:
            assert ix >= last_ix
        last_ix = ix
        last_rgb = numpy.copy(rgb)
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
    color_map_id: str
    name: str
    data: _RGBA8ImageDataType


color_maps: typing.Dict[str, ColorMap] = dict()

def add_color_map(color_map: ColorMap) -> None:
    color_maps[color_map.color_map_id] = color_map

add_color_map(ColorMap("grayscale", _("Grayscale"), generate_lookup_array_grayscale()))
add_color_map(ColorMap("magma", _("Magma"), generate_lookup_array('magma')))
add_color_map(ColorMap("hsv", _("HSV"), generate_lookup_array_hsv()))
add_color_map(ColorMap("viridis", _("Viridis"), generate_lookup_array('viridis')))
add_color_map(ColorMap("plasma", _("Plasma"), generate_lookup_array('plasma')))
add_color_map(ColorMap("ice", _("Ice"), generate_lookup_array('ice')))


def get_color_map_id_from_name(name: str) -> str:
    color_map_id = name.lower()
    color_map_id = re.sub(r"[^\w\s]", '', color_map_id)
    color_map_id = re.sub(r"\s+", '-', color_map_id)
    return color_map_id


def load_color_map_json_str(color_map_json_str: str) -> None:
    color_map_json = json.loads(color_map_json_str)
    color_map_id = color_map_json["id"]
    add_color_map(ColorMap(color_map_id, color_map_json["name"], generate_lookup_array_from_points(color_map_json["points"], 256)))


def load_color_map_xml_str(color_map_xml_str: str, name: str, color_map_id: str) -> None:
    tree_root = xml.etree.ElementTree.fromstring(color_map_xml_str)
    assert tree_root.tag == "ColorMaps"
    color_map_tree = list(tree_root)[0]
    assert color_map_tree.tag == "ColorMap"
    raw_points = [point_tree.attrib for point_tree in color_map_tree]
    points: _PointsType = list()
    for raw_point in raw_points:
        if "x" in raw_point:
            points.append({"x": float(raw_point['x']), "r": float(raw_point['r']), "g": float(raw_point['g']),
                           "b": float(raw_point['b'])})
    add_color_map(ColorMap(color_map_id, name, generate_lookup_array_from_points(points, 256)))
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


def load_color_maps(color_maps_dir: pathlib.Path) -> None:
    for root, dirs, files in os.walk(color_maps_dir):
        for file in files:
            color_map_path = pathlib.Path(root) / file
            if not color_map_path.name.startswith("."):
                color_map_file_extension = color_map_path.suffix
                try:
                    if color_map_file_extension == ".json":
                        with open(color_map_path, "r") as f:
                            load_color_map_json_str(f.read())
                    elif color_map_file_extension == ".xml":
                        with open(color_map_path, "r") as f:
                            xml_str = f.read()
                            load_color_map_xml_str(xml_str, color_map_path.stem, get_color_map_id_from_name(color_map_path.stem))
                except Exception as e:
                    import traceback
                    traceback.print_exc()


def load_color_map_from_dict(d: typing.Mapping[str, typing.Any]) -> None:
    color_map_id = d["id"]
    color_map_name = d["name"]
    color_map_points = d["points"]
    add_color_map(ColorMap(color_map_id, color_map_name, generate_lookup_array_from_points(color_map_points, 256)))


def load_color_map_resource(resource_path: str) -> None:
    bytes = pkgutil.get_data(__name__, resource_path)
    assert bytes is not None
    load_color_map_json_str(bytes.decode("utf-8"))


load_color_map_resource("resources/color_maps/black_body.json")
load_color_map_resource("resources/color_maps/extended_black_body.json")
load_color_map_resource("resources/color_maps/extended_kindlmann.json")
load_color_map_resource("resources/color_maps/kindlmann.json")


def get_color_map_data_by_id(color_map_id: str) -> _RGBA8ImageDataType:
    return color_maps.get(color_map_id, color_maps["grayscale"]).data


class ColorMapProtocol(typing.Protocol):
    color_map_id: str
    name: str
    data: typing.Optional[_RGBA8ImageDataType] = None
    json_str: typing.Optional[str] = None
    xml_str: typing.Optional[str] = None


def component_registered(component: Registry._ComponentType, component_types: typing.Set[str]) -> None:
    if "color-map-description" in component_types:
        color_map_description = typing.cast(ColorMapProtocol, component)
        if hasattr(color_map_description, "data") and color_map_description.data is not None:
            add_color_map(ColorMap(color_map_description.color_map_id, color_map_description.name, color_map_description.data))
        elif hasattr(color_map_description, "json_str") and color_map_description.json_str is not None:
            load_color_map_json_str(color_map_description.json_str)
        elif hasattr(color_map_description, "xml_str") and color_map_description.xml_str is not None:
            load_color_map_xml_str(color_map_description.xml_str, color_map_description.name, color_map_description.color_map_id)


def component_unregistered(component: Registry._ComponentType, component_types: typing.Set[str]) -> None:
    if "color-map-description" in component_types:
        pass


_component_registered_listener = Registry.listen_component_registered_event(component_registered)
_component_unregistered_listener = Registry.listen_component_unregistered_event(component_unregistered)

Registry.fire_existing_component_registered_events("color-map-dict")
Registry.fire_existing_component_registered_events("color-map-json-str")
Registry.fire_existing_component_registered_events("color-map-xml-str")
