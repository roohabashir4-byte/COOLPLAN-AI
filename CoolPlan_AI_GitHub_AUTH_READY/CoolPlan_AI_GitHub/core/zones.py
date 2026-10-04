
import ee
import pandas as pd


def classify_zone_hps(hps):
    if hps is None:
        return "No Data"

    if hps <= 25:
        return "Low"

    elif hps <= 50:
        return "Moderate"

    elif hps <= 75:
        return "High"

    else:
        return "Very High"


def create_zone_grid(study_area, cell_size_m=100):
    """
    Create a regular grid over the environmental study area.

    Default:
        100 m × 100 m cells
    """

    projection = ee.Projection("EPSG:3857").atScale(
        cell_size_m
    )

    grid = study_area.bounds().coveringGrid(
        projection
    )

    grid = grid.filterBounds(study_area)

    return grid


def calculate_zone_values(
    grid,
    environmental_result
):

    lst = environmental_result["lst_composite"]
    ndvi = environmental_result["ndvi_composite"]
    ndbi = environmental_result["ndbi_composite"]

    vegetation_deficit = (
        environmental_result["vegetation_deficit"]
    )

    hps = environmental_result["heat_priority"]

    environmental_image = ee.Image.cat([
        lst.rename("LST_C"),
        ndvi.rename("NDVI"),
        ndbi.rename("NDBI"),
        vegetation_deficit.rename(
            "VEGETATION_DEFICIT"
        ),
        hps.rename("HPS")
    ])

    def process_zone(feature):

        geometry = feature.geometry()

        values = environmental_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=30,
            bestEffort=True,
            maxPixels=1e6
        )

        return feature.set({
            "LST_C": values.get("LST_C"),
            "NDVI": values.get("NDVI"),
            "NDBI": values.get("NDBI"),
            "VEGETATION_DEFICIT":
                values.get("VEGETATION_DEFICIT"),
            "HPS": values.get("HPS")
        })

    return grid.map(process_zone)


def zones_to_dataframe(zones):

    features = zones.getInfo()["features"]

    records = []

    for index, feature in enumerate(features):

        properties = feature["properties"]

        lst = properties.get("LST_C")
        ndvi = properties.get("NDVI")
        ndbi = properties.get("NDBI")
        vd = properties.get("VEGETATION_DEFICIT")
        hps = properties.get("HPS")

        if hps is not None:
            hps_class = classify_zone_hps(
                float(hps)
            )
        else:
            hps_class = "No Data"

        records.append({
            "zone_id": f"Z_{index + 1:03d}",
            "LST_C": lst,
            "NDVI": ndvi,
            "NDBI": ndbi,
            "vegetation_deficit": vd,
            "HPS": hps,
            "HPS_class": hps_class,
            "dominant_feature": None,
            "site_conditions": None,
            "activity_exposure": None
        })

    return pd.DataFrame(records)
