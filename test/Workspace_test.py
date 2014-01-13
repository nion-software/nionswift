# standard libraries
import logging
import unittest

# third party libraries
# None

# local libraries
from nion.swift import Application
from nion.swift import Workspace
from nion.swift.test import DocumentController_test
from nion.ui import UserInterface
from nion.ui import Test


class TestWorkspaceClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_change_layout(self):
        document_controller = DocumentController_test.construct_test_document(self.app, workspace_id="library")
        document_controller.workspace.change_layout("1x1")
        document_controller.workspace.change_layout("1x1")
        document_controller.workspace.change_layout("2x1")
        document_controller.workspace.change_layout("3x1")
        document_controller.workspace.change_layout("2x2")
        document_controller.workspace.change_layout("3x2")
        document_controller.workspace.change_layout("1x2")
        document_controller.workspace.change_layout("1x1")

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
