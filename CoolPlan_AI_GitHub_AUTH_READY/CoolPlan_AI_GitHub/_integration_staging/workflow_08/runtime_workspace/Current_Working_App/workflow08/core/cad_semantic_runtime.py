
from pathlib import Path
import csv, json, re, hashlib
import ezdxf
from groq import Groq

DEFAULT_MODEL = "qwen/qwen3.8-27b"
MAX_API_CALLS = 3
BATCH_SIZE = 3


def relevant_catalogue(label_payload, catalogue, limit=8):
    """Select catalogue entries with text overlap; do not send the full catalogue."""
    import re

    stop_words = {
        "the", "and", "for", "with", "from", "area", "site",
        "existing", "proposed", "future", "plan", "wide",
    }

    def tokens(value):
        words = re.findall(r"[a-z0-9]+", str(value).casefold())
        return {w for w in words if len(w) > 2 and w not in stop_words}

    label_words = set()
    for item in label_payload:
        label_words |= tokens(item.get("label", ""))
        label_words |= tokens(item.get("layer", ""))

    scored = []
    for row in catalogue:
        searchable = " ".join([
            row.get("feature_group", ""),
            row.get("standard_feature", ""),
            row.get("common_cad_labels", ""),
            row.get("environmental_relevance", ""),
        ])
        overlap = len(label_words & tokens(searchable))
        if overlap:
            scored.append((overlap, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def read_csv(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _entity_text_position(entity):
    try:
        point = entity.dxf.insert
        return float(point.x), float(point.y)
    except Exception:
        return None, None


def extract_dxf_text(dxf_path):
    """Extract text and coordinates; retain repeated labels at different positions."""
    doc = ezdxf.readfile(str(dxf_path))
    found = []

    for entity in doc.modelspace():
        kind = entity.dxftype()
        if kind in {"TEXT", "MTEXT", "ATTRIB"}:
            raw = entity.dxf.text if kind in {"TEXT", "ATTRIB"} else entity.text
            text = clean(raw)
            if text:
                x, y = _entity_text_position(entity)
                found.append({
                    "label": text, "layer": clean(entity.dxf.layer),
                    "entity_type": kind, "x": x, "y": y,
                })
        elif kind == "INSERT":
            try:
                for attrib in entity.attribs:
                    text = clean(attrib.dxf.text)
                    if text:
                        x, y = _entity_text_position(attrib)
                        found.append({
                            "label": text, "layer": clean(attrib.dxf.layer),
                            "entity_type": "ATTRIB", "x": x, "y": y,
                        })
            except Exception:
                pass

    unique = {}
    for item in found:
        key = (
            item["label"].casefold(), item["layer"].casefold(),
            item["entity_type"],
            None if item["x"] is None else round(item["x"], 6),
            None if item["y"] is None else round(item["y"], 6),
        )
        unique.setdefault(key, item)
    return list(unique.values())


def is_non_feature_label(value):
    """Exclude obvious CAD coordinates, levels, and drawing references."""
    label = str(value or "").strip().upper()
    # Remove common AutoCAD underline/overline formatting codes.
    label = re.sub(r"%%[UO]", "", label)
    compact = re.sub(r"\s+", " ", label).strip()

    if not compact:
        return True

    # Coordinate labels, including O used in place of zero.
    if re.fullmatch(
        r"[NE]\s*[-:]\s*[0-9O]+(?:\.[0-9O]+)?",
        compact
    ):
        return True

    # Numeric-only labels and isolated letters.
    if not re.search(r"[A-Z]", compact):
        return True

    # Common drawing directions and reference text.
    excluded = {
        "MASTER PLAN",
        "TO LAHORE",
        "TO NAROWAL",
        "EXISTING",
        "FUTURE",
        "SPACE FOR",
        "OVER HEAD/",
        "FOOTPATH LEV.",
        "PAVEMENT LEV.",
        "ROAD LEV.",
    }

    if compact.strip(" ()") in excluded:
        return True

    # Elevation/level annotations, without excluding named site features.
    if (
        re.search(r"\d", compact)
        and re.search(
            r"(?:%%P|[+()]|['\"]|\\bLEVEL\\b|\\bLEV\\.)",
            compact
        )
        and not re.search(
            r"\b(?:PARKING|BUILDING|ROAD|FOOTPATH|TANK)\b",
            compact
        )
    ):
        return True

    # Generic AutoCAD formatting fragments.
    if compact in {r"\A1;", r"\P", r"%%P"}:
        return True

    return False



def _grouping_cache_key(group_id, interpretation, members):
    signature = "|".join(sorted(
        "{}:{}:{}:{:.6f}:{:.6f}".format(
            clean(m.get("label", "")).casefold(),
            clean(m.get("layer", "")).casefold(),
            clean(m.get("entity_type", "")),
            float(m.get("x") or 0), float(m.get("y") or 0),
        ) for m in members
    ))
    raw = f"GROUP|{group_id.casefold()}|{interpretation.casefold()}|{signature}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_grouped_candidates(dxf_path, cad_labels, coordinate_tolerance=0.5):
    """Use only groups whose every member uniquely matches CAD text."""
    grouping_path = Path(dxf_path).parent / "Workflow08_Label_Grouping_Review.csv"
    if not grouping_path.exists():
        return [], set(), {
            "grouping_file": str(grouping_path), "grouping_file_found": False,
            "groups_loaded": 0, "groups_matched": 0, "groups_skipped": 0,
        }

    grouped = {}
    for row in read_csv(grouping_path):
        gid = clean(row.get("group_id", ""))
        if gid:
            grouped.setdefault(gid, []).append(row)

    candidates, consumed, skipped = [], set(), []
    for gid, rows in grouped.items():
        if len(rows) < 2:
            continue
        interpretations = {clean(r.get("proposed_group_interpretation", "")) for r in rows}
        statuses = {clean(r.get("review_status", "")) for r in rows}
        if len(interpretations) != 1 or not next(iter(interpretations), "") or len(statuses) != 1:
            skipped.append({"group_id": gid, "reason": "Inconsistent interpretation/status"})
            continue

        indexes = []
        valid = True
        for row in rows:
            try:
                tx, ty = float(row["x"]), float(row["y"])
            except (TypeError, ValueError, KeyError):
                valid = False
                break
            matches = [
                i for i, item in enumerate(cad_labels)
                if i not in consumed
                and clean(item.get("label", "")).casefold() == clean(row.get("original_label", "")).casefold()
                and clean(item.get("layer", "")).casefold() == clean(row.get("layer", "")).casefold()
                and clean(item.get("entity_type", "")).upper() == clean(row.get("entity_type", "")).upper()
                and item.get("x") is not None and item.get("y") is not None
                and abs(float(item["x"]) - tx) <= coordinate_tolerance
                and abs(float(item["y"]) - ty) <= coordinate_tolerance
            ]
            if len(matches) != 1:
                valid = False
                break
            indexes.append(matches[0])

        if not valid or len(set(indexes)) != len(rows):
            skipped.append({"group_id": gid, "reason": "Members did not uniquely match CAD text"})
            continue

        members = [cad_labels[i] for i in indexes]
        coords = [{
            "label": clean(r.get("original_label", "")),
            "x": float(r["x"]), "y": float(r["y"]),
            "layer": clean(r.get("layer", "")),
            "entity_type": clean(r.get("entity_type", "")),
        } for r in rows]
        interpretation = next(iter(interpretations))
        item = {
            "label": interpretation,
            "layer": clean(members[0].get("layer", "")),
            "entity_type": "GROUPED_TEXT",
            "x": sum(float(m["x"]) for m in members) / len(members),
            "y": sum(float(m["y"]) for m in members) / len(members),
            "group_id": gid,
            "original_labels": json.dumps([m["label"] for m in members], ensure_ascii=False),
            "grouping_status": next(iter(statuses)),
            "grouping_basis": clean(rows[0].get("grouping_basis", "")),
            "group_confidence": clean(rows[0].get("confidence", "")),
            "member_coordinates": json.dumps(coords, ensure_ascii=False),
        }
        item["cache_key"] = _grouping_cache_key(gid, interpretation, members)
        candidates.append(item)
        consumed.update(indexes)

    return candidates, consumed, {
        "grouping_file": str(grouping_path), "grouping_file_found": True,
        "groups_loaded": len(grouped), "groups_matched": len(candidates),
        "groups_skipped": len(skipped), "skipped_groups": skipped,
        "coordinate_tolerance": coordinate_tolerance,
    }


# APPROVED_LABEL_RULES_V2
# Deterministic interpretations approved by the project owner.
APPROVED_LABEL_RULES = {'FUTUREEXTENSION': ('Proposed building', 'Building', 'Proposed/Future'), 'GREEN': ('Green area or park', 'Green space', 'Existing'), 'BUILDING': ('Building', 'Building', 'Existing'), 'BUSPARKING': ('Parking', 'Parking', 'Existing'), 'CARPARKING': ('Parking', 'Parking', 'Existing'), 'COMMERCIAL': ('Market', 'Commercial', 'Existing'), 'COURTS': ('Sports courts', 'Sports facility', 'Existing'), 'CRICKET': ('Cricket ground', 'Sports facility', 'Existing'), 'DISPOSAL': ('Disposal station', 'Disposal facility', 'Existing'), 'EXISTINGROAD': ('Road', 'Road', 'Existing'), 'EXHIBITIONHALL': ('Hall', 'Hall', 'Existing'), 'FOOTPATH200WIDE': ('Footpath', 'Footpath', 'Existing'), 'FACILITY': ('Building', 'Building', 'Existing'), 'FACULTY': ('Building', 'Building', 'Existing'), 'FOOTPATHLEV': ('Not a feature', 'Annotation', 'Not a feature'), 'FOUNTAIN': ('Water fountain', 'Water feature', 'Existing'), 'FUTURE': ('Not a feature', 'Annotation', 'Not a feature'), 'GARDEN': ('Park or garden', 'Green space', 'Existing'), 'GROUND': ('Hockey ground or cricket ground', 'Context-dependent', 'Unknown'), 'HOCKEY': ('Hockey ground', 'Sports facility', 'Existing'), 'HOSTEL': ('Student hostel', 'Building', 'Existing'), 'LANDSCAPE': ('Not a feature', 'Annotation', 'Not a feature'), 'MAINGATE': ('Entrance', 'Site entrance', 'Existing'), 'OPENAREA': ('Open space', 'Open space', 'Existing'), 'OVERHEAD': ('Overhead reservoir', 'Water storage', 'Existing'), 'PARK': ('Park or garden', 'Green space', 'Existing'), 'PAVEMENTLEV': ('Not a feature', 'Annotation', 'Not a feature'), 'PLOTBOUNDRY': ('Boundary of structure', 'Boundary', 'Unknown'), 'ROAD400WIDE': ('Road', 'Road', 'Existing'), 'ROAD600WIDEROW': ('Road', 'Road', 'Existing'), 'ROAD1000WIDEROW': ('Road', 'Road', 'Existing'), 'ROADLEV': ('Not a feature', 'Annotation', 'Not a feature'), 'SPACEFOR': ('Not a feature', 'Annotation', 'Not a feature'), 'STAFFCOLONY': ('Residence', 'Residential', 'Existing'), 'TENNIS': ('Tennis court', 'Sports facility', 'Existing'), 'TUBEWELL': ('Not a feature', 'Annotation', 'Not a feature'), 'UNDERGROUND': ('Not a feature', 'Contextual text', 'Not a feature'), 'WATERTANK': ('Water tank for water supply', 'Water storage', 'Existing')}

def _approved_rule_for_label(label):
    value = str(label or "").upper()
    value = value.replace("%%U", "").replace("%%O", "")
    key = re.sub(r"[^A-Z0-9]+", "", value)
    return APPROVED_LABEL_RULES.get(key)

def run_runtime_classification(
    dxf_path, catalogue_path, cache_path, output_path,
    api_key, model=DEFAULT_MODEL, max_api_calls=MAX_API_CALLS
):
    catalogue = read_csv(catalogue_path)
    cad_labels = extract_dxf_text(dxf_path)

    cache_path = Path(cache_path)
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        cache = {}

    # Apply approved label rules before any AI classification.
    for item in cad_labels:
        label = item.get("label", "")
        approved = _approved_rule_for_label(label)
        if approved is None:
            continue

        interpreted, feature_group, proposed_or_existing = approved
        key = hashlib.sha256(
            (label.casefold() + "|" + item["layer"].casefold()).encode("utf-8")
        ).hexdigest()

        cache[key] = {
            "label": label,
            "layer": item["layer"],
            "entity_type": item.get("entity_type", ""),
            "group_id": "",
            "original_labels": "",
            "grouping_status": "Owner-approved label rule",
            "grouping_basis": "Approved drawing-label mapping",
            "group_confidence": "High",
            "member_coordinates": "",
            "x": item.get("x", ""),
            "y": item.get("y", ""),
            "interpreted_feature": interpreted,
            "feature_group": feature_group,
            "standard_feature": interpreted,
            "classification_status": (
                "Context-dependent"
                if feature_group == "Context-dependent"
                else "Classified"
            ),
            "confidence": (
                "Medium"
                if feature_group == "Context-dependent"
                else "High"
            ),
            "evidence_used": "Owner-approved label rule",
            "uncertainty_reason": (
                "Requires surrounding label context"
                if feature_group == "Context-dependent"
                else ""
            ),
            "proposed_or_existing": proposed_or_existing,
            "model": "Deterministic approved rule",
        }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    grouped_candidates, consumed_indexes, grouping_report = _load_grouped_candidates(
        dxf_path, cad_labels
    )

    # Build AI candidates in priority order.
    #
    # Important:
    # - Do NOT remove ATTRIB extraction because ATTRIB may contain useful
    #   master-plan information.
    # - Survey-point ATTRIB annotations can be extremely numerous and must
    #   not consume the very limited AI classification budget before genuine
    #   master-plan labels are considered.
    # - Approved rules and cached classifications have already been handled
    #   above and therefore do not consume AI calls.

    candidates = []

    # GROUPED_TEXT candidates remain first because they represent an
    # existing grouping decision produced by the Workflow 08 pipeline.
    for item in grouped_candidates:
        key = item["cache_key"]
        if key not in cache:
            candidates.append((key, item))

    # Separate ordinary CAD labels into high-priority drawing text and
    # lower-priority ATTRIB records.
    high_priority_candidates = []
    attribute_candidates = []

    for idx, item in enumerate(cad_labels):
        if idx in consumed_indexes:
            continue

        label = item["label"]
        entity_type = str(item.get("entity_type", "")).upper()

        if len(label) < 3 or not re.search(r"[A-Za-z]", label):
            continue

        if is_non_feature_label(label):
            continue

        key = hashlib.sha256(
            (label.casefold() + "|" + item["layer"].casefold()).encode("utf-8")
        ).hexdigest()

        if key in cache:
            continue

        # Real drawing TEXT/MTEXT gets priority.
        # ATTRIB is retained, but processed only after ordinary drawing text.
        if entity_type in {"TEXT", "MTEXT"}:
            high_priority_candidates.append((key, item))
        elif entity_type == "ATTRIB":
            attribute_candidates.append((key, item))
        else:
            # Preserve any other supported entity types without allowing
            # them to displace normal TEXT/MTEXT labels.
            high_priority_candidates.append((key, item))

    candidates.extend(high_priority_candidates)
    candidates.extend(attribute_candidates)

    catalogue_context = [
        {
            "feature_group": r.get("feature_group", ""),
            "standard_feature": r.get("standard_feature", ""),
            "common_cad_labels": r.get("common_cad_labels", ""),
            "environmental_relevance": r.get("environmental_relevance", ""),
        }
        for r in catalogue
    ]

    client = Groq(api_key=api_key)
    calls = 0
    failures = []

    for start in range(0, len(candidates), BATCH_SIZE):
        if calls >= max_api_calls:
            break

        batch = candidates[start:start + BATCH_SIZE]
        payload = [
            {
                "label": item["label"],
                "layer": item["layer"],
                "entity_type": item["entity_type"],
                "group_id": item.get("group_id", ""),
                "original_labels": item.get("original_labels", ""),
                "grouping_status": item.get("grouping_status", ""),
                "cache_key": key,
            }
            for key, item in batch
        ]

        prompt = {
            "task": "Classify CAD text labels semantically for a site master plan.",
            "rules": [
                "Use only the supplied label, layer, and catalogue evidence.",
                "Do not infer exact geometry, boundaries, areas, or HPS values.",
                "Do not treat a layer name alone as proof of feature meaning.",
                "GROUPED_TEXT labels are provisional human-proposed groupings, not approved decisions.",
                "Combine split words only when the supplied text supports it; do not invent missing words.",
                "Distinguish existing features from future/proposed features only when the text supports it.",
                "Use the closest catalogue feature only when evidence supports it.",
                "If unsupported, use classification_status='Unresolved'. Use Context-dependent only when the label explicitly needs surrounding context.",
                "Confidence must be High, Medium, or Low.",
                "Return one result for each input label.",
                "Keep every text field very short; evidence and uncertainty should each be under 12 words.",
                "Return JSON only, with a top-level key 'results'.",
            ],
            "catalogue": relevant_catalogue(payload, catalogue_context, limit=8),
            "labels": payload,
            "output_schema": {
                "results": [{
                    "cache_key": "input cache_key",
                    "interpreted_feature": "short text",
                    "feature_group": "catalogue group or blank",
                    "standard_feature": "catalogue feature or blank",
                    "classification_status": "Classified, Context-dependent, or Unresolved",
                    "confidence": "High, Medium, or Low",
                    "evidence_used": "brief evidence",
                    "uncertainty_reason": "brief reason or blank",
                    "proposed_or_existing": "Existing, Proposed/Future, or Unknown",
                }]
            }
        }

        calls += 1  # Count every attempt, including failures.
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a conservative CAD label semantic classifier. Follow the supplied rules exactly."
                    },
                    {
                        "role": "user",
                        "content": json.dumps(prompt, ensure_ascii=False)
                    }
                ],
                temperature=0,
                max_tokens=700,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            results = parsed.get("results", [])

            by_key = {key: item for key, item in batch}
            for result in results:
                key = result.get("cache_key")
                if key not in by_key:
                    continue
                source = by_key[key]
                cache[key] = {
                    "label": source["label"],
                    "layer": source["layer"],
                    "entity_type": source["entity_type"],
                    "group_id": source.get("group_id", ""),
                    "original_labels": source.get("original_labels", ""),
                    "grouping_status": source.get("grouping_status", ""),
                    "grouping_basis": source.get("grouping_basis", ""),
                    "group_confidence": source.get("group_confidence", ""),
                    "member_coordinates": source.get("member_coordinates", ""),
                    "x": source.get("x", ""),
                    "y": source.get("y", ""),
                    "interpreted_feature": result.get("interpreted_feature", ""),
                    "feature_group": result.get("feature_group", ""),
                    "standard_feature": result.get("standard_feature", ""),
                    "classification_status": result.get("classification_status", "Unresolved"),
                    "confidence": result.get("confidence", "Low"),
                    "evidence_used": result.get("evidence_used", ""),
                    "uncertainty_reason": result.get("uncertainty_reason", ""),
                    "proposed_or_existing": result.get("proposed_or_existing", "Unknown"),
                    "model": model,
                }

            # Persist progress after every successful batch.
            cache_path.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

        except Exception as exc:
            message = str(exc)
            failures.append(message)
            break

            # Stop immediately on rate limits, quota errors, or auth failures.
            lowered = message.casefold()
            if any(token in lowered for token in [
                "rate_limit", "rate limit", "quota", "429",
                "401", "403", "invalid api key", "insufficient_quota"
            ]):
                break

            # Do not retry failed batches automatically.
            break

    output_path = Path(output_path)
    fields = [
        "label", "layer", "entity_type", "group_id", "original_labels",
        "grouping_status", "grouping_basis", "group_confidence",
        "member_coordinates", "x", "y", "interpreted_feature",
        "feature_group", "standard_feature", "classification_status",
        "confidence", "evidence_used", "uncertainty_reason",
        "proposed_or_existing", "model"
    ]

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for item in cache.values():
            if item.get("proposed_or_existing") == "Not a feature":
                continue
            if (
                item.get("model") != "Deterministic approved rule"
                and is_non_feature_label(item.get("label", ""))
            ):
                continue
            writer.writerow({field: item.get(field, "") for field in fields})

    return {
        "cad_text_labels_found": len(cad_labels),
        "eligible_labels": len(candidates),
        "cached_classifications": len(cache),
        "api_calls_made": calls,
        "api_call_limit": max_api_calls,
        "remaining_unclassified_this_run": max(0, len(candidates) - calls * BATCH_SIZE),
        "grouping_integration": grouping_report,
        "failures": failures,
        "output_path": str(output_path),
        "cache_path": str(cache_path),
        "model": model,
    }
