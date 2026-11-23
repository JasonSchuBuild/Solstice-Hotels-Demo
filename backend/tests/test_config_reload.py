"""Config files are re-read when they change, so live edits apply without a restart."""
import os

from solstice.config import load_yaml


def test_yaml_is_reread_after_edit(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("cap_pct: 15\n", encoding="utf-8")
    assert load_yaml(p)["cap_pct"] == 15
    p.write_text("cap_pct: 12\n", encoding="utf-8")
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 5))      # make sure the timestamp moves
    assert load_yaml(p)["cap_pct"] == 12


def test_unchanged_file_is_served_from_cache(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("a: 1\n", encoding="utf-8")
    assert load_yaml(p) is load_yaml(p)
