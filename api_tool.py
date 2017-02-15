# python api_tool.py --classes api_public --level release > ../typeshed/nion/typeshed/API_1_0.py
# python api_tool.py --classes api_public --level release prerelease > ../typeshed/nion/typeshed/API_1_0_prerelease.py
# python api_tool.py --classes hardware_source_public --level release > ../typeshed/nion/typeshed/HardwareSource_1_0.py
# python api_tool.py --classes nionlib_public --level release --proxy > ../PlugIns/Connection/NionLib/nionlib/Classes.py

import argparse
import importlib
import inspect
import typing

parser = argparse.ArgumentParser(description='Generate API type stub files.')
parser.add_argument('--classes', dest='class_list_property', required=True, help='Class list property')
parser.add_argument('--levels', dest='levels', required=True, nargs='+', help='Level property')
parser.add_argument('--proxy', dest='is_proxy', required=False, nargs='?', const=True, default=False, help='Whether to generate proxy function bodies')
args = parser.parse_args()

module = importlib.import_module("nion.swift.Facade")
class_list_property = args.class_list_property
levels = args.levels
is_proxy = args.is_proxy

class_dicts = dict()

# find members of the module which are classes
for member in inspect.getmembers(module, predicate=inspect.isclass):
    class_name = member[0]
    # print("### {}".format(class_name))
    # check to see whether the class_name is in the exported classes (class_list_property)
    if class_name in getattr(module, class_list_property):
        # print("### getattr(module, class_list_property) {}".format(class_name))
        # create a dict to represent this class
        class_dict = dict()
        class_dict["name"] = class_name
        class_dict["doc"] = member[1].__doc__
        # build a list of members that are listed at the appropriate 'level' for export
        members = list()
        for level in levels:
            members.extend(getattr(member[1], level, list()))
        class_dict["threadsafe"] = getattr(member[1], "threadsafe", list())
        # scan through the properties of the class and add their info to the member info
        for member_member in inspect.getmembers(member[1], predicate=lambda x: isinstance(x, property)):
            if member_member[0] in members:
                property_dict = class_dict.setdefault("properties", dict()).setdefault(member_member[0], dict())
                function_get = member_member[1].fget
                if function_get:
                    if function_get.__annotations__:
                        property_dict.setdefault("get", dict())["annotations"] = function_get.__annotations__
                    if function_get.__doc__:
                        property_dict.setdefault("get", dict())["doc"] = function_get.__doc__
                function_set = member_member[1].fset
                if function_set:
                    if function_set.__annotations__:
                        property_dict.setdefault("set", dict())["annotations"] = function_set.__annotations__
                    if function_set.__doc__:
                        property_dict.setdefault("set", dict())["doc"] = function_set.__doc__
        # scan through the functions of the class and add their info to the member info
        for method_member in inspect.getmembers(member[1], predicate=lambda x: inspect.isfunction):
            function_name = method_member[0]
            if function_name in members and function_name not in class_dict.get("properties", dict()):
                function_dict = class_dict.setdefault("functions", dict()).setdefault(function_name, dict())
                function = method_member[1]
                function_dict["fullargspec"] = inspect.getfullargspec(function)
                if function.__doc__:
                    function_dict["doc"] = function.__doc__
        class_dicts[class_name] = class_dict

# pprint.pprint(class_dicts)

def annotation_to_str(annotation):
    if annotation is None:
        return "None"

    annotation_name = getattr(annotation, "__name__", None)

    if type(annotation) == str:
        annotation = getattr(module, annotation)
        return "\"{}\"".format(annotation.__name__)

    if annotation == bool:
        return "bool"
    if annotation == float:
        return "float"
    if annotation == int:
        return "int"
    if annotation == str:
        return "str"
    if annotation == dict:
        return "dict"
    if annotation_name == "Calibration":
        return "Calibration.Calibration"
    if annotation_name == "DataAndMetadata":
        return "DataAndMetadata.DataAndMetadata"
    if annotation_name == "DataDescriptor":
        return "DataAndMetadata.DataDescriptor"
    if annotation_name == "FloatPoint":
        return "Geometry.FloatPoint"

    classes = ["Application", "DataGroup", "DataItem", "Display", "DisplayPanel", "DocumentWindow", "Graphic", "HardwareSource", "Instrument",
        "Library", "RecordTask", "Region", "ViewTask"]

    if annotation_name in classes:
        return annotation_name

    if annotation_name == "ndarray":
        return "numpy.ndarray"
    if annotation_name == typing.List.__name__:
        return "typing.List[{}]".format(annotation_to_str(annotation.__args__[0]))
    if annotation_name == typing.Sequence.__name__:
        return "typing.Sequence[{}]".format(annotation_to_str(annotation.__args__[0]))
    if annotation_name == typing.Tuple.__name__:
        return "typing.Tuple[{}]".format(", ".join(annotation_to_str(tuple_param) for tuple_param in annotation.__args__))
    if annotation_name == "Union":
        return "typing.Union[{}]".format(", ".join(annotation_to_str(union_param) for union_param in annotation.__union_params__))
    if isinstance(annotation, type):
        class_ = annotation.__class__
        if class_ is not None:
            return f"{annotation.__module__}.{annotation.__qualname__}"
        return dir(annotation)
    return str(annotation)

