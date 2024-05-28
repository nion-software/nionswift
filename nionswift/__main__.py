import argparse
import os
import subprocess
import sys
import typing

parser = argparse.ArgumentParser(
    prog="python -m nionswift", description="Launch Nion Swift using native launcher or pyside6 libraries."
)

parser.add_argument(
    "--ui",
    dest="ui",
    action="store",
    choices=["tool", "qt"],
    help="choose UI frontend",
    default="tool",
)

parser.add_argument(
    "--fallback",
    dest="fallback",
    action=argparse.BooleanOptionalAction,
    help="whether to fall back to other UI frontend if preferred choice is unavailable",
    default=True,
)

parsed_args = parser.parse_args()

app_id = "nionui_app.nionswift"
args = list[typing.Any]()

order = list[str]()

if parsed_args.ui:
    order.append(parsed_args.ui)

# if using fallback, add tool and qt to order if not already present.
if parsed_args.fallback:
    if "tool" not in order:
        order.append("tool")
    if "qt" not in order:
        order.append("qt")

# go through the ui preferences in order
for ui in order:
    if ui == "qt":
        # launch the app using the pyside6 qt frontend
        from nionui_app.nionswift import main
        app = main.main(list(), {"qt": None})
        app.run()
        break
    else:
        # launch using the tool frontend
        if sys.platform == "darwin":
            exe_path = os.path.join(sys.exec_prefix, "bin", "Nion Swift.app", "Contents", "MacOS", "Nion Swift")
        elif sys.platform == "linux":
            exe_path = os.path.join(sys.exec_prefix, "bin", "NionSwiftLauncher", "NionSwiftLauncher")
        elif sys.platform == "win32":
            exe_path = os.path.join(sys.exec_prefix, "Scripts", "NionSwiftLauncher", "NionSwift.exe")
        else:
            exe_path = None
        if exe_path:
            python_prefix = sys.prefix
            proc = subprocess.Popen([exe_path, python_prefix, app_id] + args, universal_newlines=True)
            proc.communicate()
            break
