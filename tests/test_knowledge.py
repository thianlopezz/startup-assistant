from startup_assistant.knowledge import KnowledgeStore
from startup_assistant.seed import SEED_MARKETING_NOTES, SEED_PROFILE

CHANGES = {
    "target_customers": "B2B software companies with 100–500 employees",
    "primary_buyer": "Head of Customer Success",
    "pricing": "Under review — leave out of campaign materials (previously $299/month)",
}


def test_fresh_store_is_seed(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.json")
    assert store.version == 0
    assert store.current_profile() == SEED_PROFILE
    assert store.rules() == SEED_MARKETING_NOTES
    assert not store.pricing_restricted


def test_apply_update_changes_fields_and_persists(tmp_path):
    path = tmp_path / "knowledge.json"
    store = KnowledgeStore(path)
    update = store.apply_update("raw text", "summary", CHANGES, ["Do not mention pricing."])
    assert update.version == 1
    fresh = KnowledgeStore(path)
    assert fresh.version == 1
    assert fresh.current_profile()["primary_buyer"] == "Head of Customer Success"
    assert fresh.pricing_restricted
    assert fresh.rules()[-1] == "Do not mention pricing."
    assert fresh.updates() == [update]


def test_unknown_field_is_kept(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.json")
    store.apply_update("t", "s", {"integrations": "Slack planned"}, [])
    assert store.current_profile()["integrations"] == "Slack planned"


def test_render_marks_updated_fields(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.json")
    store.apply_update("t", "s", CHANGES, [])
    out = store.render()
    assert "Head of Customer Success" in out
    assert "v1" in out
    assert "founder or operations lead" not in out
