# futures
from __future__ import absolute_import

# standard libraries
import contextlib
import logging
import os
import shutil
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift.model import Cache
from nion.ui import TestUI


class TestApplicationClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_switching_library_closes_document_only_once(self):
        current_working_directory = os.getcwd()
        workspace1_dir = os.path.join(current_working_directory, "__Test1")
        workspace2_dir = os.path.join(current_working_directory, "__Test2")
        Cache.db_make_directory_if_needed(workspace1_dir)
        Cache.db_make_directory_if_needed(workspace2_dir)
        try:
            app = Application.Application(TestUI.UserInterface(), set_global=False)
            app.initialize(load_plug_ins=False)
            app.start(True, fixed_workspace_dir=workspace1_dir)
            app.switch_library(workspace2_dir, skip_choose=True, fixed_workspace_dir=workspace2_dir)
            app.exit()
            app.deinitialize()
        finally:
            #logging.debug("rmtree %s", workspace_dir)
            shutil.rmtree(workspace1_dir)
            shutil.rmtree(workspace2_dir)

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
