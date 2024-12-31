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

    def test_session_handler_model(self):
        session_handler = SessionPanel.SessionHandler(ApplicationData.get_session_metadata_model())
        ApplicationData.get_session_metadata_model().microscopist = "Ned Flanders"
        self.assertEqual("Ned Flanders", session_handler.session_model.microscopist)
        session_handler.session_model.site = "Earth"
        self.assertEqual("Earth", ApplicationData.get_session_metadata_model().site)
