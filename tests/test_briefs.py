from startup_assistant.briefs import BriefStore
from startup_assistant.contracts import BriefDraft, Channel


def make_draft(title="Brief") -> BriefDraft:
    return BriefDraft(
        title=title, audience="a", buyer="b", main_message="m",
        channels=[Channel(name="LinkedIn", reason="r"), Channel(name="Email", reason="r")],
        email_subject="s", email_body="body", assumptions=["x"], open_questions=["y"],
    )


def test_empty_store(tmp_path):
    store = BriefStore(tmp_path / "briefs.json")
    assert store.latest() is None
    assert store.list() == []


def test_versions_increment_and_latest(tmp_path):
    store = BriefStore(tmp_path / "briefs.json")
    first = store.save(make_draft(), "# one", "created", None, 0, "make a brief")
    second = store.save(make_draft("v2"), "# two", "revised", 1, 0, "tweak it")
    assert (first.version, second.version) == (1, 2)
    assert store.latest().version == 2
    assert store.get(1).kind == "created"
    assert store.get(2).revises == 1
    assert store.get(3) is None
    assert [r.version for r in store.list()] == [1, 2]


def test_persists_markdown_exactly(tmp_path):
    path = tmp_path / "briefs.json"
    md = "# Café — brief ✓\n\nline “quoted”\n"
    BriefStore(path).save(make_draft(), md, "created", None, 2, "req")
    rec = BriefStore(path).latest()
    assert rec.markdown == md
    assert rec.knowledge_version == 2
    assert rec.request == "req"
