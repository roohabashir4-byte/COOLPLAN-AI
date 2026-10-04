"""
CoolPlan AI — Workflow 00: Location Engine

Deployment-ready, UI-independent location state and confirmation logic.

The Streamlit UI should call this module rather than duplicating location
state logic. No project coordinates are hard-coded in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any


@dataclass
class Location:
    """A candidate, user-selected, or confirmed project location."""

    name: str
    address: str
    lat: float
    lon: float
    source: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "address": self.address,
            "lat": float(self.lat),
            "lon": float(self.lon),
            "source": self.source,
        }


class LocationEngine:
    """
    Reusable Workflow 00 location engine.

    State flow:
        candidate
            -> confirmed candidate

        candidate
            -> manual selection
            -> confirmed manual location

        manual selection
            -> select again
            -> new manual selection
    """

    def __init__(self) -> None:
        self.candidate_location: Optional[Location] = None
        self.manual_selected_location: Optional[Location] = None
        self.confirmed_location: Optional[Location] = None
        self.confirmation_type: Optional[str] = None
        self.manual_mode: bool = False

    def set_candidate(
        self,
        name: str,
        address: str,
        lat: float,
        lon: float,
        source: str,
    ) -> Location:
        """Set a geocoding/place-search candidate."""
        self.candidate_location = Location(
            name=name,
            address=address,
            lat=float(lat),
            lon=float(lon),
            source=source,
        )
        self.manual_selected_location = None
        self.confirmed_location = None
        self.confirmation_type = None
        self.manual_mode = False
        return self.candidate_location

    def start_manual_selection(self) -> None:
        """Enter manual-selection mode while retaining the candidate."""
        self.manual_mode = True
        self.manual_selected_location = None
        self.confirmed_location = None
        self.confirmation_type = None

    def select_manual_location(
        self,
        address: str,
        lat: float,
        lon: float,
    ) -> Location:
        """Store a location selected by the user on the map."""
        if not self.manual_mode:
            raise RuntimeError(
                "Manual selection is not active."
            )

        self.manual_selected_location = Location(
            name="User-selected project location",
            address=address,
            lat=float(lat),
            lon=float(lon),
            source="User selected on map",
        )
        self.confirmed_location = None
        self.confirmation_type = None
        return self.manual_selected_location

    def select_again(self) -> None:
        """Remove the current manual selection but retain the candidate."""
        self.manual_selected_location = None
        self.confirmed_location = None
        self.confirmation_type = None
        self.manual_mode = True

    def confirm_candidate(self) -> Location:
        """Confirm the candidate location."""
        if self.candidate_location is None:
            raise RuntimeError(
                "No candidate location is available."
            )

        self.confirmed_location = self.candidate_location
        self.confirmation_type = "candidate"
        self.manual_mode = False
        return self.confirmed_location

    def confirm_manual(self) -> Location:
        """Confirm the user's manually selected location."""
        if self.manual_selected_location is None:
            raise RuntimeError(
                "No manual location has been selected."
            )

        self.confirmed_location = self.manual_selected_location
        self.confirmation_type = "manual"
        self.manual_mode = False
        return self.confirmed_location

    def reset(self) -> None:
        """Reset the complete location workflow."""
        self.candidate_location = None
        self.manual_selected_location = None
        self.confirmed_location = None
        self.confirmation_type = None
        self.manual_mode = False

    def get_confirmed_coordinates(self) -> Dict[str, float]:
        """
        Return only confirmed coordinates.

        This is the interface Workflow 01 will use.
        """
        if self.confirmed_location is None:
            raise RuntimeError(
                "Project location has not been confirmed."
            )

        return {
            "latitude": float(self.confirmed_location.lat),
            "longitude": float(self.confirmed_location.lon),
        }

    def get_confirmed_location(self) -> Dict[str, Any]:
        """Return the complete confirmed location."""
        if self.confirmed_location is None:
            raise RuntimeError(
                "Project location has not been confirmed."
            )

        return self.confirmed_location.as_dict()
