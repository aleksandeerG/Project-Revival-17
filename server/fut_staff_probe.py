# Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
from __future__ import annotations


CONTROLS = (
    (35, 9, "kit"),
    (36, 10, "stadium"),
    (37, 30, "ball"),
    (39, 11, "badge"),
    (7, 201, "contract"),
    (43, 232, "misc/crowd"),
)

UNUSED_ASSET_IDS = (2, 4, 5, 6, 11, 12, 13, 14, 15, 16, 17, 18,
                    19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
                    30, 31, 33, 38, 41, 42, 46, 47, 48, 49)

SUBTYPE_CANDIDATES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 20, 40, 100, 200)

PLACEHOLDER_RATING = 50


def enabled() -> bool:
    return False


def _ratings(count: int) -> list:
    out, value = [], 1
    while len(out) < count and value < 100:
        if value != PLACEHOLDER_RATING:
            out.append(value)
        value += 1
    return out


def plan() -> list:
    rows = [("control", asset, subtype, note) for asset, subtype, note in CONTROLS]
    rows += [("assetid", asset, 0, f"cardassetid {asset}")
             for asset in UNUSED_ASSET_IDS]
    rows += [("subtype", 0, subtype, f"cardsubtypeid {subtype}")
             for subtype in SUBTYPE_CANDIDATES]
    ratings = _ratings(len(rows))
    return [{"probe": ratings[index], "band": band, "cardassetid": asset,
             "cardsubtypeid": subtype, "note": note}
            for index, (band, asset, subtype, note) in enumerate(rows)
            if index < len(ratings)]


def build_items(managers: list, timestamp: int = 0) -> list:
    import fut_cards

    probes = plan()
    if not managers:
        return []
    items = []
    for index, row in enumerate(probes):
        definition = dict(managers[index % len(managers)])
        definition["rating"] = row["probe"]
        definition["name"] = probe_label(row)
        item = fut_cards.build_card(definition, 990_000_000 + index, timestamp)
        item["cardassetid"] = row["cardassetid"]
        item["cardsubtypeid"] = row["cardsubtypeid"]
        items.append(item)
    return items


def probe_label(row: dict) -> str:
    return "P%02d %d/%d" % (row["probe"], row["cardassetid"],
                            row["cardsubtypeid"])


def describe() -> str:
    lines = ["staff-card probe: %d cards" % len(plan()),
             "  the card name is the label; the rating repeats it",
             "  a card drawn at rating 50 is a refused record, not a probe",
             ""]
    for row in plan():
        lines.append("  probe %-3d %-8s cardassetid=%-3d cardsubtypeid=%-4d %s"
                     % (row["probe"], row["band"], row["cardassetid"],
                        row["cardsubtypeid"], row["note"]))
    return "\n".join(lines)
