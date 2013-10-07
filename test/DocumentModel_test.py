# standard libraries
import unittest

# third party libraries
# None

# local libraries
from nion.swift import DocumentModel


class TestDocumentModelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass
