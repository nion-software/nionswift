# -*- coding: utf-8 -*-

import setuptools
import os

setuptools.setup(
    name="nionswift",
    version="0.13.4",
    packages=["nion.swift", "nion.swift.model", "nion.swift.test", "nionui_app.nionswift", "nionswift_plugin.none", "nionlib", "nion.typeshed"],
    package_data={"nion.swift": ["resources/*"]},
    install_requires=['scipy', 'numpy', 'h5py', 'pytz', 'tzlocal', 'pillow', 'nionutils', 'niondata>=0.13.2', 'nionui', 'nionswift-io'],
    classifiers=[
        "Development Status :: 2 - Pre-Alpha"
    ],
    include_package_data=True,
    test_suite="nion.swift.test",
    entry_points={
        'console_scripts': [
            'nionswift=nion.swift.command:main',
            ],
        },
)
