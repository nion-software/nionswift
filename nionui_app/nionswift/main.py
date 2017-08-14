import os
import warnings

def main(args, bootstrap_args):
    from nion.swift import Facade
    from nion.swift import Application
    from nion.ui import Application as ApplicationUI
    warnings.simplefilter("always", RuntimeWarning)
    Facade.initialize()
    app = Application.Application(ApplicationUI.make_ui(bootstrap_args), resources_path=os.path.dirname(__file__))
    app.initialize(use_root_dir=False)
    Facade.start_server()
    return app
