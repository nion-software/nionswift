# standard libraries
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import Profile
from nion.ui import TestUI


Facade.initialize()


def create_memory_profile_context():
    return Profile.MemoryProfileContext()


class TestProjectClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass
