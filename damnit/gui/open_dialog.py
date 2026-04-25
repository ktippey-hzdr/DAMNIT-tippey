from pathlib import Path
from socket import gethostname
from typing import Optional, Tuple

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QFileDialog

from ..site_config import (
    find_proposal_dir,
    find_site_config_path,
    load_site_config,
    proposal_is_required,
)
from .open_dialog_ui import Ui_Dialog


def find_proposal(propnum: int) -> Path:
    return find_proposal_dir(propnum)


def resolve_site_config_base_dir() -> Path:
    cwd = Path.cwd()
    if find_site_config_path(cwd) is not None:
        return cwd

    home = Path.home()
    if find_site_config_path(home) is not None:
        return home

    return cwd


class ProposalFinder(QObject):
    find_result = pyqtSignal(str, str)

    def find_proposal(self, propnum: str):
        proposal_dir = ''
        if propnum.isdecimal() and len(propnum) >= 4:
            try:
                proposal_dir = str(find_proposal(int(propnum)))
            except Exception:
                proposal_dir = ''
        self.find_result.emit(propnum, proposal_dir)


class OpenDBDialog(QDialog):
    proposal_num_changed = pyqtSignal(str)
    proposal_dir = ''

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        self._site_config_base_dir = resolve_site_config_base_dir()
        self._proposal_required = proposal_is_required(self._site_config_base_dir)
        self._configure_for_site_profile()
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.ui.proposal_rb.toggled.connect(self.update_ok)
        self.ui.folder_edit.textChanged.connect(self.update_ok)
        self.ui.browse_button.clicked.connect(self.browse_for_folder)
        if self.ui.proposal_rb.isChecked():
            self.ui.proposal_edit.setFocus()
        else:
            self.ui.folder_edit.setFocus()

        self.proposal_finder_thread = QThread(parent=parent)
        self.proposal_finder = ProposalFinder()
        self.proposal_finder.moveToThread(self.proposal_finder_thread)
        self.ui.proposal_edit.textChanged.connect(self.proposal_finder.find_proposal)
        self.proposal_finder.find_result.connect(self.proposal_dir_result)
        self.finished.connect(self.proposal_finder_thread.quit)
        self.proposal_finder_thread.finished.connect(self.proposal_finder_thread.deleteLater)

    def _configure_for_site_profile(self):
        """Adapt the startup choices to proposal or folder-based deployments."""
        if self._proposal_required:
            return

        lab_name = str(
            load_site_config(self._site_config_base_dir).get("lab", {}).get("name", "")
        ).strip()
        self.ui.proposal_rb.setChecked(False)
        self.ui.folder_rb.setChecked(True)
        self.ui.proposal_rb.hide()
        self.ui.proposal_edit.hide()
        if lab_name:
            self.ui.label.setText(f"Select an existing {lab_name} DAMNIT folder:")
            self.ui.folder_rb.setText(f"{lab_name} DAMNIT folder:")

    def run_get_result(self) -> Tuple[Optional[Path], Optional[int]]:
        self.proposal_finder_thread.start()
        if self.exec() == QDialog.Rejected:
            return None, None
        context_dir = self.get_chosen_dir()
        prop_no = self.get_proposal_num()

        # use separated directory if running online to avoid file corruption
        # during sync between clusters.
        if (
                gethostname().startswith('exflonc')
                and not context_dir.stem.endswith('-online')
        ):
            context_dir = context_dir.absolute().parent / f'{context_dir.stem}-online'

        return context_dir, prop_no

    def proposal_dir_result(self, propnum: str, proposal_dir: str):
        if propnum != self.ui.proposal_edit.text():
            return  # Text field has been changed
        self.proposal_dir = proposal_dir
        self.update_ok()

    def update_ok(self):
        if self.ui.proposal_rb.isChecked():
            valid = bool(self.proposal_dir)
        else:
            valid = Path(self.ui.folder_edit.text()).is_dir()
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def browse_for_folder(self):
        path = QFileDialog.getExistingDirectory()
        if path:
            self.ui.folder_edit.setText(path)

    def get_chosen_dir(self):
        if self.ui.proposal_rb.isChecked():
            return Path(self.proposal_dir) / "usr/Shared/amore"
        else:
            return Path(self.ui.folder_edit.text())

    def get_proposal_num(self) -> Optional[int]:
        if self.ui.proposal_rb.isChecked():
            return int(self.ui.proposal_edit.text())
        return None
