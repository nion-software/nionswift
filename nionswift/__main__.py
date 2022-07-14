import argparse
import os
import subprocess
import sys

parser = argparse.ArgumentParser(
    prog="python -m nionswift", description="Launch Nion Swift using Qt or a launcher."
)

parser.add_argument(
    "--ui",
    dest="ui",
    action="store",
    choices=["tool", "qt", "pyqt", "pyside2"],
    help="choose UI frontend",
    default="tool",
)

# python 3.8 compatible
parser.add_argument('--fallback', action='store_true')
parser.add_argument('--no-fallback', dest='fallback', action='store_false')
parser.set_defaults(fallback=True)

# python 3.9+ compatible
# parser.add_argument(
#     "--fallback",
#     dest="fallback",
#     action=argparse.BooleanOptionalAction,
#     help="whether to fallback to other UI frontend if preferred choice is unavailable",
#     default=True,
# )

parsed_args = parser.parse_args()

app = "nionui_app.nionswift"
args = []

order = []

if parsed_args.ui:
    order.append(parsed_args.ui)

if parsed_args.fallback:
    if "tool" not in order:
        order.append("tool")
    if "qt" not in order:
        order.append("qt")

for ui in order:
    if ui == "qt":
        from nionui_app.nionswift import main
        app = main.main({}, {"pyqt": None})
        app.run()
        break
    else:
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
            proc = subprocess.Popen([exe_path, python_prefix, app] + args, universal_newlines=True)
            proc.communicate()
            break
