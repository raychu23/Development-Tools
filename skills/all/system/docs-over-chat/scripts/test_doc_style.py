import pathlib
import tempfile
import pytest
import doc_style as d


def page(body):
    t = pathlib.Path(tempfile.mkdtemp()) / "doc.html"
    t.write_text("<!doctype html><html><head></head><body><main>" + body + "</main></html>")
    return t


def test_core_block_limit_is_seven_lines():
    assert d.core(["core   a"] * 7).startswith('<pre class="core">')
    with pytest.raises(AssertionError):
        d.core(["x"] * 8)


def test_fold_list_chunks_by_seven():
    assert d.fold_list(["<p>x</p>"] * 7, "r") == "<p>x</p>" * 7
    out = d.fold_list(["<p>x</p>"] * 15, "r")
    assert out.count('class="fold chunk"') == 3 and "r 1-7" in out and "r 8-14" in out and "r 15-15" in out


def test_apply_injects_script_once_and_only_for_fold_pages():
    new = page(d.fold("s", "b"))
    assert d.apply(new) and not d.apply(new)
    assert new.read_text().count("<script data-doc-fold>") == 1
    old = page("<table><tr><td>x</td></tr></table>")
    d.apply(old)
    assert "data-doc-fold" not in old.read_text()          # old pages stay untouched except for the shared style


def test_audit_counts_core_folds_and_longest_table():
    p = page(d.core(["core   x"]) + d.fold("s", "b") + "<table>" + "<tr><td>1</td></tr>" * 9 + "</table>")
    a = d.audit(p)
    assert a["core"] and a["folds"] == 1 and a["max_table_rows"] == 8
