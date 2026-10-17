"""Tests for _internal helpers: catch_error, safe_call, init_painter, disconnect_theme_signal."""

from __future__ import annotations


from pyqt6_ela_pro._internal import catch_error, safe_call, disconnect_theme_signal


class TestCatchError:
    """Test cases for @catch_error decorator."""

    def test_normal_function_returns_value(self):
        """Test that normal functions work correctly."""

        @catch_error
        def add(a, b):
            return a + b

        result = add(1, 2)
        assert result == 3

    def test_function_with_exception_returns_none(self, capsys):
        """Test that functions raising exceptions return None."""

        @catch_error
        def raise_error():
            raise ValueError("test error")

        result = raise_error()
        assert result is None

        captured = capsys.readouterr()
        assert "ValueError" in captured.err
        assert "raise_error" in captured.err

    def test_function_with_args_and_kwargs(self, capsys):
        """Test decorated function with various arguments."""

        @catch_error
        def func_with_args(a, b, c=None, d=None):
            if a == "error":
                raise RuntimeError("triggered")
            return f"{a}-{b}-{c}-{d}"

        assert func_with_args("x", "y", c="z") == "x-y-z-None"
        assert func_with_args("error", "y") is None

    def test_catch_error_preserves_function_metadata(self):
        """Test that decorator preserves function name and docstring."""

        @catch_error
        def my_function():
            """My docstring."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."


class TestSafeCall:
    """Test cases for safe_call function."""

    def test_safe_call_with_normal_function(self):
        """Test safe_call with a normal function."""

        def add(a, b):
            return a + b

        result = safe_call(add, 2, 3)
        assert result == 5

    def test_safe_call_with_none(self):
        """Test safe_call with None function."""
        result = safe_call(None)
        assert result is None

    def test_safe_call_with_none_args(self):
        """Test safe_call with None function and additional args."""
        result = safe_call(None, 1, 2, key="value")
        assert result is None

    def test_safe_call_with_function_raising_exception(self, capsys):
        """Test safe_call handles exceptions from the function."""

        def raise_error():
            raise RuntimeError("test")

        result = safe_call(raise_error)
        assert result is None

        captured = capsys.readouterr()
        assert "RuntimeError" in captured.err

    def test_safe_call_with_kwargs(self):
        """Test safe_call passes kwargs correctly."""

        def greet(name, prefix="Hello"):
            return f"{prefix}, {name}!"

        result = safe_call(greet, "World", prefix="Hi")
        assert result == "Hi, World!"

    def test_safe_call_with_non_callable(self):
        """Test safe_call with non-callable (not None)."""
        result = safe_call("not a function")
        assert result is None


class TestDisconnectThemeSignal:
    """Test cases for disconnect_theme_signal helper."""

    def test_disconnect_theme_signal_does_not_raise(self):
        """Test disconnect_theme_signal does not raise on never-connected slot."""

        def dummy():
            pass

        disconnect_theme_signal(dummy)

    def test_disconnect_theme_signal_accepts_none_slot(self):
        """Test disconnect_theme_signal handles non-callable gracefully."""
        disconnect_theme_signal(None)
