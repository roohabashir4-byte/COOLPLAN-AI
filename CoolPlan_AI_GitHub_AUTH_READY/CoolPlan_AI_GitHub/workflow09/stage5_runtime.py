
"""
CoolPlan AI — Workflow 09 Stage 5 Runtime

Independent Stage 5 runtime.

Responsibilities:
1. Accept the existing Workflow 09 categorical project constraints.
2. Build the assessment queue from Stage 4 screening output.
3. Run deterministic Workflow 09 assessment.
4. Run the existing Workflow 09 RAG + AI Agent for each task.
5. Keep deterministic assessment and AI proposal separate.
6. Build a consolidated intervention report.
7. Do not modify Stage 3/Stage 4 data.
8. Do not invent missing feature constraints or component scores.

The application UI can call these functions later.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------
# Existing Workflow 09 components
# ---------------------------------------------------------------------

from workflow09.workflow09_orchestrator import (
    Workflow09Orchestrator,
)


# ---------------------------------------------------------------------
# Default RAG location
# ---------------------------------------------------------------------

DEFAULT_RAG_DIR = Path(
    "/content/Integrated_App/Integrated_App/workflow09/rag_runtime"
)


# ---------------------------------------------------------------------
# Categorical design selections
# ---------------------------------------------------------------------

VALID_DESIGN_SELECTIONS = {
    "available_space": {
        "Available",
        "Limited",
        "Not available",
    },
    "water_availability": {
        "Adequate",
        "Limited",
        "Not available",
    },
    "project_budget": {
        "Low",
        "Moderate",
        "High",
    },
    "maintenance_capacity": {
        "Low",
        "Moderate",
        "High",
    },
}


def validate_stage5_design_selections(
    design_selections: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validate the existing categorical Workflow 09 inputs.

    No conversion or inference is performed.
    """

    if not isinstance(design_selections, dict):
        raise TypeError(
            "design_selections must be a dictionary."
        )

    missing = [
        key
        for key in VALID_DESIGN_SELECTIONS
        if key not in design_selections
    ]

    if missing:
        raise ValueError(
            "Missing Stage 5 design selections: "
            + ", ".join(missing)
        )

    for key, allowed in VALID_DESIGN_SELECTIONS.items():

        value = design_selections[key]

        if value not in allowed:
            raise ValueError(
                f"Invalid value for {key}: {value!r}. "
                f"Allowed values: {sorted(allowed)}"
            )

    return dict(design_selections)


# ---------------------------------------------------------------------
# Build the minimal FeatureCollection expected by Workflow 09 queue
# ---------------------------------------------------------------------

