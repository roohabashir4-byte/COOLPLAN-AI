import json
import hashlib
import importlib.util
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import ee
import folium
from folium.plugins import Draw
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from core.environmental import (
    initialize_earth_engine,
    run_environmental_analysis,
)
from core.zones import (
    create_zone_grid,
    calculate_zone_values,
    zones_to_dataframe,
)

# ---------------------------------------------------------
# APP CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="CoolPlan AI",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_DIR = Path(__file__).resolve().parent

boundary_editor_component = components.declare_component(
    "coolplan_boundary_editor",
    path=str(BASE_DIR / "boundary_editor"),
)
TEST_BOUNDARY = BASE_DIR / "data" / "uet_narowal_campus_boundary.geojson"
GRID_SIZE_M = 100

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(135deg, #071827 0%, #0b2632 55%, #102f35 100%);
        color: #e8f4f1;
    }
    [data-testid="stSidebar"] {
        background: #0b202d;
        border-right: 1px solid #24534f;
    }
    h1, h2, h3 {
        color: #e7fff5 !important;
    }
    p, label, span {
        color: #d4e7e2;
    }
    div[data-testid="stMetric"] {
        background: rgba(20, 65, 65, 0.55);
        border: 1px solid #28675d;
        padding: 15px;
        border-radius: 12px;
    }
    div.stButton > button {
        background: #16a085;
        color: white;
        border: 0;
        border-radius: 9px;
        font-weight: 600;
    }
    div.stButton > button:hover {
        background: #20b99b;
        color: white;
    }
    .hero {
        padding: 22px 26px;
        border-radius: 18px;
        background: linear-gradient(120deg, #103d43, #14534b);
        border: 1px solid #28786a;
        margin-bottom: 20px;
    }
    .hero p {
        color: #d2eee5;
        margin-bottom: 0;
    }
    .small-note {
        color: #a9c9c1;
        font-size: 0.9rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# HEADER
# ---------------------------------------------------------

logo_path = BASE_DIR / "assets" / "CoolPlanAI_animated_logo.gif"

if logo_path.exists():
    left, right = st.columns([1, 5], vertical_alignment="center")
    with left:
        import base64
        logo_data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        st.components.v1.html(
            f"""
            <div style="display:flex;justify-content:center;align-items:center;">
                <img
                    src="data:image/gif;base64,{logo_data}"
                    style="width:190px;max-width:100%;height:190px;object-fit:contain;display:block;"
                    alt="CoolPlan AI animated logo"
                />
            </div>
            """,
            height=200,
            scrolling=False,
        )
    with right:
        st.markdown(
            """
            <div class="hero">
                <h1>CoolPlan AI</h1>
                <p>Environmental intelligence for climate-responsive planning and design.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    st.markdown(
        """
        <div class="hero">
            <h1>🌿 CoolPlan AI</h1>
            <p>Environmental intelligence for climate-responsive planning and design.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

if "zones_df" not in st.session_state:
    st.session_state.zones_df = None

if "zones_geojson" not in st.session_state:
    st.session_state.zones_geojson = None

if "project_name" not in st.session_state:
    st.session_state.project_name = None

if "boundary_geojson" not in st.session_state:
    st.session_state.boundary_geojson = None


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def load_geojson(path):
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    if data.get("type") not in ("FeatureCollection", "Feature"):
        raise ValueError("The uploaded file is not a valid GeoJSON feature.")

    return data


def get_boundary_geojson(uploaded_file):
    if uploaded_file is None:
        return None

    content = uploaded_file.getvalue()
    data = json.loads(content.decode("utf-8"))

    if data.get("type") not in ("FeatureCollection", "Feature"):
        raise ValueError("Please upload a valid GeoJSON boundary.")

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".geojson",
        delete=False,
        encoding="utf-8",
    )
    json.dump(data, temp_file)
    temp_file.close()

    return temp_file.name


def geocode_address(address):
    """Search an address using OpenStreetMap, with a fallback service."""
    import urllib.parse
    import urllib.request
    import json

    query = urllib.parse.urlencode({
        "q": address,
        "format": "jsonv2",
        "limit": 1
    })

    # Try OpenStreetMap first.
    try:
        request = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{query}",
            headers={"User-Agent": "CoolPlanAI/1.0"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            results = json.loads(response.read().decode("utf-8"))

        if results:
            item = results[0]
            return (
                float(item["lat"]),
                float(item["lon"]),
                item.get("display_name", address)
            )
    except Exception:
        pass

    # Fallback search.
    fallback_query = urllib.parse.urlencode({
        "q": address,
        "limit": 1
    })
    request = urllib.request.Request(
        f"https://photon.komoot.io/api/?{fallback_query}",
        headers={"User-Agent": "CoolPlanAI/1.0"}
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        features = data.get("features", [])
        if features:
            item = features[0]
            lon, lat = item["geometry"]["coordinates"]
            name = item.get("properties", {}).get("name", address)
            return float(lat), float(lon), name

    except Exception as exc:
        raise ValueError(
            f"Address services did not respond: {exc}"
        )

    raise ValueError("No matching location found. Try a more specific address.")

def geojson_bounds(data):
    """Return Leaflet bounds [[south, west], [north, east]] from GeoJSON."""
    values = []
    def walk(obj):
        if isinstance(obj, (list, tuple)):
            if len(obj) >= 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
                lon, lat = float(obj[0]), float(obj[1])
                if -180 <= lon <= 180 and -90 <= lat <= 90:
                    values.append((lat, lon))
            else:
                for child in obj:
                    walk(child)
        elif isinstance(obj, dict):
            if obj.get("type") == "FeatureCollection":
                for feature in obj.get("features", []): walk(feature)
            elif obj.get("type") == "Feature":
                walk(obj.get("geometry", {}))
            elif "coordinates" in obj:
                walk(obj["coordinates"])
    walk(data)
    if not values:
        return None
    lats = [p[0] for p in values]
    lons = [p[1] for p in values]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def normalize_drawings_to_geojson(drawings):
    if isinstance(drawings, dict) and drawings.get("type") == "FeatureCollection":
        return drawings
    if isinstance(drawings, dict) and drawings.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [drawings]}
    if isinstance(drawings, list):
        features = []
        for item in drawings:
            if isinstance(item, dict) and item.get("type") == "Feature":
                features.append(item)
            elif isinstance(item, dict) and item.get("geometry"):
                features.append({"type": "Feature", "properties": item.get("properties", {}), "geometry": item["geometry"]})
        if features:
            return {"type": "FeatureCollection", "features": features}
    raise ValueError("The map did not return an editable polygon. Finish editing and try again.")


def get_boundary_geojson_from_data(data):
    temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".geojson", delete=False, encoding="utf-8")
    json.dump(data, temp_file)
    temp_file.close()
    return temp_file.name


def safe_number(value, digits=2):
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return "N/A"


def hps_color(value):
    if value is None:
        return "#87969b"

    try:
        value = float(value)
    except (TypeError, ValueError):
        return "#87969b"

    if value >= 75:
        return "#b91c1c"
    if value >= 50:
        return "#ea580c"
    if value >= 25:
        return "#eab308"
    return "#16a34a"


def run_project_analysis(
    project_name,
    latitude,
    longitude,
    analysis_days,
    boundary_path,
):
    with st.spinner("Connecting to Google Earth Engine..."):
        initialize_earth_engine()

    with st.spinner("Processing satellite imagery and environmental indicators..."):
        result = run_environmental_analysis(
            latitude=latitude,
            longitude=longitude,
            analysis_days=analysis_days,
            boundary_geojson=boundary_path,
        )

    with st.spinner("Creating the 100 m grid and calculating zone values..."):
        grid = create_zone_grid(
            result["study_area"],
            cell_size_m=GRID_SIZE_M,
        )

        zones = calculate_zone_values(grid, result)
        zones_df = zones_to_dataframe(zones)
        # Convert grid geometries to WGS84 longitude/latitude for Folium.
        zones_for_map = zones.map(
            lambda feature: feature.setGeometry(
                feature.geometry().transform("EPSG:4326", 1)
            )
        )
        zones_info = zones_for_map.getInfo()

        print("COOLPLAN GRID DIAGNOSTICS")
        print("Grid feature count:", len(zones_info.get("features", [])))
        print("Zone table rows:", len(zones_df))
        if zones_info.get("features"):
            first = zones_info["features"][0]
            print("First geometry type:", first.get("geometry", {}).get("type"))
            print("First geometry coordinates:",
                  str(first.get("geometry", {}).get("coordinates"))[:500])
            print("First properties:", first.get("properties", {}))

        # Workflow 03 IDs and HPS classes, shared with map features.
        features = zones_info.get("features", [])
        if len(features) != len(zones_df):
            raise RuntimeError(
                f"Zone mismatch: {len(features)} map features, "
                f"{len(zones_df)} dataframe rows."
            )

        for index, feature in enumerate(features):
            props = feature.setdefault("properties", {})
            row = zones_df.iloc[index]

            props["zone_id"] = str(row["zone_id"])
            props["HPS_class"] = str(row["HPS_class"])
            for column in (
                "HPS", "LST_C", "NDVI", "NDBI",
                "VEGETATION_DEFICIT",
            ):
                if column in zones_df.columns:
                    value = row[column]
                    props[column] = None if pd.isna(value) else float(value)

    st.session_state.analysis_result = result
    st.session_state.zones_df = zones_df
    st.session_state.zones_geojson = zones_info
    st.session_state.project_name = project_name


def get_zone_lookup(zones_df):
    if zones_df is None or zones_df.empty:
        return {}

    return {
        str(row["zone_id"]): row.to_dict()
        for _, row in zones_df.iterrows()
    }


# SIDEBAR — PROJECT SETUP
# ---------------------------------------------------------

st.sidebar.title("Project Setup")

project_mode = st.sidebar.radio(
    "Choose an analysis mode",
    ["Analyze Test Project", "Analyze New Project"],
)

project_name = "UET Narowal Campus"
latitude = 32.0919
longitude = 74.7640
analysis_days = 365
boundary_path = None
boundary_geojson = None

if project_mode == "Analyze Test Project":
    st.sidebar.success("Test project: UET Narowal, Punjab")
    st.sidebar.caption("The saved campus boundary will be used if available.")

    latitude = st.sidebar.number_input(
        "Campus latitude",
        value=32.0919,
        format="%.6f",
        disabled=True,
    )
    longitude = st.sidebar.number_input(
        "Campus longitude",
        value=74.7640,
        format="%.6f",
        disabled=True,
    )

    if TEST_BOUNDARY.exists():
        boundary_path = str(TEST_BOUNDARY)
        try:
            boundary_geojson = load_geojson(boundary_path)
        except Exception as exc:
            st.sidebar.error(f"Could not read the saved boundary: {exc}")
    else:
        st.sidebar.warning(
            "The saved campus boundary file was not found. "
            "Upload the boundary under Analyze New Project, or place the "
            "saved file at /content/uet_narowal_campus_boundary.geojson."
        )

else:
    if st.session_state.get("coolplan_saved_boundary"):
        boundary_geojson = st.session_state["coolplan_saved_boundary"]
        boundary_path = get_boundary_geojson_from_data(boundary_geojson)
        saved_center = geojson_bounds(boundary_geojson)
        if saved_center:
            latitude = (saved_center[0][0] + saved_center[1][0]) / 2
            longitude = (saved_center[0][1] + saved_center[1][1]) / 2
    project_name = st.sidebar.text_input(
        "Project name",
        value="My Study Area",
    )

    st.sidebar.markdown("**Find project location**")
    address = st.sidebar.text_input(
        "Project address or place name",
        key="new_project_address",
        placeholder="e.g. University of Engineering and Technology, Narowal",
    )
    if st.sidebar.button("Search address", key="search_project_address", use_container_width=True):
        if not address.strip():
            st.sidebar.warning("Enter an address or place name first.")
        else:
            try:
                with st.spinner("Searching address..."):
                    found_lat, found_lon, found_name = geocode_address(address.strip())

                st.session_state["new_project_lat"] = found_lat
                st.session_state["new_project_lon"] = found_lon
                st.session_state["new_project_lat_widget"] = found_lat
                st.session_state["new_project_lon_widget"] = found_lon
                st.session_state["new_project_location_name"] = found_name
                st.sidebar.success(f"Location found: {found_name}")
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"Location search failed: {type(exc).__name__}: {exc}")

    if (
        not st.session_state.get("new_project_location_name")
        and st.session_state.get("new_project_lat") == 32.0919
        and st.session_state.get("new_project_lon") == 74.7640
    ):
        st.session_state["new_project_lat"] = 0.0
        st.session_state["new_project_lon"] = 0.0
        st.session_state.pop("new_project_lat_widget", None)
        st.session_state.pop("new_project_lon_widget", None)

    if "new_project_lat" not in st.session_state:
        st.session_state["new_project_lat"] = 0.0
    if "new_project_lon" not in st.session_state:
        st.session_state["new_project_lon"] = 0.0

    latitude = st.sidebar.number_input(
        "Latitude",
        min_value=-90.0,
        max_value=90.0,
        value=float(st.session_state["new_project_lat"]),
        format="%.6f",
        key="new_project_lat_widget",
    )
    longitude = st.sidebar.number_input(
        "Longitude",
        min_value=-180.0,
        max_value=180.0,
        value=float(st.session_state["new_project_lon"]),
        format="%.6f",
        key="new_project_lon_widget",
    )
    st.session_state["new_project_lat"] = latitude
    st.session_state["new_project_lon"] = longitude
    if st.session_state.get("new_project_location_name"):
        st.sidebar.caption(f"Found: {st.session_state['new_project_location_name']}")

    boundary_source = st.sidebar.radio(
        "Boundary source",
        ["GeoJSON boundary", "Survey DXF"],
        key="workflow05_boundary_source",
    )

    if boundary_source == "GeoJSON boundary":
        uploaded_boundary = st.sidebar.file_uploader(
            "Upload study-area boundary (GeoJSON)",
            type=["geojson", "json"],
            help="Upload a GeoJSON Feature or FeatureCollection.",
            key="workflow05_geojson_upload",
        )

        if uploaded_boundary is not None:
            try:
                boundary_path = get_boundary_geojson(uploaded_boundary)
                boundary_geojson = json.loads(
                    uploaded_boundary.getvalue().decode("utf-8")
                )
                st.sidebar.success("GeoJSON boundary loaded.")
            except Exception as exc:
                st.sidebar.error(f"Invalid boundary file: {exc}")

    else:
        import json
        import tempfile
        from core.boundary import extract_boundary
        from core.placement import place_boundary
        from core.survey import inspect_survey_dxf

        uploaded_dxf = st.sidebar.file_uploader(
            "Upload survey drawing (DXF)",
            type=["dxf"],
            key="workflow05_dxf_upload",
        )

        dxf_layer = st.sidebar.text_input(
            "Boundary layer name",
            value="BOUNDARY",
            key="workflow05_dxf_layer",
        )

        scale_m_per_unit = st.sidebar.number_input(
            "Metres per CAD drawing unit",
            min_value=0.000001,
            value=0.3048,
            format="%.6f",
            help="0.3048 assumes the drawing uses feet. Verify this against your survey.",
            key="workflow05_scale",
        )

        rotation_degrees = st.sidebar.number_input(
            "Boundary rotation (degrees)",
            value=0.0,
            step=1.0,
            key="workflow05_rotation",
        )

        st.sidebar.caption(
            "Placement is approximate. Confirm the drawing units, scale, "
            "rotation and map location before using the results."
        )

        if uploaded_dxf is not None:
            try:
                with tempfile.NamedTemporaryFile(
                    suffix=".dxf", delete=False
                ) as temp_dxf:
                    temp_dxf.write(uploaded_dxf.getvalue())
                    dxf_path = temp_dxf.name

                survey_report = inspect_survey_dxf(dxf_path)
                st.sidebar.subheader("Survey inspection")

                extracted = extract_boundary(
                    dxf_path,
                    layer_name=dxf_layer,
                )

                placed = place_boundary(
                    cad_points=extracted["points"],
                    target_longitude=longitude,
                    target_latitude=latitude,
                    scale_m_per_unit=scale_m_per_unit,
                    rotation_degrees=rotation_degrees,
                )

                boundary_geojson = {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "properties": {
                            "source": "Workflow 05 survey DXF",
                            "layer": extracted["layer"],
                            "handle": extracted["handle"],
                            "candidate_count": extracted["candidate_count"],
                            "placement": placed["placement"],
                            "projected_crs": placed["projected_crs"],
                        },
                        "geometry": placed["geometry"],
                    }],
                }

                placed_path = (
                    Path("/content/CoolPlan_AI_Final/data")
                    / "workflow05_placed_boundary.geojson"
                )
                placed_path.parent.mkdir(parents=True, exist_ok=True)
                placed_path.write_text(
                    json.dumps(boundary_geojson, indent=2),
                    encoding="utf-8",
                )
                boundary_path = str(placed_path)

                st.sidebar.success(
                    f"Survey boundary prepared. "
                    f"Layer: {extracted['layer']}; "
                    f"candidates found: {extracted['candidate_count']}."
                )

                st.sidebar.download_button(
                    "Download placed boundary",
                    data=json.dumps(boundary_geojson, indent=2),
                    file_name="workflow05_placed_boundary.geojson",
                    mime="application/geo+json",
                    key="workflow05_download_boundary",
                )

            except Exception as exc:
                boundary_path = None
                boundary_geojson = None
                st.sidebar.error(f"Could not prepare DXF boundary: {exc}")


