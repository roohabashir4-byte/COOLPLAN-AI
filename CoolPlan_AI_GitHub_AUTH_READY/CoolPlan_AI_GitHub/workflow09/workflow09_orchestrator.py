
"""
CoolPlan AI — Workflow 09 Orchestrator

Connects existing Workflow 09 modules without modifying:
- environmental screening results
- existing RAG index
- existing suitability scorer
- existing application

Important:
Call run_task() from a background worker, not the Streamlit UI thread.
AI proposals are not automatically eligible or scored.
"""

from copy import deepcopy
from typing import Any, Dict, Optional

from .workflow09_agent import Workflow09Agent
from .workflow09_api_client import Workflow09APIClient
from .workflow09_rag_retriever import Workflow09RAGRetriever

from .design_constraints import validate_design_constraints
from .constraint_mapper import map_design_constraints
from .scoring_adapter import assess_intervention
from .assessment_queue import build_assessment_queue


class Workflow09Orchestrator:
    def __init__(
        self,
        retriever: Optional[Workflow09RAGRetriever] = None,
        api_client: Optional[Workflow09APIClient] = None,
        agent: Optional[Workflow09Agent] = None,
    ):
        self.retriever = retriever or Workflow09RAGRetriever()
        self.api_client = api_client or Workflow09APIClient()
        self.agent = agent or Workflow09Agent(
            retriever=self.retriever,
            api_client=self.api_client,
        )

    @staticmethod
    def validate_selections(design_selections: Dict[str, Any]) -> None:
        if not isinstance(design_selections, dict):
            raise TypeError("design_selections must be a dictionary.")
        validate_design_constraints(design_selections)

    @staticmethod
    def build_queue(screening_result, design_selections):
        """
        Uses the existing queue builder.
        Only screening-eligible zones enter this queue.
        Does not modify screening_result.
        """
        Workflow09Orchestrator.validate_selections(design_selections)
        return build_assessment_queue(
            screening_result=deepcopy(screening_result),
            design_selections=deepcopy(design_selections),
        )

    def run_task(
        self,
        task: Dict[str, Any],
        design_selections: Dict[str, Any],
        top_k: int = 5,
        category: Optional[str] = None,
        max_output_tokens: int = 500,
    ) -> Dict[str, Any]:
        """
        Produce AI proposals while preserving the agent's actual status.

        This method does not score proposals or change screening eligibility.
        Run API calls in a background worker.
        """
        self.validate_selections(design_selections)

        if not isinstance(task, dict):
            raise TypeError("task must be a dictionary.")

        task_copy = deepcopy(task)
        selections_copy = deepcopy(design_selections)

        try:
            proposal_result = self.agent.propose_interventions(
                task=task_copy,
                design_selections=selections_copy,
                top_k=top_k,
                category=category,
                max_output_tokens=max_output_tokens,
            )

            if not isinstance(proposal_result, dict):
                return {
                    "status": "PENDING",
                    "task": task_copy,
                    "proposals": None,
                    "assessment": None,
                    "error": "INVALID_AGENT_RESULT",
                    "note": "Screening results remain unchanged.",
                }

            agent_status = proposal_result.get("status", "PENDING")
            successful = agent_status == "COMPLETED"

            return {
                "status": (
                    "PROPOSALS_RETURNED" if successful else agent_status
                ),
                "task": task_copy,
                "proposals": proposal_result,
                "assessment": None,
                "note": (
                    "AI proposals are not approvals. "
                    "Constraint and component assessment remain separate."
                    if successful
                    else
                    "The proposal step did not complete successfully. "
                    "Screening results remain unchanged."
                ),
            }

        except Exception as exc:
            return {
                "status": "AGENT_ERROR",
                "task": task_copy,
                "proposals": None,
                "assessment": None,
                "error": str(exc),
                "note": "Screening results remain unchanged.",
            }


    @staticmethod
    def assess_proposal(
        intervention: str,
        design_selections: Dict[str, Any],
        feature_constraints: Optional[Dict[str, Any]] = None,
        component_inputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sends a proposal to the existing deterministic assessment adapter.

        Supply only verified feature constraints and defensible component
        inputs. Missing inputs are passed through as missing; this method
        does not infer site conditions or manufacture scores.
        """
        Workflow09Orchestrator.validate_selections(design_selections)

        if not isinstance(intervention, str) or not intervention.strip():
            raise ValueError("intervention must be a non-empty string.")

        if feature_constraints is not None and not isinstance(
            feature_constraints, dict
        ):
            raise TypeError("feature_constraints must be a dictionary or None.")

        if component_inputs is not None and not isinstance(
            component_inputs, dict
        ):
            raise TypeError("component_inputs must be a dictionary or None.")

        try:
            result = assess_intervention(
                intervention=intervention,
                design_selections=deepcopy(design_selections),
                feature_constraints=deepcopy(feature_constraints or {}),
                component_inputs=deepcopy(component_inputs or {}),
            )

            return {
                "status": "ASSESSMENT_RETURNED",
                "intervention": intervention,
                "result": result,
            }

        except Exception as exc:
            return {
                "status": "ASSESSMENT_ERROR",
                "intervention": intervention,
                "result": None,
                "error": str(exc),
            }

    def close(self, wait: bool = False):
        """Close the API client's background executor when appropriate."""
        close_method = getattr(self.api_client, "close", None)
        if callable(close_method):
            close_method(wait=wait)


def create_orchestrator():
    """Convenience factory for application or notebook use."""
    return Workflow09Orchestrator()
