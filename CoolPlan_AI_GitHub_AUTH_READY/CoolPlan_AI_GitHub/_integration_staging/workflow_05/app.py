import json
import math
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from pyproj import Transformer
from shapely.geometry import Polygon, mapping

from core.boundary import extract_boundary
from core.placement import place_boundary
from core.survey import inspect_survey_dxf

st.set_page_config(page_title="CoolPlan AI — Workflow 05", layout="wide")
st.title("CoolPlan AI — Workflow 05")
st.subheader("Project Boundary Placement & Verification")
st.caption(
    "Colab test build. The starting location and drawing scale are assumptions; "
    "verify alignment against survey control before engineering use."
)

DEFAULT_DXF = "/content/NAROWAL SURVEY PLAN FINAL.dxf"
DEFAULT_LAT = 32.0924562
DEFAULT_LON = 74.7580475
DEFAULT_SCALE = 0.3048  # adopted test assumption: 1 CAD unit = 1 foot

component = components.declare_component(
    "coolplan_boundary_editor",
    path=str(Path(__file__).parent / "boundary_editor"),
)

with st.sidebar:
    st.header("Survey input")
    uploaded = st.file_uploader("Upload survey DXF (optional)", type=["dxf"])
    dxf_path = st.text_input("DXF path in Colab", value=DEFAULT_DXF)
    layer_name = st.text_input("Boundary layer", value="BOUNDARY")
    st.caption("The source DXF is read only.")

