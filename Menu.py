# standard libraries
import gettext

# third party libraries
# None

# local libraries
# None

_ = gettext.gettext


def build_menus(menu_manager):
    menu_manager.insert_menu("help", _("Help"), None)

    menu_manager.insert_menu("window", _("Window"), "help")

    menu_manager.insert_menu("file", _("File"), "window")

    menu_manager.insert_menu("edit", _("Edit"), "window")

    menu_manager.insert_menu("processing-menu", _("Processing"), "window")
    menu_manager.add_document_action("processing-menu", "processingFFT", _("FFT"), callback=lambda dc: dc.processing_fft(), key_sequence="Ctrl+F")
    menu_manager.add_document_action("processing-menu", "processingIFFT", _("Inverse FFT"), callback=lambda dc: dc.processing_ifft(), key_sequence="Ctrl+Shift+F")
    menu_manager.add_document_action("processing-menu", "processingGaussianBlur", _("Gaussian Blur"), callback=lambda dc: dc.processing_gaussian_blur())
    menu_manager.add_document_action("processing-menu", "processingResample", _("Resample"), callback=lambda dc: dc.processing_resample())
    menu_manager.add_document_action("processing-menu", "processingCrop", _("Crop"), callback=lambda dc: dc.processing_crop())
    menu_manager.add_document_action("processing-menu", "processingLineProfile", _("Line Profile"), callback=lambda dc: dc.processing_line_profile())
    menu_manager.add_document_action("processing-menu", "processingInvert", _("Invert"), callback=lambda dc: dc.processing_invert())
    menu_manager.add_document_action("processing-menu", "processingDuplicate", _("Duplicate"), callback=lambda dc: dc.processing_duplicate(), key_sequence="Ctrl+D")
    menu_manager.add_document_action("processing-menu", "processingSnapshot", _("Snapshot"), callback=lambda dc: dc.processing_snapshot(), key_sequence="Ctrl+Shift+S")
    menu_manager.add_document_action("processing-menu", "processingHistogram", _("Histogram"), callback=lambda dc: dc.processing_histogram())
    menu_manager.add_document_action("processing-menu", "processingConvertToScalar", _("Convert to Scalar"), callback=lambda dc: dc.processing_convert_to_scalar())

    # put these in processing menu until it is possible to add them to the File menu
    menu_manager.insert_document_action("file", "file-add-smart-group", "print", _("Add Smart Group"), callback=lambda dc: dc.add_smart_group(), key_sequence="Ctrl+Alt+N")
    menu_manager.insert_document_action("file", "file-add-group", "print", _("Add Group"), callback=lambda dc: dc.add_group(), key_sequence="Ctrl+Shift+N")
    menu_manager.insert_document_action("file", "file-add-green", "print", _("Add Green"), callback=lambda dc: dc.add_green_data_item(), key_sequence="Ctrl+Shift+G")
    menu_manager.insert_separator("file", "print")

    menu_manager.insert_menu("layout-menu", _("Layout"), "window")
    menu_manager.add_document_action("layout-menu", "layout1x1", _("Layout 1x1"), callback=lambda dc: dc.workspace.change_layout("1x1"), key_sequence="Ctrl+1")
    menu_manager.add_document_action("layout-menu", "layout2x1", _("Layout 2x1"), callback=lambda dc: dc.workspace.change_layout("2x1"), key_sequence="Ctrl+2")
    menu_manager.add_document_action("layout-menu", "layout3x1", _("Layout 3x1"), callback=lambda dc: dc.workspace.change_layout("3x1"), key_sequence="Ctrl+3")
    menu_manager.add_document_action("layout-menu", "layout2x2", _("Layout 2x2"), callback=lambda dc: dc.workspace.change_layout("2x2"), key_sequence="Ctrl+4")

    menu_manager.insert_menu("graphic-menu", _("Graphic"), "window")
    menu_manager.add_document_action("graphic-menu", "graphic-add-line", _("Add Line Graphic"), callback=lambda dc: dc.add_line_graphic())
    menu_manager.add_document_action("graphic-menu", "graphic-add-ellipse", _("Add Ellipse Graphic"), callback=lambda dc: dc.add_ellipse_graphic())
    menu_manager.add_document_action("graphic-menu", "graphic-add-rect", _("Add Rectangle Graphic"), callback=lambda dc: dc.add_rectangle_graphic())
    # TODO: allow action to change menu name based on plurality of selected objects
    menu_manager.add_document_action("graphic-menu", "graphic-remove", _("Remove Graphic"), callback=lambda dc: dc.remove_graphic())
