# type: ignore

import importlib
import os
import sys
import typing


def load_module_as_path(path: str) -> typing.Any:
    if os.path.isfile(path):
        dirname = os.path.dirname(path)
        module_name = os.path.splitext(os.path.basename(path))[0]
        sys.path.insert(0, dirname)
        module = importlib.import_module(module_name)
        return getattr(module, "main", None)
    return None


def load_module_as_package(package: str) -> typing.Any:
    try:
        module = importlib.import_module(package)
        main_fn = getattr(module, "main", None)
        if main_fn:
            return main_fn
    except ImportError:
        pass
    try:
        module = importlib.import_module(package + ".main")
        main_fn = getattr(module, "main", None)
        if main_fn:
            return main_fn
    except ImportError:
        pass
    return None


def load_module_local(path:typing.Optional[str]=None) -> typing.Any:
    try:
        if path:
            sys.path.insert(0, path)
        module = importlib.import_module("main")
        main_fn = getattr(module, "main", None)
        if main_fn:
            return main_fn
    except ImportError:
        pass
    return None


def bootstrap_main(args: typing.Any) -> typing.Tuple[typing.Any, typing.Optional[str]]:
    """
    Main function explicitly called from the C++ code.
    Return the main application object.
    """
    version_info = sys.version_info
    if version_info.major != 3 or version_info.minor < 6:
        return None, "python36"
    main_fn = load_module_as_package("nionui_app.nionswift")
    if main_fn:
        return main_fn(["nionui_app.nionswift"] + args, {"pyqt": None}), None
    return None, "main"


def main() -> None:

    # first, attempt to launch using nionswift-tool
    try:
        from nion.nionswift_tool import command
        command.launch(sys.argv)
        return
    except ImportError:
        pass

    success = False

    # next attempt to launch using pyside6
    try:
        from PySide6 import QtCore
        success = True
    except ImportError:
        pass

    if not success:
        print("Please install either pyside6 using pip or conda or use nionswift-tool to launch.")

    if success:
        app, error = bootstrap_main(sys.argv)

        if app:
            app.run()
        else:
            print("Error: " + (error or "unknown"))


if __name__ == '__main__':
    main()
