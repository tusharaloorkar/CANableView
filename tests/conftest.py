import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
