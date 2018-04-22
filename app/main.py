import os
import sys
import warnings

def main(args, bootstrap_args):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "nionutils"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "nionui"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "niondata"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "nionswift"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "nionswift-instrumentation-kit"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "nionswift-io"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "eels-analysis"))
    # these imports need to occur AFTER the args are parsed and the path
    # is updated accordingly.
    from nion.swift import Facade
    from nion.swift import Application
    from nion.ui import Application as ApplicationUI
    warnings.simplefilter("always", RuntimeWarning)
    Facade.initialize()
    app = Application.Application(ApplicationUI.make_ui(bootstrap_args), resources_path=os.path.dirname(__file__))
    app.initialize()
    Facade.start_server()
    return app
