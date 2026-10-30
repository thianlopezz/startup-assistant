import json

import pytest

from startup_assistant.briefs import DEFAULT_CAMPAIGN, BriefStore
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


# --- phase 3: named campaigns ---------------------------------------------------------

def test_default_campaign(tmp_path):
    assert DEFAULT_CAMPAIGN == "Customer acquisition"
    store = BriefStore(tmp_path / "briefs.json")
    rec = store.save(make_draft(), "# one", "created", None, 0, "r")
    assert rec.campaign == DEFAULT_CAMPAIGN
    assert store.campaigns() == [DEFAULT_CAMPAIGN]


def test_campaigns_number_versions_separately(tmp_path):
    store = BriefStore(tmp_path / "briefs.json")
    a1 = store.save(make_draft("a1"), "# a1", "created", None, 0, "r")
    b1 = store.save(make_draft("b1"), "# b1", "created", None, 0, "r", campaign="Spring launch")
    a2 = store.save(make_draft("a2"), "# a2", "revised", 1, 0, "r")
    b2 = store.save(make_draft("b2"), "# b2", "revised", 1, 0, "r", campaign="spring LAUNCH ")
    assert [(r.campaign, r.version) for r in (a1, b1, a2, b2)] == [
        (DEFAULT_CAMPAIGN, 1), ("Spring launch", 1), (DEFAULT_CAMPAIGN, 2), ("Spring launch", 2),
    ]
    assert store.get(1).markdown == "# a1"
    assert store.get(1, "Spring launch").markdown == "# b1"
    assert store.get(2, "  spring launch").markdown == "# b2"
    assert store.get(3, "Spring launch") is None
    assert store.get(1, "Nope") is None
    assert store.latest(DEFAULT_CAMPAIGN).markdown == "# a2"
    assert store.latest("SPRING launch").markdown == "# b2"
    assert store.latest("Nope") is None
    assert [r.markdown for r in store.list("Spring launch")] == ["# b1", "# b2"]
    assert len(store.list()) == 4
    assert store.campaigns() == [DEFAULT_CAMPAIGN, "Spring launch"]


def test_latest_none_is_most_recent_overall(tmp_path):
    store = BriefStore(tmp_path / "briefs.json")
    store.save(make_draft(), "# a1", "created", None, 0, "r")
    store.save(make_draft(), "# a2", "revised", 1, 0, "r")
    store.save(make_draft(), "# b1", "created", None, 0, "r", campaign="Spring launch")
    assert store.latest().markdown == "# b1"
    assert store.latest(None).campaign == "Spring launch"


def test_old_json_without_campaign_loads_as_default(tmp_path):
    path = tmp_path / "briefs.json"
    BriefStore(path).save(make_draft(), "# one", "created", None, 0, "r")
    data = json.loads(path.read_text(encoding="utf-8"))
    for rec in data["records"]:
        del rec["campaign"]
    path.write_text(json.dumps(data), encoding="utf-8")
    store = BriefStore(path)
    assert store.latest().campaign == DEFAULT_CAMPAIGN
    assert store.get(1).markdown == "# one"
    assert store.campaigns() == [DEFAULT_CAMPAIGN]
    assert store.save(make_draft(), "# two", "revised", 1, 0, "r").version == 2


def test_revises_across_campaigns_rejected(tmp_path):
    store = BriefStore(tmp_path / "briefs.json")
    store.save(make_draft(), "# a1", "created", None, 0, "r")
    store.save(make_draft(), "# a2", "revised", 1, 0, "r")
    store.save(make_draft(), "# b1", "created", None, 0, "r", campaign="Spring launch")
    with pytest.raises(ValueError):
        store.save(make_draft(), "# b?", "revised", 2, 0, "r", campaign="Spring launch")
    assert len(store.list()) == 3


def test_blank_campaign_means_default(tmp_path):
    store = BriefStore(tmp_path / "briefs.json")
    assert store.save(make_draft(), "# a", "created", None, 0, "r", campaign="  ").campaign == (
        DEFAULT_CAMPAIGN
    )
