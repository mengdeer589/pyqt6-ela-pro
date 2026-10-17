"""``ElaUploadArea`` 测试：初值 / 属性往返 / 文件校验 / 拖放 / 鼠标 / 主题。"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QEnterEvent, QMouseEvent
from PyQt6.QtWidgets import QFileDialog
from PyQt6ElaWidgetTools import ElaThemeType

from pyqt6_ela_pro.ela_upload_area import ElaUploadArea


@pytest.fixture
def area(make):
    return make(ElaUploadArea)


# (setter, getter, 非默认值) —— 十二组形状完全一样，逐个写测试纯属复制粘贴
_ROUNDTRIP = [
    (ElaUploadArea.setTitle, ElaUploadArea.title, "上传文件"),
    (ElaUploadArea.setTitle, ElaUploadArea.title, ""),
    (ElaUploadArea.setSubTitle, ElaUploadArea.subTitle, "点击上传"),
    (ElaUploadArea.setBorderRadius, ElaUploadArea.borderRadius, 16),
    (
        ElaUploadArea.setAcceptedSuffixes,
        ElaUploadArea.acceptedSuffixes,
        [".txt", ".py"],
    ),
    (ElaUploadArea.setMaxFileCount, ElaUploadArea.maxFileCount, 5),
    (ElaUploadArea.setMaxFileSize, ElaUploadArea.maxFileSize, 1024),
    (ElaUploadArea.setMultiple, ElaUploadArea.isMultiple, False),
    (ElaUploadArea.setDialogTitle, ElaUploadArea.dialogTitle, "选择文件"),
    (
        ElaUploadArea.setAcceptedMimeFilter,
        ElaUploadArea.acceptedMimeFilter,
        "Text (*.txt)",
    ),
]

# getter -> 默认值
_DEFAULTS = [
    (ElaUploadArea.title, "拖拽文件到此处"),
    (ElaUploadArea.subTitle, "或点击选择文件"),
    (ElaUploadArea.borderRadius, 8),
    (ElaUploadArea.acceptedSuffixes, []),
    (ElaUploadArea.maxFileCount, 0),
    (ElaUploadArea.maxFileSize, 0),
    (ElaUploadArea.isMultiple, True),
    (ElaUploadArea.dialogTitle, ""),
    (ElaUploadArea.acceptedMimeFilter, ""),
    (ElaUploadArea.selectedFiles, []),
]


class TestElaUploadAreaInit:
    @pytest.mark.parametrize(
        ("attr", "expected"),
        [
            ("_title", "拖拽文件到此处"),
            ("_sub_title", "或点击选择文件"),
            ("_border_radius", 8),
            ("_accepted_suffixes", []),
            ("_max_file_count", 0),
            ("_max_file_size", 0),
            ("_is_multiple", True),
            ("_is_drag_over", False),
            ("_is_hover", False),
            ("_is_pressed", False),
            ("_file_paths", []),
        ],
    )
    def test_initialization_with_defaults(self, area, attr, expected):
        assert getattr(area, attr) == expected

    def test_minimum_size(self, area):
        assert area.minimumWidth() == 260
        assert area.minimumHeight() == 160

    def test_accepts_drops(self, area):
        assert area.acceptDrops() is True

    def test_mouse_tracking_enabled(self, area):
        assert area.hasMouseTracking() is True

    def test_hand_cursor(self, area):
        assert area.cursor().shape() == Qt.CursorShape.PointingHandCursor


class TestElaUploadAreaSignals:
    @pytest.mark.parametrize(
        "name", ["filesSelected", "fileAdded", "fileRemoved", "fileRejected"]
    )
    def test_declares_signal(self, area, name):
        assert hasattr(area, name)


class TestElaUploadAreaProps:
    @pytest.mark.parametrize(
        ("getter", "expected"), _DEFAULTS, ids=lambda v: str(v)[:20]
    )
    def test_getter_default(self, area, getter, expected):
        assert getter(area) == expected

    @pytest.mark.parametrize(
        ("setter", "getter", "value"), _ROUNDTRIP, ids=range(len(_ROUNDTRIP))
    )
    def test_setter_roundtrip(self, area, setter, getter, value):
        setter(area, value)
        assert getter(area) == value

    def test_clear_files(self, area):
        area._file_paths = ["a.txt", "b.py"]
        area.clearFiles()
        assert area.selectedFiles() == []


class TestElaUploadAreaValidateFile:
    def test_validate_file_nonexistent(self, area):
        ok, reason = area._validateFile("Z:\\nonexistent_file.xyz")
        assert ok is False
        assert reason == "文件不存在"

    def test_validate_file_suffix_rejected(self, area):
        area.setAcceptedSuffixes([".txt"])
        ok, reason = area._validateFile("C:\\Windows\\System32\\drivers\\etc\\hosts")
        assert ok is False
        assert "不支持的文件类型" in reason

    def test_validate_file_duplicate(self, area):
        area._file_paths = ["C:\\test.txt"]
        ok, reason = area._validateFile("C:\\test.txt")
        assert ok is False
        assert len(reason) > 0


class TestElaUploadAreaAddFiles:
    @pytest.mark.parametrize(
        ("validate", "path", "signal"),
        [
            ((True, ""), "C:\\test.txt", "fileAdded"),
            ((False, "不支持"), "C:\\bad.exe", "fileRejected"),
        ],
        ids=["accepted", "rejected"],
    )
    def test_add_files_emits_per_file_signal(self, area, validate, path, signal):
        area._validateFile = lambda p: validate
        received = []
        getattr(area, signal).connect(
            (lambda p: received.append(p))
            if signal == "fileAdded"
            else (lambda p, r: received.append((p, r)))
        )
        area._addFiles([path])
        assert received

    def test_add_files_emits_files_selected(self, area):
        area._validateFile = lambda p: (True, "")
        received = []
        area.filesSelected.connect(received.append)
        area._addFiles(["C:\\test.txt"])
        assert any("C:\\test.txt" in files for files in received)


class TestElaUploadAreaRemoveFile:
    def test_remove_file_emits_file_removed(self, area):
        area._file_paths = ["a.txt", "b.py"]
        received = []
        area.fileRemoved.connect(received.append)
        area._removeFile(0)
        assert "a.txt" in received

    def test_remove_file_updates_list(self, area):
        area._file_paths = ["a.txt", "b.py"]
        area._removeFile(0)
        assert area._file_paths == ["b.py"]

    def test_remove_invalid_index(self, area):
        area._file_paths = ["a.txt"]
        area._removeFile(5)
        assert area._file_paths == ["a.txt"]


class TestElaUploadAreaEvents:
    def test_drag_enter_sets_drag_over(self, area):
        mime = QMimeData()
        mime.setUrls([])
        area.dragEnterEvent(
            QDragEnterEvent(
                area.rect().topLeft(),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
        )
        assert area._is_drag_over is True

    def test_drag_leave_clears_drag_over(self, area):
        area._is_drag_over = True
        area.dragLeaveEvent(QDragLeaveEvent())
        assert area._is_drag_over is False

    def test_enter_event_sets_hover(self, area):
        pos = QPointF(1, 1)
        area.enterEvent(QEnterEvent(QPointF(pos), QPointF(pos), QPointF(pos)))
        assert area._is_hover is True

    def test_leave_event_clears_hover(self, area):
        area._is_hover = True
        area.leaveEvent(QEvent(QEvent.Type.Leave))
        assert area._is_hover is False


class TestElaUploadAreaTheme:
    def test_on_theme_changed_updates_mode(self, area):
        area._onThemeChanged(ElaThemeType.ThemeMode.Dark)
        assert area._theme_mode == ElaThemeType.ThemeMode.Dark


class TestElaUploadAreaDeleteLater:
    def test_delete_later_cleans_up(self, area):
        area.deleteLater()


class TestElaUploadAreaSuffixNormalization:
    """文档里后缀写法带点（``[".txt"]``），而 ``QFileInfo.suffix()`` 返回值不带点。"""

    def test_normalized_suffixes_strips_dots_and_lowercases(self, area):
        area.setAcceptedSuffixes([".TXT", "py", ".Md"])
        assert area._normalized_suffixes() == ["txt", "py", "md"]

    def test_accepted_suffixes_getter_round_trips(self, area):
        area.setAcceptedSuffixes([".txt", ".py"])
        assert area.acceptedSuffixes() == [".txt", ".py"]

    def test_real_dotted_file_is_accepted(self, area, tmp_path):
        target = tmp_path / "sample.txt"
        target.write_text("hi", encoding="utf-8")
        area.setAcceptedSuffixes([".txt"])
        ok, reason = area._validateFile(str(target))
        assert ok is True, reason

    def test_real_other_file_is_rejected(self, area, tmp_path):
        target = tmp_path / "sample.exe"
        target.write_text("x", encoding="utf-8")
        area.setAcceptedSuffixes([".txt"])
        ok, reason = area._validateFile(str(target))
        assert ok is False
        assert "exe" in reason

    def test_directory_is_rejected(self, area, tmp_path):
        ok, reason = area._validateFile(str(tmp_path))
        assert ok is False
        assert "目录" in reason

    @pytest.mark.parametrize("multiple", [True, False], ids=["multi", "single"])
    def test_dialog_filter_has_single_dot(self, area, monkeypatch, multiple):
        area.setAcceptedSuffixes([".txt", ".py"])
        area.setMultiple(multiple)
        captured = {}

        def fake_names(parent, title, dir_, filter_):
            captured["filter"] = filter_
            return [], ""

        def fake_name(parent, title, dir_, filter_):
            captured["filter"] = filter_
            return "", ""

        # 真实模态文件框会把 pytest 卡死，两个入口都得替换
        monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(fake_names))
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake_name))

        area._openFileDialog()

        assert "*.txt" in captured["filter"]
        assert "*..txt" not in captured["filter"]


class TestElaUploadAreaMouseButtons:
    """右键 / 中键不得触发模态文件框（此前 press/release 都没有 button 检查）。"""

    @staticmethod
    def _click(area, qapp, button):
        pos = QPoint(50, 50)
        glob = area.mapToGlobal(pos)
        for event_type, buttons in (
            (QEvent.Type.MouseButtonPress, button),
            (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        ):
            qapp.sendEvent(
                area,
                QMouseEvent(
                    event_type,
                    QPointF(pos),
                    QPointF(glob),
                    button,
                    buttons,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )

    @pytest.fixture
    def shown_area(self, make, qapp):
        area = make(ElaUploadArea)
        area.resize(300, 200)
        area.show()
        qapp.processEvents()
        yield area
        area.close()

    @pytest.mark.parametrize(
        "button",
        [Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton],
        ids=["right", "middle"],
    )
    def test_non_left_click_does_not_open_dialog(
        self, shown_area, qapp, monkeypatch, button
    ):
        calls = []
        monkeypatch.setattr(shown_area, "_openFileDialog", lambda: calls.append(1))
        self._click(shown_area, qapp, button)
        assert calls == []
        assert shown_area._is_pressed is False

    def test_left_click_still_opens_dialog(self, shown_area, qapp, monkeypatch):
        calls = []
        monkeypatch.setattr(shown_area, "_openFileDialog", lambda: calls.append(1))
        self._click(shown_area, qapp, Qt.MouseButton.LeftButton)
        assert calls == [1]
