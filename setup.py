# -*- coding: utf-8 -*-

import setuptools
import os

setuptools.setup(
    name="nionswift",
    version="0.0.1",
    packages=["nion.swift", "nion.swift.model", "nionui_app.nionswift", "nionswift_plugin", "nionlib", "nion.typeshed"],
    namespace_packages=["nion", "nionswift_plugin"],
    install_requires=['scipy', 'numpy', 'h5py', 'pytz', 'tzlocal', 'nionutils', 'niondata', 'nionui'],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha"
    ],
    include_package_data=True,
    test_suite="nion.swift.test"
)
