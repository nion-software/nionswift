from __future__ import annotations

# standard libraries
import gettext
import typing

# third party libraries
import numpy
import scipy.stats

# local libraries
from nion.data import Calibration
from nion.data import DataAndMetadata
from nion.swift.model import DataItem
from nion.ui import Declarative
from nion.utils import Converter
from nion.utils import Model

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController

_ = gettext.gettext


class GenerateDataDialog(Declarative.WindowHandler):

    def __init__(self, document_controller: DocumentController.DocumentController):
        super().__init__()

        self.__document_controller = document_controller

        self.title_model: Model.PropertyModel[str] = Model.PropertyModel(_("Generated Data"))
        self.data_type_model: Model.PropertyModel[int] = Model.PropertyModel(0)
        self.is_sequence_model: Model.PropertyModel[int] = Model.PropertyModel(0)
        self.collection_rank_model: Model.PropertyModel[int] = Model.PropertyModel(0)
        self.datum_rank_model: Model.PropertyModel[int] = Model.PropertyModel(1)

        self.sequence_size_model: Model.PropertyModel[int] = Model.PropertyModel(16)

        self.line_size_model: Model.PropertyModel[int] = Model.PropertyModel(512)

        self.scan_width_model: Model.PropertyModel[int] = Model.PropertyModel(256)
        self.scan_height_model: Model.PropertyModel[int] = Model.PropertyModel(256)

        self.spectrum_size_model: Model.PropertyModel[int] = Model.PropertyModel(1024)

        self.image_width_model: Model.PropertyModel[int] = Model.PropertyModel(1024)
        self.image_height_model: Model.PropertyModel[int] = Model.PropertyModel(1024)

        self.array_width_model: Model.PropertyModel[int] = Model.PropertyModel(1024)
        self.array_height_model: Model.PropertyModel[int] = Model.PropertyModel(256)

        self.int_converter = Converter.IntegerToStringConverter()

        u = Declarative.DeclarativeUI()

        title_row = u.create_row(u.create_label(text=_("Title")),
                                 u.create_line_edit(text="@binding(title_model.value)"), u.create_stretch(), spacing=8)

        data_type_row = u.create_row(u.create_label(text=_("Data Type")), u.create_combo_box(items=["Float (32-bit)"],
                                                                                             current_index="@binding(data_type_model.value)"),
                                     u.create_stretch(), spacing=8)

        is_sequence_row = u.create_row(u.create_label(text=_("Sequence")),
                                       u.create_combo_box(items=["No", "Yes"],
                                                          current_index="@binding(is_sequence_model.value)"),
                                       u.create_stretch(), spacing=8)

        not_sequence_column = u.create_column(u.create_row(u.create_label(text=_("No Sequence Axis"), enabled=False)))

        sequence_column = u.create_column(
            u.create_row(u.create_label(text=_("Sequence Length")),
                         u.create_line_edit(text="@binding(sequence_size_model.value, converter=int_converter)"),
                         u.create_stretch(), spacing=8),
        )

        is_sequence_stack = u.create_stack(not_sequence_column, sequence_column,
                                           current_index="@binding(is_sequence_model.value)")

        collection_rank_row = u.create_row(u.create_label(text=_("Collection Rank")),
                                           u.create_combo_box(items=["0 (none)", "1 (line)", "2 (scan)"],
                                                              current_index="@binding(collection_rank_model.value)"),
                                           u.create_stretch(), spacing=8)

        no_scan_column = u.create_column(u.create_row(u.create_label(text=_("No Collection Axes"), enabled=False)))

        line_column = u.create_column(
            u.create_row(u.create_label(text=_("Line Length")),
                         u.create_line_edit(text="@binding(line_size_model.value, converter=int_converter)"),
                         u.create_stretch(), spacing=8),
        )

        scan_column = u.create_column(
            u.create_row(u.create_label(text=_("Scan Width")),
                         u.create_line_edit(text="@binding(scan_width_model.value, converter=int_converter)"),
                         u.create_label(text=_("Scan Height")),
                         u.create_line_edit(text="@binding(scan_height_model.value, converter=int_converter)"),
                         u.create_stretch(), spacing=8),
        )

        collection_stack = u.create_stack(no_scan_column, line_column, scan_column,
                                          current_index="@binding(collection_rank_model.value)")

        datum_rank_row = u.create_row(u.create_label(text=_("Datum Rank")),
                                      u.create_combo_box(items=["1 (spectrum)", "2 (image)", "1+1 (array of 1d)"],
                                                         current_index="@binding(datum_rank_model.value)"),
                                      u.create_stretch(), spacing=8)

        spectrum_column = u.create_column(
            u.create_row(u.create_label(text=_("Length")),
                         u.create_line_edit(text="@binding(spectrum_size_model.value, converter=int_converter)"),
                         u.create_stretch(), spacing=8),
        )

        image_column = u.create_column(
            u.create_row(u.create_label(text=_("Width")),
                         u.create_line_edit(text="@binding(image_width_model.value, converter=int_converter)"),
                         u.create_label(text=_("Height")),
                         u.create_line_edit(text="@binding(image_height_model.value, converter=int_converter)"),
                         u.create_stretch(), spacing=8),
        )

        array_column = u.create_column(
            u.create_row(u.create_label(text=_("Width")),
                         u.create_line_edit(text="@binding(array_width_model.value, converter=int_converter)"),
                         u.create_label(text=_("Height")),
                         u.create_line_edit(text="@binding(array_height_model.value, converter=int_converter)"),
                         u.create_stretch(), spacing=8),
        )

        datum_stack = u.create_stack(spectrum_column, image_column, array_column,
                                     current_index="@binding(datum_rank_model.value)")

        button_row = u.create_row(u.create_stretch(),
                                  u.create_push_button(text=_("Cancel"), on_clicked="close_window"),
                                  u.create_push_button(text=_("Generate"), on_clicked="generate"), spacing=8)

        main_page = u.create_column(title_row, data_type_row,
                                    is_sequence_row, is_sequence_stack,
                                    collection_rank_row, collection_stack,
                                    datum_rank_row, datum_stack,
                                    u.create_spacing(26), button_row, min_width=320 - 24)

        window = u.create_window(main_page, title=_("Generate Data"), margin=12, window_style="tool")

        self.run(window, parent_window=document_controller, persistent_id="generate_data")
        self.__document_controller.register_dialog(self.window)

    def generate(self, widget: typing.Optional[Declarative.UIWidget] = None) -> None:
        data_shape: typing.Tuple[int, ...] = tuple()
        calibrations: typing.List[Calibration.Calibration] = list()
        is_sequence = False
        collection_rank = 0
        datum_rank = 1

        if self.is_sequence_model.value == 1:
            is_sequence = True
            sequence_size = self.sequence_size_model.value or 1
            data_shape = data_shape + (sequence_size,)
            calibrations.append(Calibration.Calibration(units="s"))

        if self.collection_rank_model.value == 1:
            collection_rank = 1
            line_size = self.line_size_model.value or 1
            data_shape = data_shape + (line_size,)
            calibrations.append(Calibration.Calibration(units="nm"))
        elif self.collection_rank_model.value == 2:
            collection_rank = 2
            scan_height = self.scan_height_model.value or 1
            scan_width = self.scan_width_model.value or 1
            data_shape = data_shape + (scan_height, scan_width)
            calibrations.append(Calibration.Calibration(units="nm"))
            calibrations.append(Calibration.Calibration(units="nm"))

        if self.datum_rank_model.value == 0:
            datum_rank = 1
            spectrum_size = self.spectrum_size_model.value or 1
            data_shape = data_shape + (spectrum_size,)
            calibrations.append(Calibration.Calibration(units="eV"))
        elif self.datum_rank_model.value == 1:
            datum_rank = 2
            image_height = self.image_height_model.value or 1
            image_width = self.image_width_model.value or 1
            data_shape = data_shape + (image_height, image_width)
            calibrations.append(Calibration.Calibration(units="nm"))
            calibrations.append(Calibration.Calibration(units="nm"))
        elif self.datum_rank_model.value == 2:
            collection_rank += 1
            datum_rank = 1
            array_height = self.array_height_model.value or 1
            array_width = self.array_width_model.value or 1
            data_shape = data_shape + (array_height, array_width)
            calibrations.append(Calibration.Calibration(units="nm"))
            calibrations.append(Calibration.Calibration(units="eV"))

        is_large = numpy.product(numpy.array(data_shape), dtype=numpy.int64).item() > 16 * 1024 * 1024

        document_model = self.__document_controller.document_model

        data_item = DataItem.DataItem(large_format=is_large)
        title_value = self.title_model.value
        if title_value:
            data_item.title = title_value
        document_model.append_data_item(data_item)

        data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_rank, datum_rank)

        data_item.reserve_data(data_shape=data_shape, data_dtype=numpy.dtype(numpy.float32), data_descriptor=data_descriptor)

        with data_item.data_ref() as dr:
            data = dr.data
            if data is not None:
                if datum_rank == 1:
                    n = scipy.stats.norm()
                    length = data.shape[-1]
                    data[..., :] = n.pdf(numpy.linspace(n.ppf(1.0 / length), n.ppf(1.0 - 1.0 / length), length))

                # noise
                rng = numpy.random.default_rng()
                data[...] += rng.standard_normal(data.shape)

            dr.data_updated()

        data_item.set_dimensional_calibrations(calibrations)

        display_item = document_model.get_display_item_for_data_item(data_item)
        assert display_item

        self.__document_controller.show_display_item(display_item)
