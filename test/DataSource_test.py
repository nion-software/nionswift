import unittest
import weakref

from nion.swift import DataSource


class TestDataSourceClass(unittest.TestCase):
    class TestImageSourceFactory(object):
        def __init__(self, id, name):
            self.id = id
            self.graphic_url = ''
            self.name = name
        def __str__(self):
            return self.name

    def setUp(self):
        new_values = []
        self.old_values = DataSource.DataSourceManager().reset_(new_values)

    def tearDown(self):
        DataSource.DataSourceManager().reset_(self.old_values)

    def test_singleton(self):
        ds1 = DataSource.DataSourceManager()
        ds2 = DataSource.DataSourceManager()
        self.assertIs(ds1, ds2)

    def test_register(self):
        ds = DataSource.DataSourceManager()
        id = 'one'
        imgsrc = self.TestImageSourceFactory('one', 'One')
        ds.registerDataSourceFactory(imgsrc)
        self.assertIs(ds.getDataSourceFactoryById(id), imgsrc)
        ds.unregisterDataSourceFactory(id)
        with self.assertRaises(KeyError):
            self.assertIsNone(ds.getDataSourceFactoryById(id))
