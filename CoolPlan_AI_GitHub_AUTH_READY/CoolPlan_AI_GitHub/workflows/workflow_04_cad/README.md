# CoolPlan AI — Workflow 04: CAD Engine

## Purpose

Extract and validate project-boundary geometry from DXF/CAD drawings.

## Input

DXF master/site plan.

## Process

1. Read DXF.
2. Identify CAD layers.
3. Extract the BOUNDARY layer.
4. Separate connected boundary components.
5. Detect open boundary endpoints.
6. Check nearby CAD geometry.
7. Determine whether the boundary is closed.
8. Flag incomplete/ambiguous boundaries for confirmation.

## Important Safety Rule

The system does NOT automatically close boundary gaps.

If the CAD boundary is incomplete, the status is:

BOUNDARY_REQUIRES_CONFIRMATION

## Tested Result

The test DXF contained:

- 34 BOUNDARY entities
- 5 boundary components
- C1: 23 entities
- C2: 6 entities
- C3: 3 entities
- C4: 1 entity
- C5: 1 entity

The final test correctly returned:

BOUNDARY_REQUIRES_CONFIRMATION

## Production Behavior

A confirmed boundary will later be aligned with the satellite map before
being passed to the Environmental Engine.

## Status

WORKFLOW 04 — TESTED
