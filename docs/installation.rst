.. _installation:

Nion Swift Installation
=======================
To install Nion Swift, you will need to install a Python environment with some specific Python packages. When you
initially launch the application, it will ask you for the directory of that Python environment.

As an open source project, there are many possible installation scenarios such as for offline use, for use on a
Nion electron microscope, or for open source development. In addition, Python installation itself is highly flexible.
Some Python installations will be used with other software, and others specifically with Nion Swift.

This guide mainly covers the offline use case with a broad Python environment dedicated to Nion Swift usage.

Python Environment
------------------
To use Nion Swift for offline use, you will need to install a Python environment. We recommend have a dedicated
Python installation that is only used for Nion Swift.

You will first need to install Python for your specific platform.

Nion Swift has been tested extensively with the *Anaconda* Python distribution and we recommend using that. The
Anaconda distribution includes a wide range of preinstalled Python packages, including everything required for
Nion Swift. If you are familiar with Python and wish to use a smaller distribution, you may also consider using
*Miniconda*.

We recommend using Python 3.6 or later for best performance, although the application is compatible with Python 3.5.

The Python environment requires the ``scipy``, ``pytz``, and ``h5py`` packages as a minimum installation requirement.
The Anaconda distribution includes these by default. The Miniconda installation will require them to be installed
explicitly.

Begin by installing Anaconda or Miniconda on your system.

We recommend installing Python to the default location,
although you may want to customize the location if you are installing more than one version of Nion Swift or if you
want to keep Nion Swift fully separated from other Python use.

We do not recommend adding Python to your command line PATH, which the installers will give you the option to do.

    * `Anaconda <https://www.anaconda.com/download/>`_
    * `Miniconda <https://conda.io/miniconda.html>`_

Ensure that ``scipy``, ``pytz``, and ``h5py`` if you have installed Miniconda. ::

    $ \path\to\python\Scripts\conda install scipy h5py pytz

Windows
-------
Nion Swift for Windows requires Windows 7 or later, although we recommend Windows 10 for best compatibility.

Nion Swift for Windows requires you to install the Microsoft Visual C++ Redistributable for Visual Studio 2015.

    * Install Anaconda or Miniconda (see above)
    * `Visual C++ Redistributable for Visual Studio 2015 <https://www.microsoft.com/en-us/download/details.aspx?id=48145>`_
    * `Download Nion Swift 0.12.0 for Windows <http://nion.com/swift/files/NionSwift_Windows_np112py36_0.12.0.zip>`_
    * md5 checksum e4e09b7f213f81a40e8f13488e64a1b8

Run the `Swift.exe` program within the unzipped directory.

The first time you run Nion Swift, it will ask you to locate your Python directory. Point it to the directory you
specified when you installed Anaconda or Miniconda.

You can also create a shortcut to `Swift.exe` and pass the Python directory as an argument to the shortcut.

Right-click on the ``Swift.exe`` program and choose `Create Shortcut`. Now right click on the newly created shortcut
and add the path to your Python installation after the path to ``Swift.exe``. Now when you click on the shortcut, it
will automatically launch Nion Swift with the specified Python environment.

Creating multiple shortcuts allows you to run Nion Swift with different Python environments.

You can also launch Nion Swift from ``PowerShell`` or the ``Command Prompt`` by running ``Swift.exe`` and passing
the path to the Python environment as the first parameter on the command line. ::

    $ \path\to\Swift.exe C:\Miniconda3

MacOS
-----
Nion Swift for macOS requires macOS 10.11 or later. We recommend using the latest version of macOS.

    * Install Anaconda or Miniconda (see above)
    * `Download Nion Swift 0.12.0 for macOS <http://nion.com/swift/files/NionSwift_MacOS_np112py36_0.12.0.zip>`_
    * md5 checksum 291514cd29ab13c7f049599638c2c1a2

Run the NionSwift program within the unzipped directory.

.. note::
    While Nion Swift runs fine by double clicking on the ``Nion Swift``, you will not be able to see any diagnostic
    output. To run Nion Swift and see diagnostic output, you will need to run it using ``Terminal`` and specify the
    full path to the executable using ``$ /path/to/NionSwift.app/Contents/MacOS/NionSwift``.

Linux
-----
Nion Swift for Linux requires Qt 5.5 or later (qt5-default), Python 3.5 or later, and packages scipy, h5py, and pytz to
be installed.

Swift has been tested with Ubuntu 16.04, 17.04, 17.10, Debian 9, Fedora 26. It is not compatible with Debian 8 (Qt 5.3)
but please contact us if you need to run on Debian 8 as there may be workarounds.

    * Install Anaconda or Miniconda (see above)
    * Install qt5-default (`sudo apt-get qt5-default`)
    * `Download Nion Swift 0.12.0 for Linux <http://nion.com/swift/files/NionSwift_Linux_np112py36_0.12.0.zip>`_
    * md5 checksum 6ee351e3e83a273df9e73368dd571ead

Run the NionSwift program within the unzipped directory from ``Terminal``.

Installing Nion Swift Extensions
--------------------------------
Extensions for Nion Swift can be installed in your Python directory using the ``pip`` installation tool.

For example, although it is currently not available on PyPI (the Python repository for packages), if it were, you
could install the Nion STEM microscope simulator using the following command. ::

    $ pip install nionswift-usim

After restarting Nion Swift, the microscope simulator would be available within Nion Swift.

If you need to install a specific extension now, you can download the package from GitHub and install it manually.

For the example above, you would download ``nionswift-usim`` from its
`GitHub project page <https://github.com/nion-software/nionswift-usim>`_ or directly from its download link
`nionswift-usim zip file <https://github.com/nion-software/nionswift-usim/archive/master.zip>`_. Then you would
unzip the file and install it using the following commands. ::

    $ cd nionswift-usim
    $ python setup.py install
