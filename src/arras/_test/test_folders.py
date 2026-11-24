"""Tests of arras.folders"""

import os
import doctest

import arras.folders
from arras.folders import PACKAGEDIR, userdir, workdir, glpath, search_path, findfile

def test_packagedir():
    assert os.path.isfile(os.path.join(PACKAGEDIR, "unitfile.txt"))
    assert os.path.isfile(os.path.join(PACKAGEDIR, "folders.py"))

def test_userdir_default(monkeypatch):
    monkeypatch.delenv("ARRAS_USERDIR", raising=False)
    monkeypatch.setenv("HOME", "/home/user")
    assert userdir() == "/home/user/.arras"
    assert userdir("share", "x.txt") == "/home/user/.arras/share/x.txt"

def test_userdir_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ARRAS_USERDIR", str(tmp_path / "user"))
    assert userdir("lib") == str(tmp_path / "user" / "lib")
    assert not (tmp_path / "user").exists()
    assert userdir("lib", create=True) == str(tmp_path / "user" / "lib")
    assert (tmp_path / "user" / "lib").is_dir()
    assert userdir("lib", create=True) == str(tmp_path / "user" / "lib")

def test_workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert workdir() == str(tmp_path)

def test_glpath(monkeypatch):
    monkeypatch.delenv("GLPATH", raising=False)
    assert glpath() == []
    monkeypatch.setenv("GLPATH", "")
    assert glpath() == []
    monkeypatch.setenv("GLPATH", f"/a;;/b{os.pathsep}/c;")
    assert glpath() == ["/a", "/b", "/c"]

def test_search_path(tmp_path, monkeypatch):
    monkeypatch.setenv("ARRAS_USERDIR", str(tmp_path / "user"))
    monkeypatch.delenv("GLPATH", raising=False)
    monkeypatch.chdir(tmp_path)
    assert search_path() == [str(tmp_path), str(tmp_path / "user" / "share"), PACKAGEDIR]
    monkeypatch.setenv("GLPATH", "/a;/b")
    assert search_path() == [str(tmp_path), str(tmp_path / "user" / "share"), "/a", "/b", PACKAGEDIR]
    assert search_path("/project")[0] == "/project"

def test_findfile(tmp_path, monkeypatch):
    monkeypatch.setenv("ARRAS_USERDIR", str(tmp_path / "user"))
    monkeypatch.setenv("GLPATH", str(tmp_path / "glpath"))
    work = tmp_path / "work"
    share = tmp_path / "user" / "share"
    work.mkdir()
    share.mkdir(parents=True)
    installed = os.path.join(PACKAGEDIR, "unitfile.txt")
    assert findfile("unitfile.txt", str(work)) == installed
    (share / "unitfile.txt").write_text("")
    assert findfile("unitfile.txt", str(work)) == str(share / "unitfile.txt")
    (work / "unitfile.txt").write_text("")
    assert findfile("unitfile.txt", str(work)) == str(work / "unitfile.txt")
    (tmp_path / "glpath").mkdir()
    (tmp_path / "glpath" / "glpath.txt").write_text("")
    assert findfile("glpath.txt", str(work)) == str(tmp_path / "glpath" / "glpath.txt")
    (tmp_path / "glpath" / "unitfile.txt").write_text("")
    os.remove(share / "unitfile.txt")
    os.remove(work / "unitfile.txt")
    assert findfile("unitfile.txt", str(work)) == str(tmp_path / "glpath" / "unitfile.txt")
    assert findfile(installed) == installed
    assert findfile(str(tmp_path / "missing.txt")) is None

def test_doctest():
    result = doctest.testmod(arras.folders)
    assert result.failed == 0 and result.attempted > 0
