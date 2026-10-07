"""Catalog families, Ready/Use rewrite, slot and stack fields."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rtkitems


def _row(name, **fields):
    lines = [rtkitems._fmt("Item_Name", name, 0)]
    for key, val in fields.items():
        if key == "effects":
            continue
        lines.append(rtkitems._fmt(key, val, 0))
    for effect in fields.get("effects") or []:
        lines.extend(rtkitems._named_effect_block(effect["name"], effect))
    lines.append("End_Item")
    return "\n".join(lines)


CATALOG = "\n".join((
    _row("Gold", Category="Gem", SubCategory="Money", UniqueID="0",
         Location_Active="Pack", Aggregate="True", Price="1",
         Encumbrance="0.05", AS_Tag="Gold", UA_Tag="Gold"),
    _row("Ruby", Category="Gem", SubCategory="Single_Use", UniqueID="10",
         Location_Active="Pack", Price="20", AS_Tag="Ruby"),
    _row("RingOfStrength", Category="Ring", SubCategory="UseByAll",
         UniqueID="50", Location_Active="Ring", Quality_Original="Magical",
         AS_Tag="Ring of Strength", effects=[{
             "name": "Ready",
             "desc": "Strength",
             "modifiers": [{"name": "Attribute_Strength", "modify": "Ratio",
                            "value": "125"}],
         }]),
    _row("Firestaff", Category="Weapon", SubCategory="Quarterstaff",
         UniqueID="80", Location_Active="Hand", Weapon_Damage="Rand(2-6)",
         AS_Tag="Firestaff", effects=[
             {"name": "Use", "desc": "Flame", "spell": "Fire_FireRain",
              "magic": "CastOnUse", "cast_limit": "Limited", "cast_max": "3",
              "noncombat": "0", "modifiers": []},
             {"name": "Ready", "desc": "Heat",
              "modifiers": [{"name": "Damage_FireNormal", "modify": "Ratio",
                             "value": "125"}]},
         ]),
    _row("HealingPotion", Category="Potion", SubCategory="Potion",
         UniqueID="152", Location_Active="Pack", AS_Tag="Healing Potion",
         effects=[{
             "name": "Use", "desc": "Heal", "spell": "Heal_Light",
             "magic": "CastOnUse", "cast_limit": "Limited", "cast_max": "1",
             "noncombat": "1", "modifiers": [],
         }]),
    _row("Lockpicks", Category="Picks", SubCategory="Single_Use",
         UniqueID="223", Location_Active="Pack", AS_Tag="Lockpicks"),
    _row("Crucible", Category="Alchemy", SubCategory="Equipment",
         UniqueID="200", Location_Active="Pack", AS_Tag="Crucible"),
    _row("Fennel", Category="Alchemy", SubCategory="Ingredient",
         UniqueID="133", Location_Active="Pack", Aggregate="True",
         AS_Tag="Fennel"),
    _row("WoodShield", Category="Armor", SubCategory="Shield",
         UniqueID="12", Location_Active="Hand", AS_Tag="Wooden Shield"),
))


def catalog():
    return rtkitems.ItemCatalog.load(CATALOG.encode("latin-1"))


def test_kinds():
    cat = catalog()
    got = {it["Item_Name"]: cat.kind_of(it) for it in cat.items}
    assert got == {
        "Gold": "money",
        "Ruby": "gem",
        "RingOfStrength": "ring",
        "Firestaff": "weapon",
        "HealingPotion": "potion",
        "Lockpicks": "picks",
        "Crucible": "tool",
        "Fennel": "reagent",
        "WoodShield": "shield",
    }
    groups = {k["id"]: k["count"] for g in cat.kind_groups() for k in g["kinds"]}
    assert groups["money"] == 1
    assert groups["ring"] == 1
    assert groups["tool"] == 1
    assert groups["reagent"] == 1
    assert groups["picks"] == 1


def test_ring_ready():
    cat = catalog()
    cat.apply("RingOfStrength", ready_effect={
        "desc": "Agility",
        "modifiers": [{"name": "Attribute_Agility", "modify": "Ratio",
                       "value": "130"}],
    })
    rec = cat.detail("RingOfStrength")
    assert rec["kind"] == "ring"
    assert rec["edit_ready"]
    assert rec["ready"]["modifiers"][0]["name"] == "Attribute_Agility"
    assert rec["active"] == "Ring"


def test_potion_use():
    cat = catalog()
    cat.apply("HealingPotion", use_effect={
        "desc": "Heal more",
        "spell": "Heal_Serious",
        "magic": "CastOnUse",
        "cast_max": "1",
        "cast_limit": "Limited",
        "noncombat": "1",
        "modifiers": [],
    })
    rec = cat.detail("HealingPotion")
    assert rec["edit_use"]
    assert rec["use"]["spell"] == "Heal_Serious"
    assert rec["use"]["noncombat"] == "1"
    assert rec["ready"] is None


def test_gold_stack_no_effects():
    cat = catalog()
    cat.apply("Gold", fields={"Price": "2", "Aggregate": "True",
                              "Location_Active": "Pack"})
    rec = cat.detail("Gold")
    assert rec["kind"] == "money"
    assert rec["aggregate"]
    assert rec["preview_3d"] is False
    assert rec["edit_ready"] is False
    assert rec["edit_use"] is False
    assert rec["unique_id"] == "0"
    assert rec["price"] == "2"
    assert "Effect" not in "\n".join(cat.by_name["Gold"]["lines"])


def test_firestaff_keeps_use_when_ready_changes():
    cat = catalog()
    cat.apply("Firestaff", ready_effect={
        "desc": "Hotter",
        "modifiers": [{"name": "Damage_FireSpell", "modify": "Ratio",
                       "value": "150"}],
    })
    rec = cat.detail("Firestaff")
    assert rec["use"]["spell"] == "Fire_FireRain"
    assert rec["ready"]["modifiers"][0]["name"] == "Damage_FireSpell"


def test_preview_holdables():
    cat = catalog()
    wand = _row("WandOfTest", Category="Wand", SubCategory="UseByMage",
                UniqueID="261", Location_Active="Hand", AS_Tag="Test Wand")
    extra = rtkitems.ItemCatalog.load((CATALOG + "\n" + wand).encode("latin-1"))
    w = extra.preview_of(extra.by_name["WandOfTest"])
    assert w["gear"] == "wand" and w["hold"]
    p = extra.preview_of(extra.by_name["HealingPotion"])
    assert p["gear"] == "objpotion"
    r = extra.preview_of(extra.by_name["RingOfStrength"])
    assert r.get("paper_doll")
    a = extra.detail("HealingPotion")
    assert extra.kind_of(extra.by_name["HealingPotion"]) == "potion"


def test_icon_cells():
    assert rtkitems.paper_doll_cell(0) == 0
    assert rtkitems.paper_doll_cell(76) == 0
    assert rtkitems.paper_doll_cell(124) == 0
    assert rtkitems.paper_doll_cell(151) == 0
    assert rtkitems.paper_doll_cell(192) == 0
    assert rtkitems.paper_doll_cell(204) == 12
    assert rtkitems.paper_doll_cell(205) == 0
    assert rtkitems.paper_doll_cell(215) == 10
    assert rtkitems.bag_cell(152) == 152
    assert rtkitems.bag_cell(152, assessed=False) == 0x10b
    assert rtkitems.bag_cell(0) == 0


def test_clear_use_leaves_ready():
    cat = catalog()
    cat.apply("Firestaff", use_effect={"spell": "", "modifiers": []})
    rec = cat.detail("Firestaff")
    assert rec["use"] is None
    assert rec["ready"]["modifiers"][0]["name"] == "Damage_FireNormal"


if __name__ == "__main__":
    test_kinds()
    test_ring_ready()
    test_potion_use()
    test_gold_stack_no_effects()
    test_firestaff_keeps_use_when_ready_changes()
    test_clear_use_leaves_ready()
    test_icon_cells()
    test_preview_holdables()
    print("ok")
