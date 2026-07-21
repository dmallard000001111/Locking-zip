from pathlib import Path

from locking_zip import gui_logic


class _FakeTclSplitlist:
    """Mimics tk.splitlist's handling of Tcl brace-quoted list syntax, since we
    can't rely on a real Tk instance in headless CI."""

    def __call__(self, raw: str):
        result = []
        i = 0
        n = len(raw)
        while i < n:
            while i < n and raw[i] == " ":
                i += 1
            if i >= n:
                break
            if raw[i] == "{":
                end = raw.index("}", i)
                result.append(raw[i + 1:end])
                i = end + 1
            else:
                end = raw.find(" ", i)
                if end == -1:
                    end = n
                result.append(raw[i:end])
                i = end
        return result


def test_parse_dropped_paths_simple():
    splitlist = _FakeTclSplitlist()
    paths = gui_logic.parse_dropped_paths("/tmp/a.txt", splitlist)
    assert paths == ["/tmp/a.txt"]


def test_parse_dropped_paths_braced_with_spaces():
    splitlist = _FakeTclSplitlist()
    raw = "{/Users/me/My Folder} /Users/me/file.txt"
    paths = gui_logic.parse_dropped_paths(raw, splitlist)
    assert paths == ["/Users/me/My Folder", "/Users/me/file.txt"]


def test_passwords_match():
    assert gui_logic.passwords_match("hunter2", "hunter2") is True
    assert gui_logic.passwords_match("hunter2", "hunter3") is False
    assert gui_logic.passwords_match("", "") is False


def test_suggest_dest_name():
    assert gui_logic.suggest_dest_name(Path("/tmp/myfolder")) == "myfolder.zip"
    assert gui_logic.suggest_dest_name(Path("/tmp/report.docx")) == "report.zip"


def test_suggest_extract_dir():
    assert gui_logic.suggest_extract_dir(Path("/tmp/archive.zip")) == Path("/tmp/archive")


def test_validate_source_missing(tmp_path):
    missing = tmp_path / "nope"
    error = gui_logic.validate_source(missing)
    assert error is not None
    assert "no longer exists" in error


def test_validate_source_none():
    error = gui_logic.validate_source(None)
    assert error == "No file or folder selected."


def test_validate_source_ok(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hi")
    assert gui_logic.validate_source(f) is None


def test_estimate_strength_boundaries():
    assert gui_logic.estimate_strength("") == ""
    assert gui_logic.estimate_strength("abc") == "Weak"
    assert gui_logic.estimate_strength("abcdefgh") == "Weak"
    assert gui_logic.estimate_strength("abcdefgh1") == "Medium"
    assert gui_logic.estimate_strength("Abcdefgh12!!") == "Strong"
