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
    assert "- primary_buyer: Head of Customer Success [updated in v1]" in out
    assert "founder or operations lead" not in out


PRICING_LINE = (
    "Pricing restricted: leave prices and any mention of pricing out of all campaign materials."
)


def test_update_without_pricing_leaves_it_unrestricted(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.json")
    store.apply_update(
        "t", "s", {"primary_buyer": "Head of Customer Success"}, ["Keep the tone friendly."]
    )
    assert not store.pricing_restricted


def test_render_has_pricing_line_only_when_restricted(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.json")
    assert PRICING_LINE not in store.render()
    store.apply_update("t", "s", {"primary_buyer": "Head of Customer Success"}, [])
    assert PRICING_LINE not in store.render()
    store.apply_update("t", "s", CHANGES, [])
    assert PRICING_LINE in store.render()


def test_render_has_pricing_line_when_restricted_by_rule(tmp_path):
    store = KnowledgeStore(tmp_path / "knowledge.json")
    store.apply_update("t", "s", {}, ["Do not mention pricing."])
    assert PRICING_LINE in store.render()
