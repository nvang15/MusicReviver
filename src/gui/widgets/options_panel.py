"""Task-aware backend option controls."""

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel

from src.gui.models import GuiTask
from src.mastering.models import MasteringMode
from src.restoration.models import RestorationStrength
from src.separation.backends import DeviceMode
from src.separation.models import DEFAULT_MODEL_ID, MODEL_REGISTRY, get_model


class OptionsPanel(QGroupBox):
    def __init__(self) -> None:
        super().__init__("Options")
        self.model_combo, self.device_combo = QComboBox(), QComboBox()
        self.restoration_combo, self.mastering_combo = QComboBox(), QComboBox()
        for identifier, model in MODEL_REGISTRY.items():
            self.model_combo.addItem(model.display_name, identifier)
        self.model_combo.setCurrentIndex(self.model_combo.findData(DEFAULT_MODEL_ID))
        for mode in DeviceMode:
            self.device_combo.addItem(mode.value.title(), mode)
        for strength in RestorationStrength:
            self.restoration_combo.addItem(strength.value.title(), strength)
        for mode in MasteringMode:
            descriptions = {
                MasteringMode.ARCHIVAL: "Minimal intervention and maximum preservation.",
                MasteringMode.BALANCED: "Gentle restoration and polish while preserving original character.",
                MasteringMode.MODERN: "A contemporary presentation with bounded processing.",
            }
            self.mastering_combo.addItem(mode.value.title(), mode)
            self.mastering_combo.setItemData(self.mastering_combo.count() - 1, descriptions[mode], 3)
        self.restoration_combo.setCurrentIndex(self.restoration_combo.findData(RestorationStrength.BALANCED))
        self.mastering_combo.setCurrentIndex(self.mastering_combo.findData(MasteringMode.BALANCED))
        self.model_label, self.device_label = QLabel("Separation model:"), QLabel("Device:")
        self.restoration_label, self.mastering_label = QLabel("Restoration:"), QLabel("Mastering:")
        layout = QFormLayout(self)
        for label, widget in ((self.model_label, self.model_combo), (self.device_label, self.device_combo),
                              (self.restoration_label, self.restoration_combo), (self.mastering_label, self.mastering_combo)):
            layout.addRow(label, widget)
        self.model_combo.currentIndexChanged.connect(self._update_devices)
        self._update_devices()
        self.set_task(GuiTask.MODERNIZE)

    def _update_devices(self) -> None:
        supported = get_model(self.model_combo.currentData()).supported_devices
        index = self.device_combo.findData(DeviceMode.DIRECTML)
        item = self.device_combo.model().item(index)
        if item:
            item.setEnabled(DeviceMode.DIRECTML.value in supported)
        if self.device_combo.currentData() == DeviceMode.DIRECTML.value and DeviceMode.DIRECTML.value not in supported:
            self.device_combo.setCurrentIndex(self.device_combo.findData(DeviceMode.AUTO))

    def set_task(self, task: GuiTask) -> None:
        separation = task in {GuiTask.SEPARATE, GuiTask.MODERNIZE}
        restoration = task in {GuiTask.RESTORE, GuiTask.MODERNIZE}
        mastering = task is GuiTask.MODERNIZE
        for widget in (self.model_label, self.model_combo, self.device_label, self.device_combo):
            widget.setVisible(separation)
        for widget in (self.restoration_label, self.restoration_combo):
            widget.setVisible(restoration)
        for widget in (self.mastering_label, self.mastering_combo):
            widget.setVisible(mastering)
