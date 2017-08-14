import xmlrpc.client

from . import Classes
from . import Pickler
from . import Structs


proxy = xmlrpc.client.ServerProxy("http://127.0.0.1:8199/", allow_none=True)
api = Classes.API(proxy, None)


def _parse_version(version, count=3, max_count=None):
    max_count = max_count if max_count is not None else count
    version_components = [int(version_component) for version_component in version.split(".")]
    assert len(version_components) <= max_count
    while len(version_components) < count:
        version_components.append(0)
    return version_components


def _compare_versions(version1: str, version2: str) -> int:
    if version1.startswith("~"):
        version1 = version1[1:]
        version_components1 = _parse_version(version1, 1, 3)
        assert len(version_components1) > 1
    elif version1 == "1":  # same as "~1.0"
        version1 = "1.0"
        version_components1 = _parse_version(version1, 2, 3)
    else:
        version_components1 = _parse_version(version1)
    version_components2 = _parse_version(version2)
    # print(version_components1, version_components2)
    for version_component1, version_component2 in zip(version_components1, version_components2):
        if version_component1 > version_component2:
            return 1
        elif version_component1 < version_component2:
            return -1
    return 0


def get_api(version):
    actual_version = "1.0.0"
    if _compare_versions(str(version), actual_version) > 0:
        raise NotImplementedError("API requested version %s is greater than %s." % (version, actual_version))
    return api


try:
    from IPython import get_ipython

    ip = get_ipython()

    if ip:
        svg_f = ip.display_formatter.formatters['image/svg+xml']

        def get_svg(data_item):
            return data_item.data_item_to_svg()

        svg_f.for_type_by_name('nionlib.Proxy', 'DataItem', get_svg)
except ImportError:
    pass


Pickler.all_classes = Classes.API, Classes.Application, Classes.DataGroup, Classes.DataItem, Classes.Display, Classes.DisplayPanel, Classes.DocumentWindow,\
    Classes.Graphic, Classes.HardwareSource, Classes.Instrument, Classes.Library
Pickler.all_structs = Structs.Calibration, Structs.DataAndCalibration
Pickler.struct_names = {Structs.DataAndCalibration: "ExtendedData"}
