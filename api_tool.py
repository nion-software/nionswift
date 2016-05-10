# python api_tool.py --classes api_public > ../typeshed/nion/typeshed/API_1_0.py
# python api_tool.py --classes hardware_source_public > ../typeshed/nion/typeshed/HardwareSource_1_0.py

import argparse
import importlib
import inspect
import typing

parser = argparse.ArgumentParser(description='Generate API type stub files.')
parser.add_argument('--classes', dest='class_list_property', required=True, help='Class list property')
args = parser.parse_args()

module = importlib.import_module("nion.swift.Facade")
class_list_property = args.class_list_property

class_dicts = dict()

for member in inspect.getmembers(module, predicate=inspect.isclass):
    class_name = member[0]
    # print("### {}".format(class_name))
    if class_name in getattr(module, class_list_property):
        # print("### getattr(module, class_list_property) {}".format(class_name))
        class_dict = dict()
        class_dict["name"] = class_name
        class_dict["doc"] = member[1].__doc__
        member_public = member[1].public
        for member_member in inspect.getmembers(member[1], predicate=lambda x: isinstance(x, property)):
            if member_member[0] in member_public:
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
        for method_member in inspect.getmembers(member[1], predicate=lambda x: inspect.isfunction):
            function_name = method_member[0]
            if function_name in member_public and function_name not in class_dict.get("properties", dict()):
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

    if type(annotation) == str:
        annotation = getattr(module, annotation)
        return "\"{}\"".format(annotation.__name__)

    if annotation == float:
        return "float"
    if annotation == int:
        return "int"
    if annotation == str:
        return "str"
    if annotation == dict:
        return "dict"
    if annotation.__name__ == "Calibration":
        return "Calibration.Calibration"
    if annotation.__name__ == "DataAndMetadata":
        return "DataAndMetadata.DataAndMetadata"
    if annotation.__name__ == "FloatPoint":
        return "Geometry.FloatPoint"

    classes = ["Application", "DataGroup", "DataItem", "Display", "DisplayPanel", "DocumentController", "Graphic", "HardwareSource", "Instrument",
        "Library", "RecordTask", "Region", "ViewTask"]

    if annotation.__name__ in classes:
        return annotation.__name__

    if annotation.__name__ == "ndarray":
        return "numpy.ndarray"
    if issubclass(annotation, typing.List):
        return "List[{}]".format(annotation_to_str(annotation.__parameters__[0]))
    if isinstance(annotation, type):
        class_ = annotation.__class__
        if class_ is not None:
            return class_.__qualname__
        return dir(annotation)
    return str(annotation)

def default_to_str(default):
    return "={}".format(default)

print("import numpy")
print("from typing import List")
print("from nion.data import Calibration")
print("from nion.data import DataAndMetadata")
print("from nion.utils import Geometry")

for class_name in getattr(module, class_list_property):
    class_dict = class_dicts[class_name]
    class_name = class_dict["name"]
    class_name = getattr(module, "alias", dict()).get(class_name, class_name)
    doc = class_dict.get("doc")
    print("")
    print("")
    print("class {}:".format(class_name))
    if class_name == "API":
        print("    version = \"~1.0\"")
    if doc:
        print("    \"\"\"{}\"\"\"".format(doc))
    class_functions_dict = class_dict.get("functions", dict())
    for member_name in sorted(class_functions_dict.keys()):
        argspec = class_functions_dict[member_name]["fullargspec"]
        # print("    ### {}".format(argspec))
        doc = class_functions_dict[member_name].get("doc")
        arg_strings = list()
        for arg in argspec.args:
            annotation = argspec.annotations.get(arg)
            if annotation is not None:
                arg_strings.append("{}: {}".format(arg, annotation_to_str(annotation)))
            else:
                arg_strings.append("{}".format(arg))
        default_count = len(argspec.defaults) if argspec.defaults else 0
        for index in range(default_count):
            arg_index = -default_count + index
            arg_strings[arg_index] = "{}{}".format(arg_strings[arg_index], default_to_str(argspec.defaults[index]))
        if "return" in argspec.annotations:
            return_type = " -> {}".format(annotation_to_str(argspec.annotations["return"]))
        else:
            return_type = ""
        print("")
        print("    def {}({}){}:".format(member_name, ", ".join(arg_strings), return_type))
        if doc:
            print("        \"\"\"{}\"\"\"".format(doc))
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
            print("    def {}(self){}:".format(property_name, property_return_str))
            if doc:
                print("        \"\"\"{}\"\"\"".format(doc))
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
            print("    def {}(self, value{}) -> None:".format(property_name, property_type_str))
            if doc:
                print("        \"\"\"{}\"\"\"".format(doc))
            print("        ...")
