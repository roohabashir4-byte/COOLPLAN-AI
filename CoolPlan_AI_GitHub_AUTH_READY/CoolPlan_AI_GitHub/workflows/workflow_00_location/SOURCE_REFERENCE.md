# Workflow 00 Source Reference

The tested Streamlit file supplied by the user was:

`coolplan_location_selector.py`

The reusable `core/location.py` was extracted from the tested behavior:
- candidate location state
- manual selection
- select again
- candidate confirmation
- manual confirmation
- confirmed-coordinate interface

The reusable module deliberately contains no hard-coded project coordinates.
The Streamlit UI remains responsible for displaying the map and markers.
