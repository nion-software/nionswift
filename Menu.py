# standard libraries
import gettext
import logging

# third party libraries
# None

# local libraries
from nion.swift.Decorators import singleton
from nion.swift import UserInterface

_ = gettext.gettext


# TODO: make menus, actions removable


class Action(object):

    def __init__(self, ui, action_id, title):
        self.ui = ui
        self.action_id = action_id
        self.title = title
        self._qt_action = None
        self.qt_action_manager = None
        self.key_sequence = None

    def create(self):
        pass

    def __get_qt_action(self):
        self.create()
        return self._qt_action
    qt_action = property(__get_qt_action)

    def configure(self):
        if self.key_sequence:
            self.ui.Actions_setShortcut(self.qt_action_manager, self.action_id, self.key_sequence)


class ApplicationAction(Action):

    def __init__(self, ui, action_id, title, callback):
        Action.__init__(self, ui, action_id, title)
        self.callback = callback

    def create(self):
        if self._qt_action is None:
            self._qt_action = self.ui.Actions_createApplicationAction(self.qt_action_manager, self.action_id, self.title, True)

    def adjustApplicationAction(self):
        self.ui.Actions_enableAction(self.qt_action_manager, self.action_id)

    def adjustDocumentAction(self, document_controller):
        pass

    def execute(self):
        self.callback()


class DocumentAction(Action):

    def __init__(self, ui, action_id, title, callback):
        Action.__init__(self, ui, action_id, title)
        self.callback = callback

    def create(self):
        if self._qt_action is None:
            self._qt_action = self.ui.Actions_createApplicationAction(self.qt_action_manager, self.action_id, self.title, False)

    def adjustApplicationAction(self):
        pass

    def adjustDocumentAction(self, document_controller):
        self.ui.Actions_enableAction(self.qt_action_manager, self.action_id)

    def execute(self, document_controller):
        self.callback(document_controller)


class PanelAction(Action):

    def __init__(self, ui, action_id, title, callback):
        Action.__init__(self, ui, action_id, title)
        self.callback = callback

    def create(self):
        if self._qt_action is None:
            self._qt_action = self.ui.Actions_createApplicationAction(self.qt_action_manager, self.action_id, self.title, False)

    def adjustApplicationAction(self):
        pass

    def adjustDocumentAction(self, document_controller):
        pass # self.ui.Actions_enableAction(qt_action_manager, self.action_id)

    def execute(self, document_controller):
        self.callback(document_controller.selected_image_panel)


class Menu(object):

    def __init__(self, ui, menu_id, title):
        self.ui = ui
        self.menu_id = menu_id
        self.title = title
        self.qt_action_manager = None
        self.__qt_menu = None
        self.action_ids = []
        self.__action_map = {}
        self.__build_items = []  # used to delay building menus

    def __create(self):
        if self.__qt_menu is None:
            self.__qt_menu = self.ui.Actions_findMenu(self.qt_action_manager, self.menu_id)
            if not self.__qt_menu:
                self.__qt_menu = self.ui.Actions_createMenu(self.qt_action_manager, self.menu_id, self.title)

    def get_qt_menu(self):
        self.__create()
        return self.__qt_menu
    qt_menu = property(get_qt_menu)

    def createActions(self):
        for build_item in self.__build_items:
            insert_before_action_id = build_item["insert"] if "insert" in build_item else None
            if "action" in build_item:
                action = build_item["action"]
                action.qt_action_manager = self.qt_action_manager
                qt_action = action.qt_action  # need to set action.qt_action_manager before this call
                self.ui.Actions_insertAction(self.qt_action_manager, self.qt_menu, qt_action, insert_before_action_id)
                action.configure()
            else:
                self.ui.Actions_insertSeparator(self.qt_action_manager, self.qt_menu, insert_before_action_id)

    def insertAction(self, action, before_action_id):
        action_id = action.action_id
        assert action_id not in self.action_ids
        self.action_ids.append(action_id)
        self.__build_items.append({ "action": action, "insert": before_action_id })
        self.__action_map[action_id] = action
        if self.__qt_menu:
            action.qt_action_manager = self.qt_action_manager
            qt_action = action.qt_action  # need to set action.qt_action_manager before this call
            self.ui.Actions_insertAction(self.qt_action_manager, self.qt_menu, qt_action, before_action_id)

    def insertSeparator(self, before_action_id):
        self.__build_items.append({ "separator": True, "insert": before_action_id })
        if self.__qt_menu:
            action.qt_action_manager = self.qt_action_manager
            self.ui.Actions_insertSeparator(self.qt_action_manager, self.qt_menu, before_action_id)

    def adjustApplicationActions(self):
        for action_id in self.action_ids:
            action = self.__action_map[action_id]
            action.adjustApplicationAction()

    def adjustDocumentActions(self, document_controller):
        for action_id in self.action_ids:
            action = self.__action_map[action_id]
            action.adjustDocumentAction(document_controller)

    def findAction(self, action_id):
        return self.__action_map[action_id] if action_id in self.__action_map else None


