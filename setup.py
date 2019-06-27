# -*- coding: utf-8 -*-

import setuptools
import os

setuptools.setup(
    name="nionswift",
    version="0.14.5",
    author="Nion Software",
    author_email="swift@nion.com",
    description="Nion Swift: Scientific Image Processing",
    long_description=open("README.rst").read(),
    url="https://github.com/nion-software/nionswift",
    packages=["nion.swift", "nion.swift.model", "nion.swift.test", "nionui_app.nionswift", "nionswift_plugin.none", "nionlib", "nion.typeshed"],
    package_data={"nion.swift": ["resources/*"], "nion.swift.model": ["resources/color_maps/*"]},
    install_requires=['scipy', 'numpy', 'h5py', 'pytz', 'tzlocal', 'imageio', 'pillow', 'nionutils>=0.3.17', 'niondata>=0.13.6', 'nionui>=0.3.24', 'nionswift-io'],
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
