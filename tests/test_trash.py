"""trash.py için birim testleri — gerçek Çöp Kutusu'na dokunulmaz (mock'lanır)."""

from pathlib import Path

from maclean import trash


def test_all_paths_succeed(monkeypatch):
    moved: list[str] = []
    monkeypatch.setattr(trash, "send2trash", lambda p: moved.append(p))

    paths = [Path("/tmp/a"), Path("/tmp/b")]
    succeeded, failed = trash.move_to_trash(paths)

    assert succeeded == paths
    assert failed == []
    assert moved == ["/tmp/a", "/tmp/b"]


def test_one_failure_does_not_stop_others(monkeypatch):
    def fake_send2trash(p: str):
        if p == "/tmp/bad":
            raise OSError("izin reddedildi")

    monkeypatch.setattr(trash, "send2trash", fake_send2trash)

    paths = [Path("/tmp/good1"), Path("/tmp/bad"), Path("/tmp/good2")]
    succeeded, failed = trash.move_to_trash(paths)

    assert succeeded == [Path("/tmp/good1"), Path("/tmp/good2")]
    assert len(failed) == 1
    assert failed[0][0] == Path("/tmp/bad")
    assert "izin reddedildi" in failed[0][1]


def test_empty_input():
    succeeded, failed = trash.move_to_trash([])
    assert succeeded == []
    assert failed == []