class MenuManager(object):

    def __init__(self, ui):
        self.ui = ui
        self.menu_ids = []  # ordering of menus
        self.__menu_dicts = {}  # map from id to menu dict
        self.qt_menu_bar = None
        self.qt_action_manager = None

        self.insertMenu("help", _("Help"), None)

        self.insertMenu("window", _("Window"), "help")

        self.insertMenu("file", _("File"), "window")

        self.insertMenu("edit", _("Edit"), "window")

        self.insertMenu("processing-menu", _("Processing"), "window")
        self.addDocumentAction("processing-menu", "processingFFT", _("FFT"), callback=lambda dc: dc.processing_fft(), key_sequence="Ctrl+F")
        self.addDocumentAction("processing-menu", "processingIFFT", _("Inverse FFT"), callback=lambda dc: dc.processing_ifft(), key_sequence="Ctrl+Shift+F")
        self.addDocumentAction("processing-menu", "processingGaussianBlur", _("Gaussian Blur"), callback=lambda dc: dc.processing_gaussian_blur())
        self.addDocumentAction("processing-menu", "processingResample", _("Resample"), callback=lambda dc: dc.processing_resample())
        self.addDocumentAction("processing-menu", "processingCrop", _("Crop"), callback=lambda dc: dc.processing_crop())
        self.addDocumentAction("processing-menu", "processingLineProfile", _("Line Profile"), callback=lambda dc: dc.processing_line_profile())
        self.addDocumentAction("processing-menu", "processingInvert", _("Invert"), callback=lambda dc: dc.processing_invert())
        self.addDocumentAction("processing-menu", "processingDuplicate", _("Duplicate"), callback=lambda dc: dc.processing_duplicate(), key_sequence="Ctrl+D")
        self.addDocumentAction("processing-menu", "processingSnapshot", _("Snapshot"), callback=lambda dc: dc.processing_snapshot(), key_sequence="Ctrl+Shift+S")
        self.addDocumentAction("processing-menu", "processingHistogram", _("Histogram"), callback=lambda dc: dc.processing_histogram())
        self.addDocumentAction("processing-menu", "processingRGBtoGrayscale", _("RGBtoGrayscale"), callback=lambda dc: dc.processing_RGBtoGrayscale())

        # put these in processing menu until it is possible to add them to the File menu
        self.insertDocumentAction("file", "file-add-smart-group", "print", _("Add Smart Group"), callback=lambda dc: dc.add_smart_group(), key_sequence="Ctrl+Alt+N")
        self.insertDocumentAction("file", "file-add-group", "print", _("Add Group"), callback=lambda dc: dc.add_group(), key_sequence="Ctrl+Shift+N")
        self.insertDocumentAction("file", "file-add-green", "print", _("Add Green"), callback=lambda dc: dc.add_green_data_item(), key_sequence="Ctrl+Shift+G")
        self.insertSeparator("file", "print")

        self.insertMenu("layout-menu", _("Layout"), "window")
        self.addDocumentAction("layout-menu", "layout1x1", _("Layout 1x1"), callback=lambda dc: dc.workspace.change_layout("1x1"), key_sequence="Ctrl+1")
        self.addDocumentAction("layout-menu", "layout2x1", _("Layout 2x1"), callback=lambda dc: dc.workspace.change_layout("2x1"), key_sequence="Ctrl+2")
        self.addDocumentAction("layout-menu", "layout3x1", _("Layout 3x1"), callback=lambda dc: dc.workspace.change_layout("3x1"), key_sequence="Ctrl+3")
        self.addDocumentAction("layout-menu", "layout2x2", _("Layout 2x2"), callback=lambda dc: dc.workspace.change_layout("2x2"), key_sequence="Ctrl+4")

        self.insertMenu("graphic-menu", _("Graphic"), "window")
        self.addDocumentAction("graphic-menu", "graphic-add-line", _("Add Line Graphic"), callback=lambda dc: dc.add_line_graphic())
        self.addDocumentAction("graphic-menu", "graphic-add-ellipse", _("Add Ellipse Graphic"), callback=lambda dc: dc.add_ellipse_graphic())
        self.addDocumentAction("graphic-menu", "graphic-add-rect", _("Add Rectangle Graphic"), callback=lambda dc: dc.add_rectangle_graphic())
        # TODO: allow action to change menu name based on plurality of selected objects
        self.addDocumentAction("graphic-menu", "graphic-remove", _("Remove Graphic"), callback=lambda dc: dc.remove_graphic())

        self.insertMenu("test-menu", _("Test"), "window")
        self.addApplicationAction("test-menu", "test-xxx", _("XXX"), callback=lambda: logging.debug("XXX"))
        self.addDocumentAction("test-menu", "test-log", _("Storage Log"), callback=lambda dc: dc.test_storage_log())
        self.addDocumentAction("test-menu", "test-read", _("Storage Read"), callback=lambda dc: dc.test_storage_read())
        self.addDocumentAction("test-menu", "test-write", _("Storage Write"), callback=lambda dc: dc.test_storage_write())
        self.addDocumentAction("test-menu", "test-reset", _("Storage Reset"), callback=lambda dc: dc.test_storage_reset())

    def createMenus(self, qt_menu_bar, qt_action_manager):
        self.qt_menu_bar = qt_menu_bar
        self.qt_action_manager = qt_action_manager
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            menu.qt_action_manager = self.qt_action_manager
            qt_menu = menu.qt_menu  # need to set menu.qt_action_manager before this call
            insert_before_id = menu_dict["insert"]
            self.ui.Actions_insertMenu(self.qt_action_manager, self.qt_menu_bar, qt_menu, insert_before_id)
            menu.createActions()

    # Menu will be inserted immediately if menu_bar is not None.
    # Otherwise, menu will be inserted when createMenus is called.
    def insertMenu(self, menu_id, title, before_menu_id, use_existing=True):
        assert use_existing or menu_id not in self.menu_ids
        if not use_existing or menu_id not in self.menu_ids:
            menu = Menu(self.ui, menu_id, title)
            self.menu_ids.append(menu_id)
            self.__menu_dicts[menu_id] = { "menu": menu, "insert": before_menu_id }
            if self.qt_menu_bar and self.qt_action_manager:
                menu.qt_action_manager = self.qt_action_manager
                qt_menu = menu.qt_menu  # need to set menu.qt_action_manager before this call
                self.ui.Actions_insertMenu(self.qt_action_manager, self.qt_menu_bar, qt_menu, before_menu_id)
                menu.createActions()

    def addMenu(self, menu_id, title):
        self.insertMenu(menu_id, title, None)

    def insertSeparator(self, menu_id, before_action_id):
        assert menu_id in self.__menu_dicts
        menu_dict = self.__menu_dicts[menu_id]
        menu = menu_dict["menu"]
        assert menu is not None
        menu.insertSeparator(before_action_id)

    def insertAction(self, menu_id, action, before_action_id):
        assert menu_id in self.__menu_dicts
        menu_dict = self.__menu_dicts[menu_id]
        menu = menu_dict["menu"]
        assert menu is not None
        menu.insertAction(action, before_action_id)

    def insertApplicationAction(self, menu_id, action_id, before_action_id, title, callback, key_sequence=None):
        action = self.findAction(action_id)
        assert action is None, "action already exists"
        action = ApplicationAction(self.ui, action_id, title, callback)
        action.key_sequence = key_sequence
        self.insertAction(menu_id, action, before_action_id)

    def insertDocumentAction(self, menu_id, action_id, before_action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert action is None, "action already exists"
        action = DocumentAction(self.ui, action_id, title, callback)
        action.key_sequence = key_sequence
        self.insertAction(menu_id, action, before_action_id)

    def addAction(self, menu_id, action):
        assert not self.findAction(action.action_id)
        self.insertAction(menu_id, action, None)

    def addApplicationAction(self, menu_id, action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert replace_existing or (action is None), "action already exists"
        if replace_existing and action:
            action.title = title
            action.callback = callback
        else:
            action = ApplicationAction(self.ui, action_id, title, callback)
            action.key_sequence = key_sequence
            self.addAction(menu_id, action)

    def addDocumentAction(self, menu_id, action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert replace_existing or (action is None), "action already exists"
        if replace_existing and action:
            action.title = title
            action.callback = callback
        else:
            action = DocumentAction(self.ui, action_id, title, callback)
            action.key_sequence = key_sequence
            self.addAction(menu_id, action)

    def addPanelAction(self, menu_id, action_id, title, callback, key_sequence=None, replace_existing=False):
        action = self.findAction(action_id)
        assert replace_existing or (action is None), "action already exists"
        if replace_existing and action:
            action.title = title
            action.callback = callback
        else:
            action = PanelAction(self.ui, action_id, title, callback)
            action.key_sequence = key_sequence
            self.addAction(menu_id, action)

    def adjustApplicationActions(self):
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            menu.adjustApplicationActions()

    def adjustDocumentActions(self, document_controller):
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            menu.adjustDocumentActions(document_controller)

    # search through each menu and look for a matching action
    def findAction(self, action_id):
        for menu_id in self.menu_ids:
            menu_dict = self.__menu_dicts[menu_id]
            menu = menu_dict["menu"]
            action = menu.findAction(action_id)
            if action:
                return action
        return None

    def dispatchApplicationAction(self, action_id):
        action = self.findAction(action_id)
        if action:
            action.execute()

    def dispatchDocumentAction(self, document_controller, action_id):
        action = self.findAction(action_id)
        if action:
            action.execute(document_controller)
