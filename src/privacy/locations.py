"""Offline evidence-based locality hierarchy and distinct-patient support."""
import re
from collections import defaultdict

# Deliberately small, unambiguous district-to-state vocabulary. No PIN-to-
# village inference: PIN evidence is learned only from supplied addresses.
DISTRICT_STATES = {
    "lucknow": "Uttar Pradesh", "sitapur": "Uttar Pradesh",
    "gonda": "Uttar Pradesh", "bahraich": "Uttar Pradesh",
    "jaipur": "Rajasthan", "pune": "Maharashtra", "patna": "Bihar",
}


def hierarchy_outputs(entries, k):
    """Return output per field and an alias map learned from explicit labels."""
    parents = defaultdict(set)
    labels = {}
    leaves = {}
    patients = defaultdict(set)
    for ref, path, patient, raw, candidate in entries:
        if re.search(r"(?i)platform|railway|found near|canal", raw):
            leaves[(ref, path)] = None
            continue
        parts = re.findall(
            r"(?i)\b(vill(?:age)?\.?|post|ps|distt?\.?|district|state)\s*[:=-]?\s*([^,;\n]+)", raw
        )
        chain = []
        for kind, value in parts:
            value = re.sub(r"\b\d{6}\b", "", value).strip()
            if value:
                chain.append(value)
        if not chain:
            chain = [candidate]
        district = next((v.strip() for t, v in parts if t.lower().rstrip('.') in {'dist', 'distt', 'district'}), None)
        if district and district.casefold() in DISTRICT_STATES:
            chain.append(DISTRICT_STATES[district.casefold()])
        pin = re.search(r"(?<!\d)([1-8]\d{2})\d{3}(?!\d)", raw)
        if pin:
            chain.append(pin.group(1) + "XXX region")
        keys = [v.casefold() for v in chain]
        for key, label in zip(keys, chain):
            labels.setdefault(key, label)
        for child, parent in zip(keys, keys[1:]):
            if child != parent:
                parents[child].add(parent)
        leaves[(ref, path)] = (keys[0], patient)

    def ancestors(leaf):
        result, todo = [], [leaf]
        while todo:
            node = todo.pop(0)
            if node in result:
                continue
            result.append(node)
            # Contradictory parent evidence must not pick an arbitrary region.
            if len(parents[node]) == 1:
                todo.extend(sorted(parents[node]))
        return result

    for item in leaves.values():
        if item:
            leaf, patient = item
            for node in ancestors(leaf):
                patients[node].add(patient)
    choices = {}
    for leaf in {item[0] for item in leaves.values() if item}:
        choices[leaf] = next((labels[n] for n in ancestors(leaf) if len(patients[n]) >= k), '[ADDRESS]')
    outputs = {key: choices[item[0]] if item else '[ADDRESS]' for key, item in leaves.items()}
    return outputs, {labels[leaf]: output for leaf, output in choices.items()}
