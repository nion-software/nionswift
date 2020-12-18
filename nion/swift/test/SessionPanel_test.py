# standard libraries
import contextlib
import unittest

# third party libraries
# None

# local libraries
from nion.swift import SessionPanel
from nion.swift.model import ApplicationData
from nion.swift.test import TestContext


class TestSessionPanelClass(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()

    def tearDown(self):
        TestContext.end_leaks(self)

    def test_session_panel_controller_notifies_fields_changed(self):
        session_panel_controller = SessionPanel.SessionPanelController()
        with contextlib.closing(session_panel_controller):
            fields = dict()

            def fields_changed(d):
                fields.update(d)

            session_panel_controller.on_fields_changed = fields_changed

            ApplicationData.get_session_metadata_model().microscopist = "Ned Flanders"
            ApplicationData.get_session_metadata_model().site = "Earth"

            self.assertEqual({"microscopist": "Ned Flanders", "site": "Earth"}, fields)