# ---------------------------------------------------------
# PROJECT SWITCH — CLEAR PREVIOUS PROJECT RESULTS
# ---------------------------------------------------------

_current_project_identity = (
    str(project_mode),
    str(project_name),
)

_previous_project_identity = st.session_state.get(
    "coolplan_active_project_identity"
)

if _previous_project_identity != _current_project_identity:
    # Clear project-specific analysis outputs.
    st.session_state["analysis_result"] = None
    st.session_state["zones_df"] = None
    st.session_state["zones_geojson"] = None
    st.session_state["project_name"] = None

    # Clear only the previously saved New Project boundary.
    # This does not affect the boundary editor, dragging, rotation,
    # or any map functionality.
    if project_mode == "Analyze New Project":
        st.session_state.pop("coolplan_saved_boundary", None)

    # Clear project-specific Stage 2 results.
    for _key in (
        "stage2_project_hash",
        "stage2_project_name",
        "stage2_results",
        "stage2_source_name",
    ):
        st.session_state.pop(_key, None)

    # Record the newly selected project.
    st.session_state["coolplan_active_project_identity"] = (
        _current_project_identity
    )


# Boundary editor: move or rotate the complete boundary before analysis.
if project_mode == "Analyze New Project" and boundary_geojson:
    st.markdown("### Confirm project boundary")
    st.caption(
        "Choose Move to reposition the whole boundary, or Rotate to rotate it. "
        "After editing, click Save edited boundary. "
        "The saved boundary will be used for environmental analysis."
    )

    # Convert the current GeoJSON polygon to Leaflet [latitude, longitude].
    # Support the GeoJSON structures produced by the DXF workflow.
    if boundary_geojson.get("type") == "FeatureCollection":
        features = boundary_geojson.get("features", [])
        geometry = features[0].get("geometry", {}) if features else {}
    elif boundary_geojson.get("type") == "Feature":
        geometry = boundary_geojson.get("geometry", {})
    else:
        geometry = boundary_geojson

    coordinates = geometry.get("coordinates", [])

    if geometry.get("type") == "Polygon" and coordinates:
        ring = coordinates[0]
    elif geometry.get("type") == "MultiPolygon" and coordinates:
        ring = coordinates[0][0]
    else:
        ring = []


    editor_coordinates = [[lat, lon] for lon, lat in ring]
    editor_center = [latitude, longitude]

    component_key = "coolplan_boundary_editor_component"
    editor_result = boundary_editor_component(
        center=editor_center,
        coordinates=editor_coordinates,
        key=component_key,
        default=None,
    )

    if editor_result and editor_result.get("coordinates"):
        st.session_state["coolplan_pending_boundary_coordinates"] = (
            editor_result["coordinates"]
        )

    if st.button("Save edited boundary", key="save_edited_boundary"):
        edited_coordinates = st.session_state.get(
            "coolplan_pending_boundary_coordinates"
        )

        if edited_coordinates and len(edited_coordinates) >= 3:
            # Leaflet returns [latitude, longitude]; GeoJSON requires
            # [longitude, latitude]. Close the polygon ring.
            ring = [[lon, lat] for lat, lon in edited_coordinates]
            if ring[0] != ring[-1]:
                ring.append(ring[0])

            edited_geojson = {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring],
                },
            }

            boundary_geojson = edited_geojson
            boundary_path = get_boundary_geojson_from_data(boundary_geojson)
            st.session_state["coolplan_saved_boundary"] = boundary_geojson
            st.session_state.pop(
                "coolplan_pending_boundary_coordinates", None
            )
            st.success("Edited boundary saved for this analysis.")
            st.rerun()
        else:
            st.warning(
                "No edited boundary was received. Move or rotate the boundary, "
                "then try saving again."
            )

