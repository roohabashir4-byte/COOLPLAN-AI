import sys
from pathlib import Path
import ezdxf

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.cad import analyze_cad_boundary


def test_cad_boundary():

    dxf_files = list(Path("/content").glob("*.dxf"))

    if not dxf_files:
        print("No DXF available for standalone test.")
        return

    doc = ezdxf.readfile(str(dxf_files[0]))
    msp = doc.modelspace()

    result = analyze_cad_boundary(msp)

    assert result["boundary_entity_count"] == 34
    assert result["component_count"] == 5
    assert result["status"] == "BOUNDARY_REQUIRES_CONFIRMATION"

    print("✓ CAD boundary analysis passed")
    print("✓ 34 boundary entities detected")
    print("✓ 5 components detected")
    print("✓ Incomplete boundary correctly detected")
    print("✓ WORKFLOW 04 TEST PASSED")


if __name__ == "__main__":
    test_cad_boundary()