def default_to_str(default):
    return "={}".format(default)

if is_proxy:
    print("from .Pickler import Unpickler")
else:
    print("import datetime")
    print("import numpy")
    print("import typing")
    print("import uuid")
    print("from nion.data import Calibration")
    print("from nion.data import DataAndMetadata")
    print("from nion.utils import Geometry")

for class_name in getattr(module, class_list_property):
    class_dict = class_dicts[class_name]
    class_name = class_dict["name"]
    class_name = getattr(module, "alias", dict()).get(class_name, class_name)
    doc = class_dict.get("doc")
    threadsafe = class_dict.get("threadsafe")
    print("")
    print("")
    print("class {}:".format(class_name))
    if doc and not is_proxy:
        print("    \"\"\"{}\"\"\"".format(doc))
    if is_proxy:
        print("")
        print("    def __init__(self, proxy, specifier):")
        print("        self.__proxy = proxy")
        print("        self.specifier = specifier")
    class_functions_dict = class_dict.get("functions", dict())
    for member_name in sorted(class_functions_dict.keys()):
        argspec = class_functions_dict[member_name]["fullargspec"]
        # print("    ### {}".format(argspec))
        doc = class_functions_dict[member_name].get("doc")
        raw_arg_strings = list()
        arg_strings = list()
        for arg in argspec.args:
            annotation = argspec.annotations.get(arg)
            if annotation is not None:
                arg_strings.append("{}: {}".format(arg, annotation_to_str(annotation)))
            else:
                arg_strings.append("{}".format(arg))
            raw_arg_strings.append("{}".format(arg))
        default_count = len(argspec.defaults) if argspec.defaults else 0
        for index in range(default_count):
            arg_index = -default_count + index
            arg_strings[arg_index] = "{}{}".format(arg_strings[arg_index], default_to_str(argspec.defaults[index]))
        if "return" in argspec.annotations:
            return_type = " -> {}".format(annotation_to_str(argspec.annotations["return"]))
            is_return_none = argspec.annotations["return"] is None
        else:
            return_type = ""
            is_return_none = False
        print("")
        if is_proxy:
            print("    def {}({}):".format(member_name, ", ".join(raw_arg_strings)))
        else:
            print("    def {}({}){}:".format(member_name, ", ".join(arg_strings), return_type))
        if doc and not is_proxy:
            print("        \"\"\"{}\"\"\"".format(doc))
        if is_proxy:
            arg_str = "".join(", " + raw_arg_string for raw_arg_string in raw_arg_strings[1:])
            is_threadsafe = member_name in threadsafe
            if is_return_none:
                if is_threadsafe:
                    print("        Unpickler.call_threadsafe_method(self.__proxy, self, '{}'{})".format(member_name, arg_str))
                else:
                    print("        Unpickler.call_method(self.__proxy, self, '{}'{})".format(member_name, arg_str))
            else:
                if is_threadsafe:
                    print("        return Unpickler.call_threadsafe_method(self.__proxy, self, '{}'{})".format(member_name, arg_str))
                else:
                    print("        return Unpickler.call_method(self.__proxy, self, '{}'{})".format(member_name, arg_str))
        else:
            print("        ...")
    class_properties_dict = class_dict.get("properties", dict())
    for property_name in sorted(class_properties_dict.keys()):
        get_dict = class_properties_dict[property_name].get("get")
        if get_dict:
            property_return_str = str()
            doc = get_dict.get("doc")
            annotations = get_dict.get("annotations", dict())
            if "return" in annotations:
                property_return_str = " -> {}".format(annotation_to_str(annotations["return"]))
            print("")
            print("    @property")
            if is_proxy:
                print("    def {}(self):".format(property_name))
            else:
                print("    def {}(self){}:".format(property_name, property_return_str))
            if doc and not is_proxy:
                print("        \"\"\"{}\"\"\"".format(doc))
            if is_proxy:
                print("        return Unpickler.get_property(self.__proxy, self, '{}')".format(property_name))
            else:
                print("        ...")
        set_dict = class_properties_dict[property_name].get("set")
        if set_dict:
            doc = set_dict.get("doc")
            annotations = set_dict.get("annotations", dict())
            property_type_str = str()
            for k, v in annotations.items():
                if k != "return":
                    property_type_str = ": {}".format(annotation_to_str(v))
            print("")
            # print("    ### {}".format(annotations))
            print("    @{}.setter".format(property_name))
            if is_proxy:
                print("    def {}(self, value):".format(property_name))
            else:
                print("    def {}(self, value{}) -> None:".format(property_name, property_type_str))
            if doc and not is_proxy:
                print("        \"\"\"{}\"\"\"".format(doc))
            if is_proxy:
                print("        Unpickler.set_property(self.__proxy, self, '{}', value)".format(property_name))
            else:
                print("        ...")
if not is_proxy:
    print("")
    print("version = \"~1.0\"")