analysis_days = st.sidebar.selectbox(
    "Satellite analysis period",
    options=[90, 180, 365, 730],
    index=2,
    format_func=lambda days: f"Previous {days} days",
)

st.sidebar.caption("Grid cell size: 100 m × 100 m")

start_analysis = st.sidebar.button(
    "Run Environmental Analysis",
    use_container_width=True,
)

if start_analysis:
    if not boundary_path or not boundary_geojson:
        st.error(
            "Please load or confirm your project boundary before "
            "running Environmental Analysis."
        )
    else:
        try:
            run_project_analysis(
                project_name=project_name,
                latitude=latitude,
                longitude=longitude,
                analysis_days=analysis_days,
                boundary_path=boundary_path,
            )
            st.success("Environmental analysis completed.")
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")
            st.exception(exc)


# ---------------------------------------------------------
# MAIN DASHBOARD
# ---------------------------------------------------------

result = st.session_state.analysis_result
zones_df = st.session_state.zones_df
zones_geojson = st.session_state.zones_geojson

if result is None or zones_df is None or zones_geojson is None:
    st.info(
        "Choose a project in the sidebar, confirm its location and boundary, "
        "then select **Run Environmental Analysis**."
    )

    st.markdown("### What CoolPlan AI analyzes")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 🌡️ Land Surface Temperature")
        st.write("Maps surface heat using Landsat satellite imagery.")

    with col2:
        st.markdown("#### 🌱 Vegetation")
        st.write("Measures vegetation using NDVI from Sentinel-2 imagery.")

    with col3:
        st.markdown("#### 🏙️ Built-up Intensity")
        st.write("Uses NDBI to help characterize built-up surfaces.")

    st.markdown("### Heat Priority Score")
    st.write(
        "HPS combines normalized heat, vegetation deficit, and built-up "
        "intensity using the weights defined in your environmental module."
    )

    st.stop()


# ---------------------------------------------------------
# SUMMARY METRICS
# ---------------------------------------------------------

summary = result.get("summary", {})

st.markdown(f"## {st.session_state.project_name}")

st.caption(
    f"Analysis period: {result.get('start_date', 'N/A')} to "
    f"{result.get('end_date', 'N/A')} · Grid: 100 m × 100 m"
)

m1, m2, m3, m4 = st.columns(4)

m1.metric("Grid zones", f"{len(zones_df):,}")
m2.metric("Point HPS", safe_number(summary.get("hps")))
m3.metric("Minimum HPS", safe_number(summary.get("hps_min")))
m4.metric("Maximum HPS", safe_number(summary.get("hps_max")))

st.markdown("### Satellite data")

s1, s2, s3, s4 = st.columns(4)
s1.metric("Landsat images", summary.get("landsat_images", "N/A"))
s2.metric("Usable Landsat", summary.get("usable_landsat_images", "N/A"))
s3.metric("Sentinel-2 images", summary.get("sentinel_images", "N/A"))
s4.metric("Usable Sentinel-2", summary.get("usable_sentinel_images", "N/A"))


# ---------------------------------------------------------
# INTERACTIVE MAP
# ---------------------------------------------------------

st.markdown("### Interactive Environmental Map")
st.write("Click any grid cell to view its environmental results.")

center = [latitude, longitude]

map_object = folium.Map(
    location=center,
    zoom_start=16,
    tiles=None,
    control_scale=True,
)

folium.TileLayer(
    tiles="OpenStreetMap",
    name="Street map",
    overlay=False,
    control=True,
).add_to(map_object)

folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
          "World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri World Imagery",
    name="Satellite imagery",
    overlay=False,
    control=True,
).add_to(map_object)

zone_lookup = get_zone_lookup(zones_df)

def zone_style(feature):
    properties = feature.get("properties", {})
    color = hps_color(properties.get("HPS"))

    return {
        "fillColor": color,
        "color": "#263238",
        "weight": 2.0,
        "opacity": 1,
        "fillOpacity": 0.78,
    }


def zone_highlight(feature):
    return {
        "weight": 3,
        "color": "#ffffff",
        "fillOpacity": 0.75,
    }


# Ensure every map cell has an ID matching the zone table.
for index, feature in enumerate(zones_geojson.get("features", [])):
    feature.setdefault("properties", {})["zone_id"] = (
        f"Z_{index + 1:03d}"
    )

if not zones_geojson.get("features"):
    st.warning(
        "No grid-cell features were returned by the analysis. "
        "The basemap and boundary can still display, but the grid itself "
        "must be checked in core/zones.py."
    )

# Zoom to the actual grid extent so cells cannot be off-screen when the map
# center differs from the environmental grid geometry.
grid_bounds = geojson_bounds(zones_geojson)
if grid_bounds:
    map_object.fit_bounds(grid_bounds, padding=(24, 24))
else:
    st.error("Grid features exist, but their coordinates are not valid longitude/latitude values. Check core/zones.py geometry projection.")

folium.GeoJson(
    zones_geojson,
    name="100 m environmental grid",
    style_function=zone_style,
    highlight_function=zone_highlight,
    tooltip=folium.GeoJsonTooltip(
        fields=["zone_id"],
        aliases=["Zone ID:"],
        sticky=True,
    ),
    popup=folium.GeoJsonPopup(
        fields=["zone_id", "HPS", "LST_C", "NDVI", "NDBI",
                "VEGETATION_DEFICIT"],
        aliases=["Zone ID:", "HPS:", "LST (°C):", "NDVI:",
                 "NDBI:", "Vegetation Deficit:"],
        labels=True,
    ),
).add_to(map_object)

