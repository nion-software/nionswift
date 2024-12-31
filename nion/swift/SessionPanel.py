from __future__ import annotations

# standard libraries
import gettext
import typing

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import ApplicationData
from nion.ui import Declarative

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import Persistence
    from nion.utils import StructuredModel

_ = gettext.gettext


class SessionHandler(Declarative.Handler):
    def __init__(self, model: StructuredModel.RecordModel) -> None:
        super().__init__()
        self.session_model = model
        self.ui_view = self.__make_ui()

    def __make_ui(self) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()

        # ordered from most likely to change to least
        field_descriptions = [
            [_("Sample Area"), _("Sample Area Description"), "sample_area"],
            [_("Sample"), _("Sample Description"), "sample"],
            [_("Task"), _("Task Description"), "task"],
            [_("Microscopist"), _("Microscopist Name(s)"), "microscopist"],
            [_("Instrument"), _("Instrument Description"), "instrument"],
            [_("Site"), _("Site Description"), "site"],
        ]

        field_rows: typing.List[Declarative.UIDescription] = list()

        for field_description in field_descriptions:
            label, tool_tip, key = field_description
            field_line_edit = u.create_line_edit(text=f"@binding(session_model.{key}_model.value)", tool_tip=tool_tip, placeholder_text=tool_tip)
            field_rows.append(u.create_row(u.create_label(text=label, width=120, tool_tip=tool_tip), field_line_edit, spacing=4, margin_horizontal=8, margin_vertical=2))

        return u.create_column(u.create_spacing(4), *field_rows, u.create_row(u.create_stretch(), u.create_label(text=_("Session metadata added to acquired data."), font="italic"), u.create_stretch()), u.create_stretch(), spacing=4)


class SessionPanel(Panel.Panel):

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Session"))

        ui_handler = SessionHandler(ApplicationData.get_session_metadata_model())
        self.widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, ui_handler)
