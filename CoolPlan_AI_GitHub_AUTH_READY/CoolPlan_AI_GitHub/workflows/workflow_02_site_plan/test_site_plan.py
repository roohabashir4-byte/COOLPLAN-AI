"""
CoolPlan AI — Independent Test for Workflow 2
Site Plan Processing & User Verification

Colab usage:
1. Install dependencies.
2. Set GROQ_API_KEY in Colab Secrets.
3. Upload any test PDF.
4. Change TEST_FILE to the uploaded filename.
5. Run this file.
"""

import os
import sys

from pathlib import Path

# Make the package importable when this script is run directly.
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.site_plan import analyze_site_plan, validate_confirmed_composition


TEST_FILE = "/content/cool plan ai test project.pdf"


def main():
    if not Path(TEST_FILE).exists():
        raise FileNotFoundError(
            f"Test file not found: {TEST_FILE}\n"
            "Upload a PDF and update TEST_FILE if necessary."
        )

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not available. Add it to your Colab Secrets."
        )

    print("CoolPlan AI — Workflow 2 Independent Test")
    print("=" * 48)

    result = analyze_site_plan(
        file_path=TEST_FILE,
        groq_api_key=api_key,
    )

    print(f"✓ File: {result['file_name']}")
    print(f"✓ Vision model: {result['vision_model']}")
    print(f"✓ Text extracted: {len(result['extracted_text'])} characters")
    print(f"✓ Labels detected: {len(result['detected_labels'])} groups")
    print("\nAI ESTIMATE:")
    print("-" * 48)

    for item in result["estimated_composition"]:
        print(
            f"{item['category']:<28} "
            f"{item['percentage']:>6.2f}%  "
            f"{item['confidence']:<7}  "
            f"{item['reason']}"
        )

    print("-" * 48)
    print(f"Total: {result['total_percentage']:.2f}%")
    print(f"Verification required: {result['verification_required']}")

    # Independent validation test using the AI estimate.
    confirmed = validate_confirmed_composition(
        result["estimated_composition"]
    )

    print("\n✓ Composition validation passed.")
    print(f"✓ Confirmed total: {confirmed['total_percentage']:.2f}%")
    print("\nWorkflow 2 test completed successfully.")


if __name__ == "__main__":
    main()
