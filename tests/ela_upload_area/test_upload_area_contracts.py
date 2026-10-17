"""``ElaUploadArea`` 的出参不可变性。

``acceptedSuffixes()`` 原先直接返回内部 list —— 同一个类里两行之后的
``selectedFiles()`` 却返回 ``list(...)`` 副本，约定自相矛盾。后果是宿主
``area.acceptedSuffixes().append("exe")`` 就绕过了 ``setAcceptedSuffixes``，
而 ``_validateFile`` 直接读 ``_normalized_suffixes()`` —— 等于给了一条
「不改任何状态就能放宽校验」的后门。
"""

from __future__ import annotations

import pytest

from pyqt6_ela_pro.ela_upload_area import ElaUploadArea


@pytest.fixture
def area(make):
    widget = make(ElaUploadArea)
    widget.setAcceptedSuffixes([".txt", ".py"])
    return widget


class TestAcceptedSuffixesReturnsACopy:
    def test_values_are_visible(self, area):
        assert area.acceptedSuffixes() == [".txt", ".py"]

    def test_append_does_not_change_validation(self, area):
        before = list(area.acceptedSuffixes())
        area.acceptedSuffixes().append(".exe")
        assert area.acceptedSuffixes() == before

    def test_mutating_the_returned_list_is_a_no_op(self, area):
        got = area.acceptedSuffixes()
        got[0] = "被改了"
        got.clear()
        assert area.acceptedSuffixes() == [".txt", ".py"]

    def test_each_call_returns_a_fresh_object(self, area):
        first = area.acceptedSuffixes()
        second = area.acceptedSuffixes()
        assert first is not second
        first.append("x")
        assert second == [".txt", ".py"]

    def test_normalized_suffixes_still_comes_from_the_setter(self, area):
        """放后缀后校验走的是 setter 归一化后的集合，不是被外部改过的。"""
        area.acceptedSuffixes().append(".exe")
        assert area._normalized_suffixes() == ["txt", "py"]

    def test_setter_still_replaces_wholesale(self, area):
        area.setAcceptedSuffixes([".md"])
        assert area.acceptedSuffixes() == [".md"]


class TestSelectedFilesReturnsACopy:
    def test_empty(self, area):
        assert area.selectedFiles() == []

    def test_list_is_copied(self, area):
        got = area.selectedFiles()
        got.append("x")
        assert area.selectedFiles() == []

    def test_each_call_returns_a_fresh_object(self, area):
        assert area.selectedFiles() is not area.selectedFiles()


class TestOtherListOutputsAreCopies:
    """同类组件的其它 list 出参也逐个过一遍（回归时的清单）。"""

    @pytest.mark.parametrize(
        "getter,setter,value",
        [
            ("acceptedSuffixes", "setAcceptedSuffixes", [".a", ".b"]),
        ],
        ids=["accepted_suffixes"],
    )
    def test_output_is_not_the_stored_object(
        self, make, getter, setter, value
    ):
        widget = make(ElaUploadArea)
        getattr(widget, setter)(value)
        got = getattr(widget, getter)()
        got.append("tampered")
        assert getattr(widget, getter)() == value
