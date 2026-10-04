# CoolPlan AI

AI Micro-Cooling & Heat-Resilient Site Planner.

## Development rule
The same deployment-ready `core/` modules are tested in Colab and used by the final Streamlit application. No temporary Colab-only workflow logic should be created.

## Current status
- Workflow 00 — Location Engine: deployment-ready module created from the tested location workflow
- Workflow 01 — Environmental Engine: deployment-ready module included
- Workflow 02 — Site Plan Engine: deployment-ready module included
- Workflow 03 — Zone Engine: IN PROGRESS; deployment-ready module not finalized yet

## Structure
- `app.py` — final Streamlit application
- `core/` — reusable deployment-ready workflow modules
- `data/` — structured application data
- `assets/` — visual assets
- `tests/` — tests
- `workflows/` — workflow-specific tests and documentation

## Critical rule
Project analysis must always use the user-confirmed project location. No random, old, or silently substituted coordinates are permitted.
