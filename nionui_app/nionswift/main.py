import typing
import warnings

from nion.swift import Application
from nion.swift import Facade
from nion.ui import Application as ApplicationUI


def main(args: list[typing.Any], bootstrap_args: dict[str, typing.Any]) -> Application.Application:
    # from nion.swift import Application
    warnings.simplefilter("always", RuntimeWarning)
    Facade.initialize()
    app = Application.Application(ApplicationUI.make_ui(bootstrap_args))
    app.initialize(use_root_dir=False)
    Facade.start_server()
    return app