if uploaded is not None:
    temp_dir = Path("/content/CoolPlan_AI_Workflow_05_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    active_dxf = temp_dir / uploaded.name
    active_dxf.write_bytes(uploaded.getbuffer())
else:
    active_dxf = Path(dxf_path)

if not active_dxf.exists():
    st.error(f"DXF file not found: {active_dxf}")
    st.info("Upload your survey DXF or ensure the path is correct.")
    st.stop()

try:
    survey_report = inspect_survey_dxf(active_dxf)
    boundary = extract_boundary(active_dxf, layer_name=layer_name)
except Exception as exc:
    st.error(f"Could not inspect/extract the boundary: {exc}")
    st.stop()

with st.expander("Survey inspection", expanded=False):
    st.write({
        "file": survey_report["file_name"],
        "format": survey_report["format"],
        "drawing_units": survey_report["units"],
        "entity_count": survey_report["entity_count"],
        "boundary_layer": boundary["layer"],
        "boundary_handle": boundary["handle"],
        "boundary_vertices": len(boundary["points"]),
        "candidate_boundaries": boundary["candidate_count"],
        "survey_ready_for_alignment": survey_report["survey_ready_for_alignment"],
    })
    for warning in survey_report["warnings"]:
        st.warning(warning)

if "placement_center_lat" not in st.session_state:
    st.session_state.placement_center_lat = DEFAULT_LAT
if "placement_center_lon" not in st.session_state:
    st.session_state.placement_center_lon = DEFAULT_LON
if "placement_scale" not in st.session_state:
    st.session_state.placement_scale = DEFAULT_SCALE
if "placement_rotation" not in st.session_state:
    st.session_state.placement_rotation = 0.0
if "dragged_coordinates" not in st.session_state:
    initial = place_boundary(
        boundary["points"], DEFAULT_LON, DEFAULT_LAT,
        DEFAULT_SCALE, 0.0
    )
    # Shapely mapping coordinates are [longitude, latitude].
    ring = initial["geometry"]["coordinates"][0]
    st.session_state.dragged_coordinates = [[lat, lon] for lon, lat in ring[:-1]]
if "confirmed_geojson" not in st.session_state:
    st.session_state.confirmed_geojson = None

st.markdown(
    "**Move:** drag the cyan boundary itself. Use rotation and scale controls "
    "for orientation and size. Confirm to enable GeoJSON export."
)

control_col, map_col = st.columns([1, 2.3], gap="large")
with control_col:
    st.markdown("### Placement controls")
    new_scale = st.number_input(
        "Scale (metres per CAD unit)",
        min_value=0.0001, max_value=100000.0,
        value=float(st.session_state.placement_scale), format="%.4f",
        help="Set this from verified drawing units/scale. Current value is an assumption.",
    )
    new_rotation = st.slider(
        "Rotation (degrees)", -180.0, 180.0,
        float(st.session_state.placement_rotation), 1.0,
    )
    if new_scale != st.session_state.placement_scale or new_rotation != st.session_state.placement_rotation:
        st.session_state.placement_scale = float(new_scale)
        st.session_state.placement_rotation = float(new_rotation)
        # Rebuild from original CAD points using the current centre.
        placed = place_boundary(
            boundary["points"],
            st.session_state.placement_center_lon,
            st.session_state.placement_center_lat,
            st.session_state.placement_scale,
            st.session_state.placement_rotation,
        )
        ring = placed["geometry"]["coordinates"][0]
        st.session_state.dragged_coordinates = [[lat, lon] for lon, lat in ring[:-1]]
        st.session_state.confirmed_geojson = None
        st.rerun()

    if st.button("Reset placement", use_container_width=True):
        st.session_state.placement_center_lat = DEFAULT_LAT
        st.session_state.placement_center_lon = DEFAULT_LON
        st.session_state.placement_scale = DEFAULT_SCALE
        st.session_state.placement_rotation = 0.0
        placed = place_boundary(
            boundary["points"], DEFAULT_LON, DEFAULT_LAT, DEFAULT_SCALE, 0.0
        )
        ring = placed["geometry"]["coordinates"][0]
        st.session_state.dragged_coordinates = [[lat, lon] for lon, lat in ring[:-1]]
        st.session_state.confirmed_geojson = None
        st.rerun()

with map_col:
    edited = component(
        coordinates=st.session_state.dragged_coordinates,
        center=[
            st.session_state.placement_center_lat,
            st.session_state.placement_center_lon,
        ],
        height=650,
        key="workflow05_map",
    )

    if isinstance(edited, dict) and edited.get("coordinates"):
        coords = edited["coordinates"]
        if len(coords) >= 3:
            st.session_state.dragged_coordinates = [
                [float(p[0]), float(p[1])] for p in coords
            ]
            # Track the actual moved polygon's geographic centre.
            st.session_state.placement_center_lat = sum(p[0] for p in coords) / len(coords)
            st.session_state.placement_center_lon = sum(p[1] for p in coords) / len(coords)
            st.session_state.confirmed_geojson = None

coords = st.session_state.dragged_coordinates
polygon = Polygon([(lon, lat) for lat, lon in coords])

st.divider()
st.markdown("### Confirm and export")
a, b = st.columns([1, 2])
with a:
    if st.button("Confirm boundary", type="primary", use_container_width=True):
        if not polygon.is_valid or polygon.is_empty:
            st.error("The boundary is invalid. Review the geometry before confirming.")
        else:
            st.session_state.confirmed_geojson = {
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {
                        "source_dxf": str(active_dxf),
                        "boundary_handle": boundary["handle"],
                        "source_layer": boundary["layer"],
                        "scale_m_per_unit": st.session_state.placement_scale,
                        "rotation_degrees": st.session_state.placement_rotation,
                        "placement_status": "user_confirmed_approximate",
                    },
                    "geometry": mapping(polygon),
                }],
            }

with b:
    if st.session_state.confirmed_geojson:
        st.success("Boundary confirmed. Download the GeoJSON below.")
        st.download_button(
            "Download confirmed boundary (GeoJSON)",
            data=json.dumps(st.session_state.confirmed_geojson, indent=2),
            file_name="coolplan_confirmed_boundary.geojson",
            mime="application/geo+json",
            use_container_width=True,
        )
    else:
        st.info("Drag the boundary, review it, then click Confirm boundary.")

st.warning(
    "This is an approximate manual placement. The default centre is not a "
    "survey control point. The adopted 0.3048 m/unit scale must be verified. "
    "Do not treat this output as survey-grade georeferencing."
)
