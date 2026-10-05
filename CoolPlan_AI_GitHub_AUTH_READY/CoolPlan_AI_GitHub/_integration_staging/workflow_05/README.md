# CoolPlan AI — Workflow 05 (Colab integration test build)

This package preserves the uploaded tested Workflow 05 core modules and adds a
Streamlit interface with a custom Leaflet polygon-drag component.

## In Colab
1. Upload this ZIP.
2. Extract it to `/content/CoolPlan_AI_Workflow_05_Streamlit`.
3. Ensure your survey DXF is available at `/content/NAROWAL SURVEY PLAN FINAL.dxf`,
   or upload it in the app.
4. Install requirements:
   `%pip install -q -r /content/CoolPlan_AI_Workflow_05_Streamlit/requirements.txt`
5. Run:
   `!streamlit run /content/CoolPlan_AI_Workflow_05_Streamlit/app.py --server.port 8501 --server.headless true`
6. In another cell, run your existing Cloudflare tunnel:
   `!/content/cloudflared tunnel --url http://localhost:8501`

## What to test
- Survey inspection appears.
- Boundary loads from the BOUNDARY layer.
- Drag the cyan polygon itself; it should move as a whole.
- Confirm and download GeoJSON.
- Verify reset, scale, and rotation controls.

This is a test build, not a finalized workflow. The initial map location and
0.3048 metres/CAD-unit scale are assumptions and must be checked against survey
control before engineering use. Internet access is needed for Leaflet and tiles.
