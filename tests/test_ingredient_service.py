import pytest

from services import ingredient_service as s


@pytest.fixture()
def idx(ingredients):
    return s.build_index(ingredients)


def _one(text, idx):
    return s.match_items(s.split_ingredient_list(text), idx)


def test_exact_canonical_match(idx, ingredients):
    r = s.match_text("Aspartame", idx)
    assert r.match_type == "canonical" and not r.needs_confirmation
    assert next(i for i in ingredients if i.id == r.ingredient_id).canonical_name == "Aspartame"


def test_case_insensitive(idx):
    assert s.match_text("ASPARTAME", idx).ingredient_id == s.match_text("aspartame", idx).ingredient_id


def test_synonym_match(idx):
    r = s.match_text("Soya Lecithin", idx)
    assert r.match_type == "synonym" and r.ingredient_id is not None


@pytest.mark.parametrize("text", ["E102", "e 102", "INS 102", "Colour (E102)"])
def test_identifier_match(idx, text):
    ms = [m for m in _one(text, idx) if m.ingredient_id]
    assert len(ms) == 1 and ms[0].match_type in {"identifier", "canonical", "synonym"}


def test_unknown_ingredient(idx):
    r = s.match_text("Dragonfruit extract", idx)
    assert r.match_type == "none" and r.ingredient_id is None


def test_typo_is_flagged_not_auto_accepted(idx):
    r = s.match_text("Aspartme", idx)
    assert r.match_type == "fuzzy" and r.needs_confirmation


def test_similar_but_different_additive_is_not_silently_matched(idx):
    # nitrate vs nitrite: must never be an unflagged match
    r = s.match_text("Sodium nitrate", idx)
    assert r.match_type in {"none", "fuzzy"}
    if r.match_type == "fuzzy":
        assert r.needs_confirmation


def test_parenthetical_sub_ingredient(idx):
    ms = _one("Preservative (Sodium Benzoate)", idx)
    assert [m.match_type for m in ms] == ["canonical"]


def test_declared_percent_parsed(idx):
    items = s.split_ingredient_list("Sugar (45%), Water")
    assert items[0].declared_percent == 45.0 and items[0].name == "Sugar"


def test_list_splitting_ignores_commas_in_parentheses():
    items = s.split_ingredient_list("Ingredients: Flour, Emulsifier (Soy Lecithin, E471), Salt.")
    assert [i.name for i in items] == ["Flour", "Emulsifier", "Salt"]
    assert items[1].inner == ["Soy Lecithin", "E471"]


def test_duplicates_removed(idx):
    ms = [m for m in _one("Aspartame, aspartame, E951", idx) if m.ingredient_id]
    assert len(ms) == 1


def test_normalize_name():
    assert s.normalize_name("FD&C Yellow No. 5") == "fd and c yellow no 5"
    assert s.normalize_name("  Café  ") == "cafe"
