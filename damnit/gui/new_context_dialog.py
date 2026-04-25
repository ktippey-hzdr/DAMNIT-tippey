import re
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QFileDialog, QLabel, QListWidgetItem, QMessageBox

from ..site_config import find_proposal_dir, proposal_is_required
from .new_context_dialog_ui import Ui_Dialog

DAMNIT_PKG = Path(__file__).parent.parent

INST_TO_SASE = {
    'FXE': 'SA1', 'SPB': 'SA1',
    'HED': 'SA2', 'MID': 'SA2',
    'SCS': 'SA3',  'SQS': 'SA3', 'SXP': 'SA3',
}

ALL_GROUPS = set(INST_TO_SASE) | set(INST_TO_SASE.values())

TEMPLATE_DESCRIPTIONS = {
    "HZDR_labfrog": (
        "HZDR starter context for LabFrog/ShotSheet MongoDB metadata. "
        "Includes examples for counts, numeric shot series, JSON records, "
        "and planned HZDR ingest modes."
    ),
    "HZDR_preview_examples": (
        "HZDR examples for returning table thumbnails with full data or plots "
        "available when users double-click a DAMNIT table cell."
    ),
}

def find_instrument(path: Path) -> str:
    if path.is_relative_to('/gpfs/exfel/exp'):
        return path.parts[4]  # Part after exp/
    elif path.is_relative_to('/gpfs/exfel/u'):
        return path.parts[5]  # Part after usr/ or scratch/
    return ''


class NewContextFileDialog(QDialog):
    def __init__(self, target_path, parent=None):
        super().__init__(parent)
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        self._proposal_required = proposal_is_required(target_path)
        self._template_hint = self._make_template_hint()
        self._configure_for_site_profile()

        group = find_instrument(target_path)
        if group in ALL_GROUPS:
            self.match_groups = {group, None}
            if group in INST_TO_SASE:
                self.match_groups.add(INST_TO_SASE[group])
        else:
            self.match_groups = ALL_GROUPS | {None}

        self.all_templates = []

        group_re = re.compile(r'([a-zA-Z0-9]+)[ -_]')
        for path in sorted((DAMNIT_PKG / 'ctx-templates').iterdir()):
            if (m := group_re.match(path.name)) and m[1] in ALL_GROUPS:
                group = m[1]
            else:
                group = None
            self.all_templates.append((group, path))

        self.populate_template_list()

        self.ui.template_other_inst_cb.toggled.connect(self.populate_template_list)
        self.ui.template_list.currentItemChanged.connect(self._update_template_hint)
        self.ui.browse_button.clicked.connect(self.browse)

    def _make_template_hint(self) -> QLabel:
        """Add compact guidance for the currently selected template."""
        label = QLabel(self)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.ui.verticalLayout_2.addWidget(label)
        return label

    def _configure_for_site_profile(self):
        """Hide proposal-only choices when the active site does not use proposals."""
        if self._proposal_required:
            return

        self.ui.label.setText("Create a new HZDR DAMNIT context file...")
        self.ui.proposal_rb.hide()
        self.ui.proposal_edit.hide()
        self.ui.user_vars_cb.hide()
        self.ui.template_other_inst_cb.setText("Show templates for other sites")

    def populate_template_list(self, all_insts=False):
        """Populate the template list, keeping HZDR templates visible everywhere."""
        self.ui.template_list.clear()

        for group, path in self.all_templates:
            if (not all_insts) and (group not in self.match_groups):
                continue

            item = QListWidgetItem(path.stem, parent=self.ui.template_list)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            if path.stem.startswith("HZDR_"):
                item.setToolTip(TEMPLATE_DESCRIPTIONS.get(path.stem, "HZDR context template"))

        if self.ui.template_list.count() > 0:
            self.ui.template_list.setCurrentRow(0)
        self._update_template_hint()

    def _update_template_hint(self, current=None, previous=None):
        """Show short template guidance without forcing users to inspect files."""
        item = current or self.ui.template_list.currentItem()
        if item is None:
            self._template_hint.clear()
            return

        template_path = Path(item.data(Qt.ItemDataRole.UserRole))
        description = TEMPLATE_DESCRIPTIONS.get(
            template_path.stem,
            "Use this as a starting context.py file and edit it for your data.",
        )
        self._template_hint.setText(description)

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Python file", filter="Python files (*.py);;Any (*)"
        )
        if path:
            self.ui.file_edit.setText(path)

    def run_get_result(self) -> (Optional[Path], Optional[Path]):
        if self.exec() == QDialog.Rejected:
            return None, None

        if self.ui.template_rb.isChecked():
            item = self.ui.template_list.currentItem()
            return Path(item.data(Qt.ItemDataRole.UserRole)), None

        elif self.ui.proposal_rb.isChecked():
            propnum = self.ui.proposal_edit.text()
            try:
                prop_dir = find_proposal_dir(int(propnum))
            except Exception:
                QMessageBox.critical(self, "Proposal not found",
                                     f"Could not find proposal {propnum}")
                return self.run_get_result()
            path = Path(prop_dir) / 'usr/Shared/amore/context.py'
            if not path.is_file():
                QMessageBox.critical(self, "No context file",
                                     f"Proposal {propnum} didn't contain a context file")
                return self.run_get_result()
            copy_user_vars = self.ui.user_vars_cb.isChecked()
            return path, (path.parent / "runs.sqlite" if copy_user_vars else None)

        else:  # file_rb
            return Path(self.ui.file_edit.text()), None