def build_stage5_screening_result(
    stage4_zones,
) -> Dict[str, Any]:
    """
    Convert existing Stage 4 eligible zone records into the
    FeatureCollection required by the existing Workflow 09 queue.

    Stage 4 eligibility and intervention candidates remain authoritative.
    This function only maps the Stage 4 candidate field to the
    Workflow 09 queue field expected by the existing queue builder.
    """

    if not isinstance(stage4_zones, list):
        raise TypeError(
            "stage4_zones must be a list."
        )

    features = []

    for zone in stage4_zones:

        if not isinstance(zone, dict):
            continue

        if zone.get("status") != "ELIGIBLE":
            continue

        candidates = zone.get(
            "intervention_candidates",
            [],
        )

        if not isinstance(candidates, list):
            candidates = []

        screening_record = deepcopy(zone)

        screening_record[
            "eligible_interventions"
        ] = deepcopy(candidates)

        features.append(
            {
                "type": "Feature",
                "geometry": None,
                "properties": {
                    "intervention_screening": screening_record
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


# ---------------------------------------------------------------------
# Extract eligible Stage 4 zones
# ---------------------------------------------------------------------

def extract_eligible_stage4_zones(
    stage4_results: Dict[str, Any],
):
    """
    Extract only ELIGIBLE Stage 4 zones.
    """

    if not isinstance(stage4_results, dict):
        raise TypeError(
            "stage4_results must be a dictionary."
        )

    zones = (
        stage4_results.get("stage4_zones")
        or stage4_results.get("zones")
        or []
    )

    return [
        deepcopy(zone)
        for zone in zones
        if isinstance(zone, dict)
        and zone.get("status") == "ELIGIBLE"
    ]


# ---------------------------------------------------------------------
# Run deterministic assessment
# ---------------------------------------------------------------------

def run_deterministic_assessment(
    orchestrator: Workflow09Orchestrator,
    task: Dict[str, Any],
    design_selections: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Run the existing deterministic assessment adapter.

    Missing feature constraints/component inputs remain missing.
    Nothing is invented.
    """

    return orchestrator.assess_proposal(
        intervention=task["intervention"],
        design_selections=deepcopy(
            design_selections
        ),
        feature_constraints={},
        component_inputs={},
    )


# ---------------------------------------------------------------------
# Run existing RAG + AI Agent
# ---------------------------------------------------------------------

def run_ai_proposal(
    orchestrator: Workflow09Orchestrator,
    task: Dict[str, Any],
    design_selections: Dict[str, Any],
    top_k: int = 3,
    max_output_tokens: int = 500,
) -> Dict[str, Any]:
    """
    Run the existing Workflow 09 Agent.

    Only the individual Stage 5 task is passed to the agent.
    The full project dataset is never sent.
    """

    return orchestrator.run_task(
        task=deepcopy(task),
        design_selections=deepcopy(
            design_selections
        ),
        top_k=top_k,
        category=task.get("intervention"),
        max_output_tokens=max_output_tokens,
    )


# ---------------------------------------------------------------------
# Build final intervention report
# ---------------------------------------------------------------------

def build_intervention_report(
    stage5_results,
    design_selections,
) -> str:
    """
    Build a consolidated Markdown intervention report.

    The report combines:
    - Stage 4 environmental facts
    - deterministic assessment result
    - AI proposal
    - RAG evidence identifiers

    It does not recalculate or alter any result.
    """

    lines = []

    lines.append(
        "# CoolPlan AI — Stage 5 Intervention Report"
    )
    lines.append("")

    lines.append(
        "## Project Design Constraints"
    )
    lines.append("")

    lines.append(
        f"- Available Space: "
        f"{design_selections['available_space']}"
    )

    lines.append(
        f"- Water Availability: "
        f"{design_selections['water_availability']}"
    )

    lines.append(
        f"- Project Budget: "
        f"{design_selections['project_budget']}"
    )

    lines.append(
        f"- Maintenance Capacity: "
        f"{design_selections['maintenance_capacity']}"
    )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "## Proposed Interventions"
    )
    lines.append("")

    for result in stage5_results:

        task = result["task"]
        assessment = result["assessment"]
        ai = result["ai_proposal"]

        zone_id = task.get("zone_id")
        intervention = task.get("intervention")

        lines.append(
            f"### Zone {zone_id}"
        )
        lines.append("")

        lines.append(
            f"**Candidate intervention:** "
            f"{intervention}"
        )
        lines.append("")

        features = task.get(
            "identified_features",
            [],
        )

        issues = task.get(
            "environmental_issues",
            [],
        )

        lines.append(
            "**Identified features:** "
            + (
                ", ".join(map(str, features))
                if features
                else "Not specified"
            )
        )

        lines.append(
            "**Environmental issues:** "
            + (
                ", ".join(map(str, issues))
                if issues
                else "Not specified"
            )
        )

        lines.append("")

        # -------------------------------------------------------------
        # Deterministic assessment
        # -------------------------------------------------------------

        lines.append(
            "#### Deterministic Assessment"
        )
        lines.append("")

        lines.append(
            f"Assessment status: "
            f"{assessment.get('status')}"
        )

        if assessment.get("result") is not None:

            result_data = assessment["result"]

            if isinstance(result_data, dict):

                for key, value in result_data.items():

                    lines.append(
                        f"- **{key}:** {value}"
                    )

        if assessment.get("error"):

            lines.append(
                f"- Assessment error: "
                f"{assessment['error']}"
            )

        lines.append("")

        # -------------------------------------------------------------
        # AI proposal
        # -------------------------------------------------------------

        lines.append(
            "#### AI Proposed Intervention"
        )
        lines.append("")

        proposals = ai.get(
            "proposals",
            [],
        )

        if proposals:

            for proposal in proposals:

                proposed_name = proposal.get(
                    "intervention",
                    intervention,
                )

                rationale = proposal.get(
                    "rationale",
                    "",
                )

                lines.append(
                    f"**Proposal:** {proposed_name}"
                )
                lines.append("")

                lines.append(
                    f"**Rationale:** {rationale}"
                )
                lines.append("")

                evidence_ids = proposal.get(
                    "evidence_chunk_ids",
                    [],
                )

                if evidence_ids:

                    lines.append(
                        "**RAG evidence chunks:** "
                        + ", ".join(
                            map(str, evidence_ids)
                        )
                    )

                    lines.append("")

        else:

            lines.append(
                "No AI proposal was returned."
            )

            if ai.get("error"):

                lines.append(
                    f"Reason: {ai['error']}"
                )

            lines.append("")

        lines.append("---")
        lines.append("")

    lines.append(
        "## Report Notes"
    )
    lines.append("")

    lines.append(
        "- Stage 4 environmental results were not modified."
    )

    lines.append(
        "- AI proposals are evidence-grounded recommendations."
    )

    lines.append(
        "- Deterministic Workflow 09 assessment remains "
        "the authority for suitability and constraint decisions."
    )

    lines.append(
        "- Missing feature constraints and component inputs "
        "were not invented."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------
# Main Stage 5 runner
# ---------------------------------------------------------------------

def run_stage5(
    stage4_results: Dict[str, Any],
    design_selections: Dict[str, Any],
    rag_dir: Optional[Path] = None,
    top_k: int = 3,
    max_output_tokens: int = 300,
) -> Dict[str, Any]:
    """
    Complete independent Stage 5 execution.

    Speed-optimized behavior:
      - Stage 4 eligibility remains authoritative.
      - Deterministic assessment remains per existing candidate.
      - AI/RAG proposal generation runs once per existing Stage 3
        feature_group instead of once per zone/candidate.
      - Zone IDs and candidate interventions remain traceable.
    """

    selections = validate_stage5_design_selections(
        design_selections
    )

    eligible_zones = extract_eligible_stage4_zones(
        stage4_results
    )

    screening_result = build_stage5_screening_result(
        eligible_zones
    )

    orchestrator = None

    try:
        if rag_dir is None:
            rag_dir = DEFAULT_RAG_DIR

        rag_dir = Path(rag_dir)

        from workflow09.workflow09_rag_retriever import (
            Workflow09RAGRetriever
        )

        from workflow09.workflow09_api_client import (
            Workflow09APIClient
        )

        from workflow09.workflow09_agent import (
            Workflow09Agent
        )

        if not rag_dir.exists():
            raise FileNotFoundError(
                f"Workflow 09 RAG runtime not found: {rag_dir}"
            )

        retriever = Workflow09RAGRetriever(
            rag_dir=rag_dir
        )

        api_client = Workflow09APIClient()

        agent = Workflow09Agent(
            retriever=retriever,
            api_client=api_client,
        )

        orchestrator = Workflow09Orchestrator(
            retriever=retriever,
            api_client=api_client,
            agent=agent,
        )

        # ------------------------------------------------------------
        # Existing queue is retained for deterministic assessment.
        # It is NOT changed.
        # ------------------------------------------------------------
        queue = orchestrator.build_queue(
            screening_result=screening_result,
            design_selections=selections,
        )

        tasks = queue.get("tasks", [])

        # ------------------------------------------------------------
        # Deterministic assessment remains candidate-level.
        # This preserves the existing assessment behavior.
        # ------------------------------------------------------------
        results = []

        for task in tasks:
            assessment = run_deterministic_assessment(
                orchestrator=orchestrator,
                task=task,
                design_selections=selections,
            )

            results.append(
                {
                    "zone_id": task.get("zone_id"),
                    "intervention": task.get("intervention"),
                    "task": task,
                    "assessment": assessment,
                    "ai_proposal": None,
                }
            )

        # ------------------------------------------------------------
        # Build groups directly from the existing Stage 4 records.
        # Stage 4 already carries Stage 3 feature_group.
        # ------------------------------------------------------------
        groups = {}

        for zone in eligible_zones:
            if not isinstance(zone, dict):
                continue

            raw_groups = zone.get("feature_group", [])

            if isinstance(raw_groups, str):
                raw_groups = [raw_groups]

            if not isinstance(raw_groups, list):
                raw_groups = []

            clean_groups = []

            for value in raw_groups:
                value_text = str(value).strip()

                if (
                    value_text
                    and value_text.lower() != "nan"
                    and value_text not in clean_groups
                ):
                    clean_groups.append(value_text)

            # Safety fallback:
            # if an eligible zone has no group identity, keep it isolated
            # rather than silently merging it with another group.
            if not clean_groups:
                clean_groups = [
                    f"ZONE_{zone.get('zone_id', 'UNKNOWN')}"
                ]

            for group_name in clean_groups:
                if group_name not in groups:
                    groups[group_name] = {
                        "feature_group": group_name,
                        "zones": [],
                        "intervention_candidates": [],
                    }

                groups[group_name]["zones"].append(
                    {
                        "zone_id": zone.get("zone_id"),
                        "HPS": zone.get("HPS"),
                        "HPS_class": zone.get("HPS_class"),
                        "identified_features": zone.get(
                            "identified_features", []
                        ),
                        "environmental_issues": zone.get(
                            "environmental_issues", []
                        ),
                        "environmental_evidence": zone.get(
                            "environmental_evidence", []
                        ),
                        "intervention_candidates": zone.get(
                            "intervention_candidates", []
                        ),
                    }
                )

                candidates = zone.get(
                    "intervention_candidates",
                    []
                )

                if not isinstance(candidates, list):
                    candidates = []

                for candidate in candidates:
                    candidate_text = str(candidate).strip()

                    if (
                        candidate_text
                        and candidate_text
                        not in groups[group_name][
                            "intervention_candidates"
                        ]
                    ):
                        groups[group_name][
                            "intervention_candidates"
                        ].append(candidate_text)

        # ------------------------------------------------------------
        # ONE AI/RAG request per feature group.
        # ------------------------------------------------------------
        group_results = []

        for group_name, group_task in groups.items():

            ai_proposal = agent.propose_group_interventions(
                group_task=group_task,
                design_selections=selections,
                top_k=min(top_k, 2),
                max_output_tokens=max_output_tokens,
            )

            group_results.append(
                {
                    "feature_group": group_name,
                    "zone_ids": [
                        zone.get("zone_id")
                        for zone in group_task["zones"]
                    ],
                    "intervention_candidates": list(
                        group_task["intervention_candidates"]
                    ),
                    "zones": group_task["zones"],
                    "ai_proposal": ai_proposal,
                }
            )

        # ------------------------------------------------------------
        # Attach the single group AI result back to every applicable
        # candidate result for traceability.
        # ------------------------------------------------------------
        group_lookup = {}

        for group_result in group_results:
            for zone_id in group_result["zone_ids"]:
                group_lookup.setdefault(
                    str(zone_id),
                    []
                ).append(group_result)

        for result in results:
            zone_id = str(result.get("zone_id"))

            matching_groups = group_lookup.get(
                zone_id,
                []
            )

            if matching_groups:
                result["ai_proposal"] = matching_groups[0][
                    "ai_proposal"
                ]
                result["feature_group"] = matching_groups[0][
                    "feature_group"
                ]
                result["ai_group_zone_ids"] = matching_groups[0][
                    "zone_ids"
                ]

        # ------------------------------------------------------------
        # Existing report builder receives the candidate results.
        # ------------------------------------------------------------
        report = build_intervention_report(
            stage5_results=results,
            design_selections=selections,
        )

        return {
            "design_selections": selections,
            "eligible_zone_count": len(
                eligible_zones
            ),
            "task_count": len(tasks),
            "group_count": len(groups),
            "ai_group_count": len(group_results),
            "ai_request_count": len(group_results),
            "queue": queue,
            "results": results,
            "group_results": group_results,
            "report": report,
        }

    finally:
        if orchestrator is not None:
            try:
                orchestrator.close(
                    wait=False
                )
            except Exception:
                pass