# Draw the boundary after the grid with no fill, so it cannot hide the cells.
if boundary_geojson:
    folium.GeoJson(
        boundary_geojson,
        name="Study-area boundary",
        style_function=lambda feature: {
            "fill": False,
            "fillOpacity": 0,
            "color": "#00ffd0",
            "weight": 3,
        },
        tooltip="Study-area boundary",
    ).add_to(map_object)

folium.LayerControl(collapsed=True).add_to(map_object)

map_col, legend_col = st.columns([4, 1])

with map_col:
    map_state = st_folium(
        map_object,
        height=590,
        use_container_width=True,
        returned_objects=["last_active_drawing", "last_object_clicked"],
        key="coolplan_environmental_map",
    )

with legend_col:
    st.markdown("#### HPS legend")
    st.markdown(
        """
        <div style="line-height:2.1">
        <span style="color:#16a34a">■</span> 0–24: Lower<br>
        <span style="color:#eab308">■</span> 25–49: Moderate<br>
        <span style="color:#ea580c">■</span> 50–74: High<br>
        <span style="color:#b91c1c">■</span> 75–100: Very high<br>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Colors are based on HPS values. Boundary cells may be smaller "
        "than 100 m × 100 m because they are clipped to the study area."
    )


# ---------------------------------------------------------
# SELECTED ZONE
# ---------------------------------------------------------

selected_zone_id = None

if map_state:
    drawing = map_state.get("last_active_drawing")

    if drawing:
        selected_zone_id = (
            drawing.get("properties", {}).get("zone_id")
        )

if selected_zone_id is None:
    st.caption(
        "Select a grid cell on the map. If your map does not return a "
        "selection, use the zone selector below."
    )

zone_ids = zones_df["zone_id"].astype(str).tolist()

if selected_zone_id not in zone_ids:
    selected_zone_id = None

selected_zone_id = st.selectbox(
    "Select a zone",
    options=zone_ids,
    index=(
        zone_ids.index(selected_zone_id)
        if selected_zone_id in zone_ids
        else 0
    ),
)

selected_rows = zones_df[
    zones_df["zone_id"].astype(str) == str(selected_zone_id)
]

if not selected_rows.empty:
    zone = selected_rows.iloc[0]

    st.markdown(f"### Zone {zone['zone_id']}")

    z1, z2, z3 = st.columns(3)
    z1.metric("LST", f"{safe_number(zone.get('LST_C'))} °C")
    z2.metric("NDVI", safe_number(zone.get("NDVI"), 3))
    z3.metric("NDBI", safe_number(zone.get("NDBI"), 3))

    z4, z5, z6 = st.columns(3)
    z4.metric(
        "Vegetation Deficit",
        safe_number(zone.get("vegetation_deficit"), 2),
    )
    z5.metric("HPS", safe_number(zone.get("HPS"), 2))
    z6.metric("HPS Class", str(zone.get("HPS_class", "N/A")))

    st.caption(
        f"Zone area: {safe_number(zone.get('zone_area_m2'), 1)} m²"
    )


# ---------------------------------------------------------
# ZONE TABLE AND INDICATOR GUIDE
# ---------------------------------------------------------

with st.expander("View all zone results"):
    st.dataframe(
        zones_df,
        use_container_width=True,
        hide_index=True,
    )

    csv = zones_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Download zone results (CSV)",
        data=csv,
        file_name="coolplan_zone_results.csv",
        mime="text/csv",
    )

with st.expander("Indicator definitions"):
    st.markdown(
        """
        | Indicator | Meaning |
        |---|---|
        | **LST** | Land Surface Temperature, in °C |
        | **NDVI** | Normalized Difference Vegetation Index; indicates vegetation greenness |
        | **NDBI** | Normalized Difference Built-up Index; helps identify built-up surfaces |
        | **Vegetation Deficit** | The vegetation-deficit layer calculated by the environmental module |
        | **HPS** | Heat Priority Score, calculated by the existing model |
        | **HPS Class** | Category assigned to a zone's HPS |
        """
    )

st.caption(
    "CoolPlan AI · Environmental analysis results depend on satellite "
    "coverage, cloud masking, selected dates, and the supplied boundary."
)

# ---------------------------------------------------------
# STAGE 2 — MASTER PLAN & AI FEATURE IDENTIFICATION
# ---------------------------------------------------------
# COOLPLAN_STAGE_2_INTEGRATION

import hashlib as _cp_hashlib
import importlib.util as _cp_importlib_util
import json as _cp_json
import os as _cp_os
import sys as _cp_sys
from pathlib import Path as _CP_Path

st.divider()
st.header("Stage 2 — Master Plan & AI Feature Identification")
st.caption(
    "Identify features from the selected project's master plan. "
    "Review the results before proceeding."
)

_cp_app_dir = _CP_Path(__file__).resolve().parent
_cp_workflow08_dir = (
    _cp_app_dir / "_integration_staging" / "workflow_08"
)
_cp_runtime_file = (
    _cp_workflow08_dir
    / "runtime_workspace"
    / "Current_Working_App"
    / "workflow08"
    / "core"
    / "cad_semantic_runtime.py"
)
_cp_catalogue_file = (
    _cp_workflow08_dir
    / "runner_inputs"
    / "Workflow08_Expanded_Feature_Catalogue.csv"
)
_cp_test_dxf = (
    _cp_app_dir
    / "_integration_staging"
    / "workflow_06"
    / "Narowal_Master_Plan_Local_Coordinates_Text_Preserved_No_Dimensions.dxf"
)

try:
    _cp_api_key = str(st.secrets["GROQ_API_KEY"]).strip()
except Exception:
    _cp_api_key = _cp_os.environ.get("GROQ_API_KEY", "").strip()

_cp_project_name = str(
    st.session_state.get("project_name", "My Study Area")
)
_cp_is_test_project = (
    _cp_project_name.strip().casefold() == "uet narowal campus"
)

_cp_uploaded_dxf = None
_cp_use_test_plan = False

if _cp_is_test_project:
    st.info("Test Project master plan is preloaded.")
    _cp_use_test_plan = True
    st.caption("Drawing: Narowal master plan")
else:
    _cp_uploaded_dxf = st.file_uploader(
        "Upload your master plan (DXF)",
        type=["dxf"],
        key="stage2_master_plan_upload",
        help="Upload the DXF for the currently selected project.",
    )

_cp_run_stage2 = st.button(
    "Identify Master Plan Features",
    type="primary",
    key="stage2_identify_features",
)

if _cp_run_stage2:
    if not _cp_api_key:
        st.error(
            "The Stage 2 service is not configured in this session. "
            "Please configure the API key in the Colab environment."
        )
    elif not _cp_runtime_file.is_file():
        st.error("The Stage 2 classification runtime was not found.")
    elif not _cp_catalogue_file.is_file():
        st.error("The shared feature catalogue was not found.")
    elif _cp_is_test_project and not _cp_test_dxf.is_file():
        st.error("The preloaded Test Project master plan was not found.")
    elif not _cp_is_test_project and _cp_uploaded_dxf is None:
        st.warning("Upload a DXF master plan first.")
    else:
        _cp_temp_dir = (
            _cp_app_dir
            / "_integration_staging"
            / "workflow_08"
            / "app_runtime"
        )
        _cp_temp_dir.mkdir(parents=True, exist_ok=True)

        if _cp_is_test_project:
            _cp_dxf_bytes = _cp_test_dxf.read_bytes()
            _cp_dxf_name = _cp_test_dxf.name
        else:
            _cp_dxf_bytes = _cp_uploaded_dxf.getvalue()
            _cp_dxf_name = _cp_uploaded_dxf.name

        _cp_identity = (
            _cp_project_name
            + "|"
            + _cp_dxf_name
            + "|"
        ).encode("utf-8")

        _cp_project_hash = _cp_hashlib.sha256(
            _cp_identity + _cp_dxf_bytes
        ).hexdigest()[:20]

        _cp_project_dir = _cp_temp_dir / _cp_project_hash
        _cp_project_dir.mkdir(parents=True, exist_ok=True)

        _cp_dxf_path = _cp_project_dir / "master_plan.dxf"
        _cp_dxf_path.write_bytes(_cp_dxf_bytes)

        _cp_cache_path = _cp_project_dir / "classification_cache.json"
        _cp_output_path = _cp_project_dir / "feature_classification.csv"

        try:
            _cp_spec = _cp_importlib_util.spec_from_file_location(
                "coolplan_stage2_runtime",
                str(_cp_runtime_file),
            )
            if _cp_spec is None or _cp_spec.loader is None:
                raise ImportError("Could not load the Stage 2 runtime.")

            _cp_runtime = _cp_importlib_util.module_from_spec(_cp_spec)
            _cp_spec.loader.exec_module(_cp_runtime)

            with st.spinner("Identifying features in the master plan..."):
                _cp_result = _cp_runtime.run_runtime_classification(
                    dxf_path=_cp_dxf_path,
                    catalogue_path=_cp_catalogue_file,
                    cache_path=_cp_cache_path,
                    output_path=_cp_output_path,
                    api_key=_cp_api_key,
                    model=_cp_runtime.DEFAULT_MODEL,
                    max_api_calls=_cp_runtime.MAX_API_CALLS,
                )

            _cp_results_df = pd.read_csv(_cp_output_path).fillna("")

            # Do not display technical model metadata.
            _cp_hidden_columns = {"model"}
            _cp_display_df = _cp_results_df[
                [
                    _cp_col
                    for _cp_col in _cp_results_df.columns
                    if _cp_col not in _cp_hidden_columns
                ]
            ]

            st.session_state["stage2_project_hash"] = _cp_project_hash
            st.session_state["stage2_project_name"] = _cp_project_name
            st.session_state["stage2_results"] = _cp_display_df
            st.session_state["stage2_source_name"] = _cp_dxf_name

            st.success("Stage 2 feature identification finished.")

        except Exception as _cp_error:
            st.error(
                "Stage 2 could not complete. "
                "Review the error details below."
            )
            st.exception(_cp_error)

if (
    st.session_state.get("stage2_results") is not None
    and st.session_state.get("stage2_project_name") == _cp_project_name
):
    st.subheader("Review identified features")

    st.caption(
        "Check the identified features and their classification. "
        "These results belong to the current project."
    )

    st.dataframe(
        st.session_state["stage2_results"],
        use_container_width=True,
        hide_index=True,
    )

    _cp_download_df = st.session_state["stage2_results"]
    st.download_button(
        "Download feature identification results (CSV)",
        data=_cp_download_df.to_csv(index=False).encode("utf-8"),
        file_name="stage2_feature_identification.csv",
        mime="text/csv",
        key="stage2_download_results",
    )


# ---------------------------------------------------------
# STAGE 3 — ENVIRONMENTAL CAD OVERLAY + FEATURE → ZONE MATCHING
# ---------------------------------------------------------
# ============================================================
# COOLPLAN AI — STAGE 3
# Current Test Project HPS Overlay + Feature/Zone Association
#
# The CAD/drawing logic lives in:
# workflow08/stage3/hps_overlay_generator.py
# ============================================================

try:
    from workflow08.stage3.hps_overlay_generator import (
        generate_stage3_overlay,
    )

    _cp_stage3_available = True

except Exception as _cp_stage3_import_error:
    _cp_stage3_available = False
    _cp_stage3_import_error = str(
        _cp_stage3_import_error
    )


# Stage 3 is intentionally limited to the Test Project
# for the current integration step.
# Stage 3 is available for the current project
# when Stage 2 and the confirmed boundary are ready.
_cp_stage3_is_test_project = True

_cp_stage2_ready = (
    st.session_state.get(
        "stage2_results"
    ) is not None
    and
    st.session_state.get(
        "stage2_project_name"
    )
    ==
    st.session_state.get(
        "project_name"
    )
)

_cp_stage3_boundary_ready = (
    boundary_geojson is not None
)

_cp_stage3_should_show = (
    _cp_stage3_is_test_project
    and
    _cp_stage2_ready
    and
    _cp_stage3_boundary_ready
)


if _cp_stage3_should_show:

    st.markdown("---")
    st.subheader(
        "Stage 3 — AI-Assisted Feature-to-Zone Association & HPS Overlay"
    )

    st.caption(
        "Stage 3 uses the current Stage 2 master plan and "
        "current environmental analysis. No previous Stage 3 "
        "results are used as current output."
    )

    _cp_stage3_run = st.button(
        "Run Stage 3",
        key="coolplan_stage3_run",
        type="primary",
    )

    if _cp_stage3_run:

        if not _cp_stage3_available:

            st.error(
                "Stage 3 module could not be loaded."
            )

            st.code(
                _cp_stage3_import_error
            )

        else:

            try:

                _cp_stage3_project_hash = (
                    st.session_state.get(
                        "stage2_project_hash"
                    )
                )

                _cp_stage3_source_dxf = (
                    st.session_state.get(
                        "stage2_master_plan_path"
                    )
                )

                # If Stage 2 did not store the path in session,
                # recover it from the existing Stage 2 runtime
                # structure using the project hash.
                if not _cp_stage3_source_dxf:

                    _cp_stage3_hash = (
                        _cp_stage3_project_hash
                    )

                    _cp_stage3_runtime_root = (
                        _cp_app_dir
                        / "_integration_staging"
                        / "workflow_08"
                        / "app_runtime"
                    )

                    if _cp_stage3_hash:

                        _cp_stage3_candidate_dir = (
                            _cp_stage3_runtime_root
                            / str(
                                _cp_stage3_hash
                            )
                        )

                        _cp_stage3_candidate_dxf = (
                            _cp_stage3_candidate_dir
                            / "master_plan.dxf"
                        )

                        if (
                            _cp_stage3_candidate_dxf.exists()
                        ):
                            _cp_stage3_source_dxf = (
                                str(
                                    _cp_stage3_candidate_dxf
                                )
                            )

                if not _cp_stage3_source_dxf:

                    raise FileNotFoundError(
                        "The current Stage 2 master-plan DXF "
                        "could not be located."
                    )

                # Keep Stage 3 outputs inside the current project's
                # runtime folder.
                _cp_stage3_output_dir = (
                    _cp_app_dir
                    / "_integration_staging"
                    / "workflow_08"
                    / "app_runtime"
                    / str(_cp_stage3_project_hash)
                )

                _cp_stage3_output_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                _cp_stage3_result = (
                    generate_stage3_overlay(
                        master_plan_path=(
                            _cp_stage3_source_dxf
                        ),
                        zones_geojson=zones_geojson,
                        boundary_geojson=boundary_geojson,
                        output_dir=(
                            _cp_stage3_output_dir
                        ),
                        stage2_results=(
                            st.session_state.get(
                                "stage2_results"
                            )
                        ),
                        project_hash=(
                            _cp_stage3_project_hash
                        ),
                    )
                )

                st.session_state[
                    "stage3_project_hash"
                ] = _cp_stage3_project_hash

                st.session_state[
                    "stage3_results"
                ] = _cp_stage3_result

                st.session_state[
                    "stage3_overlay_path"
                ] = _cp_stage3_result[
                    "overlay_path"
                ]

                st.success(
                    "Stage 3 completed successfully."
                )

            except Exception as _cp_stage3_error:

                st.error(
                    "Stage 3 failed."
                )

                st.exception(
                    _cp_stage3_error
                )


# ------------------------------------------------------------
# Display only the Stage 3 result calculated for the current
# Stage 2 project.
# ------------------------------------------------------------

_cp_stage3_saved = (
    st.session_state.get(
        "stage3_results"
    )
)

_cp_stage3_current_hash = (
    st.session_state.get(
        "stage2_project_hash"
    )
)

if (
    _cp_stage3_saved
    and
    _cp_stage3_saved.get(
        "project_hash"
    )
    ==
    _cp_stage3_current_hash
):

    st.markdown(
        "### Stage 3 Result"
    )

    _cp_stage3_col1, _cp_stage3_col2, _cp_stage3_col3 = (
        st.columns(3)
    )

    _cp_stage3_col1.metric(
        "Environmental Zones",
        _cp_stage3_saved.get(
            "zone_count",
            0,
        ),
    )

    _cp_stage3_col2.metric(
        "Stage 2 Features Matched",
        _cp_stage3_saved.get(
            "matched_feature_count",
            0,
        ),
    )

    _cp_stage3_col3.metric(
        "Feature-Zone Associations",
        _cp_stage3_saved.get(
            "association_row_count",
            0,
        ),
    )

    _cp_stage3_overlay_path = (
        _cp_stage3_saved.get(
            "overlay_path"
        )
    )

    _cp_stage3_association_path = (
        _cp_stage3_saved.get(
            "association_path"
        )
    )

    if _cp_stage3_overlay_path:

        _cp_stage3_overlay_file = Path(
            _cp_stage3_overlay_path
        )

        if _cp_stage3_overlay_file.exists():

            with open(
                _cp_stage3_overlay_file,
                "rb",
            ) as _cp_stage3_file:

                st.download_button(
                    "Download Stage 3 HPS Master Plan DXF",
                    data=_cp_stage3_file.read(),
                    file_name=(
                        _cp_stage3_overlay_file.name
                    ),
                    mime=(
                        "application/dxf"
                    ),
                    key="coolplan_stage3_dxf_download",
                )

    if _cp_stage3_association_path:

        _cp_stage3_association_file = Path(
            _cp_stage3_association_path
        )

        if _cp_stage3_association_file.exists():

            with open(
                _cp_stage3_association_file,
                "rb",
            ) as _cp_stage3_file:

                st.download_button(
                    "Download Stage 3 Feature-Zone CSV",
                    data=_cp_stage3_file.read(),
                    file_name=(
                        _cp_stage3_association_file.name
                    ),
                    mime=(
                        "text/csv"
                    ),
                    key="coolplan_stage3_csv_download",
                )

    _cp_stage3_df = (
        _cp_stage3_saved.get(
            "association_df"
        )
    )

    if (
        _cp_stage3_df is not None
        and
        not _cp_stage3_df.empty
    ):

        st.markdown(
            "#### Feature-to-Zone Associations"
        )

        # Display one row per feature.
        # Multiple associated zones are combined inside the same row.
        # The complete association CSV remains unchanged and available
        # for download.

        # Group by the actual Stage 2 feature identity.
        # Do NOT group by standard_feature because multiple
        # Stage 2 features can share the same semantic category.
        _cp_stage3_feature_col = (
            "label"
            if "label" in _cp_stage3_df.columns
            else (
                "interpreted_feature"
                if "interpreted_feature" in _cp_stage3_df.columns
                else "standard_feature"
            )
        )

        # Load the actual environmental zone geometry.
        # Coordinates shown in the table are polygon centroids
        # in the GeoJSON coordinate system (longitude, latitude).

        import json as _cp_stage3_json
        from shapely.geometry import shape as _cp_stage3_shape

        _cp_stage3_zone_geometry = {}

        try:
            with open(
                zones_geojson,
                "r",
                encoding="utf-8",
            ) as _cp_zone_file:
                _cp_zone_geojson = _cp_stage3_json.load(
                    _cp_zone_file
                )

            for _cp_zone_feature in _cp_zone_geojson.get(
                "features",
                [],
            ):
                _cp_zone_properties = (
                    _cp_zone_feature.get("properties")
                    or {}
                )

                _cp_zone_id = str(
                    _cp_zone_properties.get(
                        "zone_id",
                        "",
                    )
                ).strip()

                _cp_zone_geometry_data = (
                    _cp_zone_feature.get("geometry")
                )

                if (
                    _cp_zone_id
                    and _cp_zone_geometry_data
                ):
                    try:
                        _cp_zone_geometry = (
                            _cp_stage3_shape(
                                _cp_zone_geometry_data
                            )
                        )

                        _cp_zone_centroid = (
                            _cp_zone_geometry.centroid
                        )

                        _cp_stage3_zone_geometry[
                            _cp_zone_id
                        ] = (
                            float(
                                _cp_zone_centroid.x
                            ),
                            float(
                                _cp_zone_centroid.y
                            ),
                        )
                    except Exception:
                        pass

        except Exception:
            _cp_stage3_zone_geometry = {}

        _cp_stage3_grouped_rows = []


        for (
            _cp_stage3_feature,
            _cp_stage3_group,
        ) in _cp_stage3_df.groupby(
            _cp_stage3_feature_col,
            sort=False,
            dropna=False,
        ):

            _cp_stage3_zone_details = []

            for _, _cp_stage3_row in _cp_stage3_group.iterrows():

                _cp_zone = str(
                    _cp_stage3_row.get("zone_id", "")
                ).strip()

                _cp_hps = _cp_stage3_row.get("HPS", "")
                _cp_hps_class = str(
                    _cp_stage3_row.get("HPS_class", "")
                ).strip()

                _cp_lst = _cp_stage3_row.get("LST_C", "")
                _cp_ndvi = _cp_stage3_row.get("NDVI", "")
                _cp_ndbi = _cp_stage3_row.get("NDBI", "")
                _cp_veg = _cp_stage3_row.get(
                    "VEGETATION_DEFICIT",
                    "",
                )

                _cp_zone_coordinates = (
                    _cp_stage3_zone_geometry.get(
                        _cp_zone
                    )
                )

                if _cp_zone_coordinates is not None:
                    _cp_zone_x, _cp_zone_y = (
                        _cp_zone_coordinates
                    )

                    _cp_coordinate_text = (
                        f"({{_cp_zone_x:.6f}}, "
                        f"{{_cp_zone_y:.6f}})"
                    )
                else:
                    _cp_coordinate_text = (
                        "(coordinates unavailable)"
                    )

                _cp_detail = (
                    f"{_cp_zone}"
                    f" — {_cp_coordinate_text}"
                    f" — HPS {float(_cp_hps):.4f}"
                    if _cp_hps != ""
                    else
                    f"{_cp_zone}"
                    f" — {_cp_coordinate_text}"
                    f" — HPS unavailable"
                )

                _cp_stage3_zone_details.append(
                    _cp_detail
                )

            _cp_stage3_grouped_rows.append(
                {
                    "Feature": str(
                        _cp_stage3_feature
                    ),
                    "Zone Count": int(
                        _cp_stage3_group["zone_id"].nunique()
                    ),
                    "Zones / Environmental Details": (
                        "\n".join(
                            _cp_stage3_zone_details
                        )
                    ),
                }
            )

        _cp_stage3_grouped_display = pd.DataFrame(
            _cp_stage3_grouped_rows
        )

        st.dataframe(
            _cp_stage3_grouped_display,
            use_container_width=True,
            hide_index=True,
        )
elif _cp_stage3_is_test_project and _cp_stage2_ready:

    st.info(
        "Stage 3 is ready. Click 'Run Stage 3' to calculate "
        "the current feature-to-zone associations and HPS drawing."
    )



# ------------------------------------------------------------
# STAGE 4 — WORKFLOW 09 INTERVENTION SCREENING
# ------------------------------------------------------------
# Uses only the current Stage 3 runtime results and the
# current environmental zones.
#
# Does NOT:
# - rerun Stage 2
# - rerun Stage 3
# - recalculate HPS
# - identify CAD features
# - modify environmental source values
# ------------------------------------------------------------

try:
    from workflow09.stage4_runtime_adapter import (
        run_stage4_from_stage3,
    )

    _cp_stage4_available = True
    _cp_stage4_import_error = ""

except Exception as _cp_stage4_import_exception:

    _cp_stage4_available = False
    _cp_stage4_import_error = str(
        _cp_stage4_import_exception
    )


# ------------------------------------------------------------
# Current Stage 3 runtime result
# ------------------------------------------------------------

_cp_stage4_saved_stage3 = st.session_state.get(
    "stage3_results"
)

_cp_stage4_current_project_hash = st.session_state.get(
    "stage2_project_hash"
)


_cp_stage4_stage3_ready = (
    isinstance(
        _cp_stage4_saved_stage3,
        dict,
    )
    and
    _cp_stage4_saved_stage3.get(
        "project_hash"
    )
    ==
    _cp_stage4_current_project_hash
    and
    isinstance(
        _cp_stage4_saved_stage3.get(
            "association_df"
        ),
        pd.DataFrame,
    )
    and
    isinstance(
        zones_geojson,
        dict,
    )
    and
    zones_geojson.get(
        "type"
    )
    ==
    "FeatureCollection"
)


# ------------------------------------------------------------
# Stage 4 controls
# ------------------------------------------------------------

if _cp_stage4_stage3_ready:

    st.markdown("---")

    st.subheader(
        "Stage 4 — Intervention Zone Selection"
    )

    st.caption(
        "Stage 4 uses the current Stage 3 "
        "feature-to-zone associations and "
        "environmental zones. It does not "
        "recalculate HPS or rerun earlier stages."
    )

    _cp_stage4_run = st.button(
        "Run Stage 4",
        key="coolplan_stage4_run",
        type="primary",
    )

    if _cp_stage4_run:

        if not _cp_stage4_available:

            st.error(
                "Stage 4 module could not be loaded."
            )

            st.code(
                _cp_stage4_import_error
            )

        else:

            try:

                # --------------------------------------------------------
                # Runtime execution indicator
                # --------------------------------------------------------
                # Stage 4 is recalculated from the CURRENT Stage 3
                # runtime result every time the button is pressed.
                # No artificial delay is introduced.
                # --------------------------------------------------------

                with st.spinner(
                    "Running Stage 4 intervention screening..."
                ):

                    _cp_stage4_result = (
                        run_stage4_from_stage3(
                            stage3_result=(
                                _cp_stage4_saved_stage3
                            ),
                            zones_geojson=(
                                zones_geojson
                            ),
                            constraints={},
                            percentile_cutoff=0.75,
                        )
                    )

                # --------------------------------------------------------
                # Store ONLY the freshly calculated runtime result
                # --------------------------------------------------------

                st.session_state[
                    "stage4_project_hash"
                ] = (
                    _cp_stage4_current_project_hash
                )

                st.session_state[
                    "stage4_results"
                ] = _cp_stage4_result

                st.success(
                    "Stage 4 completed successfully."
                )

            except Exception as _cp_stage4_error:

                st.error(
                    "Stage 4 failed."
                )

                st.exception(
                    _cp_stage4_error
                )


# ------------------------------------------------------------
# Display saved Stage 4 result
# ------------------------------------------------------------

_cp_stage4_saved = st.session_state.get(
    "stage4_results"
)

_cp_stage4_saved_hash = st.session_state.get(
    "stage4_project_hash"
)


if (
    isinstance(
        _cp_stage4_saved,
        dict,
    )
    and
    _cp_stage4_saved_hash
    ==
    _cp_stage4_current_project_hash
):

    st.markdown(
        "### Stage 4 Result"
    )

    _cp_stage4_col1, _cp_stage4_col2, _cp_stage4_col3 = (
        st.columns(3)
    )

    _cp_stage4_col1.metric(
        "Environmental Zones",
        _cp_stage4_saved.get(
            "zone_count",
            0,
        ),
    )

    _cp_stage4_col2.metric(
        "Eligible Zones",
        _cp_stage4_saved.get(
            "eligible_zone_count",
            0,
        ),
    )

    _cp_stage4_col3.metric(
        "Screening Version",
        _cp_stage4_saved.get(
            "stage4_version",
            "—",
        ),
    )

    _cp_stage4_zones = (
        _cp_stage4_saved.get(
            "zones",
            [],
        )
    )

    _cp_stage4_eligible_rows = []

    for _cp_stage4_zone in _cp_stage4_zones:

        if (
            _cp_stage4_zone.get(
                "status"
            )
            != "ELIGIBLE"
        ):
            continue

        _cp_stage4_features = (
            _cp_stage4_zone.get(
                "identified_features",
                [],
            )
        )

        _cp_stage4_feature_names = []

        for _cp_stage4_feature in _cp_stage4_features:

            if isinstance(
                _cp_stage4_feature,
                dict,
            ):

                _cp_stage4_feature_names.append(
                    str(
                        _cp_stage4_feature.get(
                            "feature",
                            "",
                        )
                    )
                )

            else:

                _cp_stage4_feature_names.append(
                    str(
                        _cp_stage4_feature
                    )
                )

        _cp_stage4_eligible_rows.append(
            {
                "Zone":
                    _cp_stage4_zone.get(
                        "zone_id",
                        "",
                    ),

                "HPS":
                    _cp_stage4_zone.get(
                        "HPS",
                        "",
                    ),

                "HPS Class":
                    _cp_stage4_zone.get(
                        "HPS_class",
                        "",
                    ),

                "Identified Features":
                    ", ".join(
                        _cp_stage4_feature_names
                    ),

                "Environmental Issues":
                    ", ".join(
                        map(
                            str,
                            _cp_stage4_zone.get(
                                "environmental_issues",
                                [],
                            ),
                        )
                    ),

                "Intervention Candidates":
                    ", ".join(
                        map(
                            str,
                            _cp_stage4_zone.get(
                                "intervention_candidates",
                                [],
                            )
                        )
                    ),
            }
        )

    if _cp_stage4_eligible_rows:

        st.dataframe(
            pd.DataFrame(
                _cp_stage4_eligible_rows
            ),
            use_container_width=True,
            hide_index=True,
        )

    else:

        st.info(
            "No Stage 4 intervention candidates "
            "were identified for the current project."
        )


elif _cp_stage4_stage3_ready:

    st.info(
        "Stage 4 is ready. Click 'Run Stage 4' "
        "to screen the current Stage 3 zones."
    )


# ============================================================================

# ---------------------------------------------------------------------------
# Stage 5 visibility gate
# Stage 5 must not appear until Stage 4 has completed for the
# current project.
# ---------------------------------------------------------------------------

_cp_stage5_visibility_stage4 = st.session_state.get(
    "stage4_results"
)

_cp_stage5_visibility_stage4_hash = st.session_state.get(
    "stage4_project_hash"
)

_cp_stage5_visibility_project_hash = st.session_state.get(
    "stage2_project_hash"
)

_cp_stage5_visibility_ready = (
    isinstance(
        _cp_stage5_visibility_stage4,
        dict,
    )
    and _cp_stage5_visibility_stage4_hash
    and _cp_stage5_visibility_stage4_hash
    == _cp_stage5_visibility_project_hash
)

if not _cp_stage5_visibility_ready:
    st.stop()

# COOLPLAN_STAGE5_CATEGORICAL_RAG_AI_V1
# Workflow 09 — Stage 5 Intervention Assessment + AI Proposal + Report
#
# IMPORTANT:
# - Uses the existing Stage 4 result.
# - Does not rerun Stage 1–4.
# - Does not modify environmental source values.
# - Uses the original categorical project inputs.
# - Deterministic assessment remains authoritative.
# - Existing Workflow 09 RAG + AI Agent is used.
# - AI does not approve feasibility or calculate ISS.
# ============================================================================

try:

    from workflow09.stage5_runtime import (
        run_stage5,
    )

    _cp_stage5_available = True
    _cp_stage5_import_error = ""

except Exception as _cp_stage5_import_exception:

    _cp_stage5_available = False
    _cp_stage5_import_error = str(
        _cp_stage5_import_exception
    )


# ---------------------------------------------------------------------------
# Stage 5 runtime state
# ---------------------------------------------------------------------------

_cp_stage5_saved = st.session_state.get(
    "stage5_results"
)

_cp_stage5_stage4 = st.session_state.get(
    "stage4_results"
)

_cp_stage5_current_project_hash = st.session_state.get(
    "stage2_project_hash"
)

_cp_stage5_stage4_hash = st.session_state.get(
    "stage4_project_hash"
)


# ---------------------------------------------------------------------------
# Stage 5 UI
# ---------------------------------------------------------------------------

st.markdown("---")

st.markdown(
    "## Stage 5 — Intervention Planning"
)

st.caption(
    "Assess the interventions identified by Stage 4 using the "
    "project's categorical design constraints, then generate "
    "evidence-grounded AI intervention proposals."
)


if not _cp_stage5_available:

    st.error(
        "Stage 5 is unavailable because the Workflow 09 "
        "Stage 5 runtime could not be imported."
    )

    st.code(
        _cp_stage5_import_error
    )


elif not isinstance(
    _cp_stage5_stage4,
    dict,
):

    st.info(
        "Run Stage 4 first. Stage 5 uses the current "
        "Stage 4 eligible zones."
    )


elif (
    _cp_stage5_stage4_hash
    != _cp_stage5_current_project_hash
):

    st.warning(
        "Stage 5 is waiting for the Stage 4 results. "
        "Run Stage 4 again for the current project."
    )


else:

    _cp_stage5_zones = (
        _cp_stage5_stage4.get(
            "zones",
            [],
        )
    )

    _cp_stage5_eligible_zones = [
        zone
        for zone in _cp_stage5_zones
        if isinstance(zone, dict)
        and zone.get("status") == "ELIGIBLE"
    ]


    if not _cp_stage5_eligible_zones:

        st.info(
            "No Stage 4 eligible zones are available "
            "to plan interventions for the identified priority zones."
        )


    else:

        # ---------------------------------------------------------------
        # Existing categorical project inputs
        # ---------------------------------------------------------------

        st.markdown(
            "### Project Design Constraints"
        )

        st.info(
            "**What to do:** Select the option that best describes your "
            "project for each item below. CoolPlan AI will use these "
            "choices together with the Stage 4 priority zones to plan "
            "practical cooling interventions for each identified zone."
        )

        _cp_stage5_col1, _cp_stage5_col2 = st.columns(2)


        with _cp_stage5_col1:

            st.caption(
                "How much suitable space is available for an intervention?"
            )
            _cp_stage5_available_space = st.selectbox(
                "Available Space",
                [
                    "Available",
                    "Limited",
                    "Not available",
                ],
                index=0,
                key="cp_stage5_available_space_categorical",
            )


            st.caption(
                "How easily can water be provided for interventions that need it?"
            )
            _cp_stage5_water_availability = st.selectbox(
                "Water Availability",
                [
                    "Adequate",
                    "Limited",
                    "Not available",
                ],
                index=0,
                key="cp_stage5_water_availability_categorical",
            )


        with _cp_stage5_col2:

            st.caption(
                "What level of budget is available for implementation?"
            )
            _cp_stage5_project_budget = st.selectbox(
                "Project Budget",
                [
                    "Low",
                    "Moderate",
                    "High",
                ],
                index=1,
                key="cp_stage5_project_budget_categorical",
            )


            st.caption(
                "What level of ongoing maintenance can the project support?"
            )
            _cp_stage5_maintenance_capacity = st.selectbox(
                "Maintenance Capacity",
                [
                    "Low",
                    "Moderate",
                    "High",
                ],
                index=1,
                key="cp_stage5_maintenance_capacity_categorical",
            )


        _cp_stage5_design_selections = {
            "available_space": (
                _cp_stage5_available_space
            ),
            "water_availability": (
                _cp_stage5_water_availability
            ),
            "project_budget": (
                _cp_stage5_project_budget
            ),
            "maintenance_capacity": (
                _cp_stage5_maintenance_capacity
            ),
        }


        st.markdown(
            "### Selected Project Constraints"
        )

        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Input": "Available Space",
                        "Selection": (
                            _cp_stage5_available_space
                        ),
                    },
                    {
                        "Input": "Water Availability",
                        "Selection": (
                            _cp_stage5_water_availability
                        ),
                    },
                    {
                        "Input": "Project Budget",
                        "Selection": (
                            _cp_stage5_project_budget
                        ),
                    },
                    {
                        "Input": "Maintenance Capacity",
                        "Selection": (
                            _cp_stage5_maintenance_capacity
                        ),
                    },
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )


        # ---------------------------------------------------------------
        # Run Stage 5
        # ---------------------------------------------------------------

        if st.button(
            "Run Stage 5 Intervention Planning",
            type="primary",
            key="cp_stage5_run_categorical",
        ):

            try:

                with st.spinner(
                    "Running deterministic assessment, "
                    "RAG retrieval, and AI intervention proposal..."
                ):

                    _cp_stage5_result = run_stage5(
                        stage4_results=(
                            _cp_stage5_stage4
                        ),
                        design_selections=(
                            _cp_stage5_design_selections
                        ),
rag_dir=(
    Path(__file__).resolve().parent
    / "workflow09"
    / "rag_runtime"
),
                        top_k=3,
                        max_output_tokens=500,
                    )


                # -------------------------------------------------------
                # Save ONLY Stage 5 result.
                # Stage 4 remains untouched.
                # -------------------------------------------------------

                st.session_state[
                    "stage5_project_hash"
                ] = (
                    _cp_stage5_current_project_hash
                )

                st.session_state[
                    "stage5_results"
                ] = {
                    "project_hash": (
                        _cp_stage5_current_project_hash
                    ),
                    "design_selections": (
                        _cp_stage5_result.get(
                            "design_selections",
                            {},
                        )
                    ),
                    "eligible_zone_count": (
                        _cp_stage5_result.get(
                            "eligible_zone_count",
                            0,
                        )
                    ),
                    "task_count": (
                        _cp_stage5_result.get(
                            "task_count",
                            0,
                        )
                    ),
                    "queue": (
                        _cp_stage5_result.get(
                            "queue",
                            {},
                        )
                    ),
                    "results": (
                        _cp_stage5_result.get(
                            "results",
                            [],
                        )
                    ),
                    "report": (
                        _cp_stage5_result.get(
                            "report",
                            "",
                        )
                    ),
                }


                # -------------------------------------------------------
                # Save report and raw result in the working folder.
                # -------------------------------------------------------

_cp_stage5_output_dir = (
    Path(
        "/tmp/Integrated_App/"
        "stage5_reports"
    )
)
                _cp_stage5_output_dir.mkdir(
                    parents=True,
                    exist_ok=True,
                )


                _cp_stage5_report_path = (
                    _cp_stage5_output_dir
                    / "CoolPlan_Stage5_Intervention_Report.md"
                )

                _cp_stage5_report_path.write_text(
                    _cp_stage5_result.get(
                        "report",
                        "",
                    ),
                    encoding="utf-8",
                )


                _cp_stage5_json_path = (
                    _cp_stage5_output_dir
                    / "CoolPlan_Stage5_Results.json"
                )

                _cp_stage5_json_path.write_text(
                    json.dumps(
                        _cp_stage5_result,
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )


                st.success(
                    "Stage 5 intervention planning completed."
                )

                st.info(
                    "Stage 4 remains unchanged. "
                    "Deterministic assessment and AI proposal "
                    "results are stored separately."
                )


            except Exception as _cp_stage5_error:

                st.error(
                    "Stage 5 intervention planning failed."
                )

                st.exception(
                    _cp_stage5_error
                )


        # -------------------------------------------------------------------
        # Display saved Stage 5 result
        # -------------------------------------------------------------------

        _cp_stage5_saved = st.session_state.get(
            "stage5_results"
        )


        if (
            isinstance(
                _cp_stage5_saved,
                dict,
            )
            and
            st.session_state.get(
                "stage5_project_hash"
            )
            == _cp_stage5_current_project_hash
        ):

            st.markdown(
                "### Stage 5 Results"
            )


            st.markdown(
                "#### Project Constraints"
            )

            st.json(
                _cp_stage5_saved.get(
                    "design_selections",
                    {},
                )
            )


            # Assessment Summary intentionally hidden from the main UI.

            _cp_stage5_result_rows = []


            for _cp_stage5_item in (
                _cp_stage5_saved.get(
                    "results",
                    [],
                )
            ):

                _cp_stage5_assessment = (
                    _cp_stage5_item.get(
                        "assessment",
                        {},
                    )
                )

                _cp_stage5_ai = (
                    _cp_stage5_item.get(
                        "ai_proposal",
                        {},
                    )
                )

                _cp_stage5_result_rows.append(
                    {
                        "Zone": (
                            _cp_stage5_item.get(
                                "zone_id",
                                "",
                            )
                        ),
                        "Intervention": (
                            _cp_stage5_item.get(
                                "intervention",
                                "",
                            )
                        ),
                        "Deterministic Assessment": (
                            _cp_stage5_assessment.get(
                                "status",
                                "",
                            )
                        ),
                        "AI Proposal": (
                            _cp_stage5_ai.get(
                                "status",
                                "",
                            )
                        ),
                    }
                )


            if _cp_stage5_result_rows:

                st.dataframe(
                    pd.DataFrame(
                        _cp_stage5_result_rows
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            else:

                st.info(
                    "No Stage 5 intervention results "
                    "were generated."
                )


            # -----------------------------------------------------------
            # Detailed AI proposals
            # -----------------------------------------------------------

            # Detailed AI Proposed Interventions intentionally hidden.


            for _cp_stage5_index, _cp_stage5_item in enumerate(
                _cp_stage5_saved.get(
                    "results",
                    [],
                ),
                start=1,
            ):

                _cp_stage5_zone_id = (
                    _cp_stage5_item.get(
                        "zone_id",
                        "",
                    )
                )

                _cp_stage5_intervention = (
                    _cp_stage5_item.get(
                        "intervention",
                        "",
                    )
                )

                _cp_stage5_ai = (
                    _cp_stage5_item.get(
                        "ai_proposal",
                        {},
                    )
                )

                with st.expander(
                    f"{_cp_stage5_zone_id} — "
                    f"{_cp_stage5_intervention}",
                    expanded=(
                        _cp_stage5_index <= 3
                    ),
                ):

                    st.markdown(
                        "**AI Status**"
                    )

                    st.write(
                        _cp_stage5_ai.get(
                            "status",
                            "UNKNOWN",
                        )
                    )


                    _cp_stage5_proposals = (
                        _cp_stage5_ai.get(
                            "proposals",
                            [],
                        )
                    )


                    if _cp_stage5_proposals:

                        for _cp_stage5_proposal in (
                            _cp_stage5_proposals
                        ):

                            st.markdown(
                                "**Proposed Intervention:** "
                                + str(
                                    _cp_stage5_proposal.get(
                                        "intervention",
                                        _cp_stage5_intervention,
                                    )
                                )
                            )

                            st.markdown(
                                "**Rationale:** "
                                + str(
                                    _cp_stage5_proposal.get(
                                        "rationale",
                                        "",
                                    )
                                )
                            )


                            _cp_stage5_evidence_ids = (
                                _cp_stage5_proposal.get(
                                    "evidence_chunk_ids",
                                    [],
                                )
                            )

                            if _cp_stage5_evidence_ids:

                                st.caption(
                                    "RAG evidence chunks: "
                                    + ", ".join(
                                        map(
                                            str,
                                            _cp_stage5_evidence_ids,
                                        )
                                    )
                                )

                    else:

                        st.info(
                            "No AI proposal was returned."
                        )


                    # ---------------------------------------------------
                    # Deterministic assessment
                    # ---------------------------------------------------

                    # Detailed deterministic assessment intentionally hidden.


            # -----------------------------------------------------------
            # Final intervention report
            # -----------------------------------------------------------

            st.markdown(
                "#### Intervention Report"
            )

            _cp_stage5_report = (
                _cp_stage5_saved.get(
                    "report",
                    "",
                )
            )


            if _cp_stage5_report:

                st.markdown(
                    _cp_stage5_report
                )

                st.download_button(
                    label="Download Stage 5 Intervention Report",
                    data=_cp_stage5_report,
                    file_name=(
                        "CoolPlan_Stage5_"
                        "Intervention_Report.md"
                    ),
                    mime="text/markdown",
                    key="cp_stage5_download_report",
                )

            else:

                st.info(
                    "No intervention report is available."
                )


            st.caption(
                "Deterministic assessment remains authoritative. "
                "AI proposals are evidence-grounded recommendations "
                "and do not replace verified hard-constraint assessment."
            )


# ============================================================================
# END COOLPLAN_STAGE5_CATEGORICAL_RAG_AI_V1
# ============================================================================
# ============================================================================
