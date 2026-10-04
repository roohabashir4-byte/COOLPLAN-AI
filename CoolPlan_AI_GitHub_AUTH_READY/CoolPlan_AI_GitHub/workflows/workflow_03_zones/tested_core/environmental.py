from datetime import datetime, timedelta
import ee

PROJECT_ID = "cool-plan-ai"

def initialize_earth_engine(project_id=PROJECT_ID):
    ee.Initialize(project=project_id)

def create_point(latitude, longitude):
    return ee.Geometry.Point([longitude, latitude])

def create_study_area(latitude, longitude, radius_m=500):
    point = create_point(latitude, longitude)
    return point, point.buffer(radius_m)

def get_analysis_dates(analysis_days=365, end_date=None):
    end_date = end_date or datetime.now()
    start_date = end_date - timedelta(days=analysis_days)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

def mask_landsat_quality(image):
    qa = image.select("QA_PIXEL")
    mask = (
        qa.bitwiseAnd(1 << 4).eq(0)
        .And(qa.bitwiseAnd(1 << 5).eq(0)
        .And(qa.bitwiseAnd(1 << 3).eq(0))
        .And(qa.bitwiseAnd(1 << 2).eq(0)))
    )
    return image.updateMask(mask)

def calculate_lst(image):
    lst = (image.select("ST_B10")
           .multiply(0.00341802)
           .add(149.0)
           .subtract(273.15)
           .rename("LST_C"))
    return image.addBands(lst)

def mask_sentinel_quality(image):
    scl = image.select("SCL")
    mask = (scl.neq(3).And(scl.neq(8))
            .And(scl.neq(9)).And(scl.neq(10))
            .And(scl.neq(11)))
    return image.updateMask(mask)

def calculate_ndvi(image):
    return image.addBands(
        image.normalizedDifference(["B8", "B4"]).rename("NDVI")
    )

def calculate_ndbi(image):
    return image.addBands(
        image.normalizedDifference(["B11", "B8"]).rename("NDBI")
    )

def normalize_image(image, minimum, maximum, name):
    denominator = maximum.subtract(minimum).max(ee.Number(1e-9))
    return image.subtract(minimum).divide(denominator).multiply(100).rename(name)

def classify_hps(value):
    value = float(value)
    if value <= 25:
        return "Low"
    if value <= 50:
        return "Moderate"
    if value <= 75:
        return "High"
    return "Very High"

def run_environmental_analysis(latitude, longitude,
                               radius_m=500, analysis_days=365):
    point, study_area = create_study_area(
        latitude, longitude, radius_m
    )
    start_date, end_date = get_analysis_dates(analysis_days)

    landsat = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
               .filterBounds(study_area)
               .filterDate(start_date, end_date))
    usable_landsat = landsat.map(mask_landsat_quality)
    lst = (usable_landsat.map(calculate_lst)
           .select("LST_C").median())

    sentinel = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(study_area)
                .filterDate(start_date, end_date))
    usable_sentinel = sentinel.map(mask_sentinel_quality)
    ndvi = (usable_sentinel.map(calculate_ndvi)
            .select("NDVI").median())
    ndbi = (usable_sentinel.map(calculate_ndbi)
            .select("NDBI").median())

    def stats(image, band, scale):
        s = image.reduceRegion(
            reducer=ee.Reducer.minMax(),
            geometry=study_area,
            scale=scale,
            maxPixels=1e6
        )
        return ee.Number(s.get(band + "_min")), ee.Number(s.get(band + "_max"))

    lst_min, lst_max = stats(lst, "LST_C", 30)
    ndvi_min, ndvi_max = stats(ndvi, "NDVI", 10)
    ndbi_min, ndbi_max = stats(ndbi, "NDBI", 20)

    lst_n = normalize_image(lst, lst_min, lst_max, "LST_N")
    ndvi_n = normalize_image(ndvi, ndvi_min, ndvi_max, "NDVI_N")
    vd_n = ee.Image(100).subtract(ndvi_n).rename("VD_N")
    ndbi_n = normalize_image(ndbi, ndbi_min, ndbi_max, "NDBI_N")

    hps = (lst_n.multiply(0.50)
           .add(vd_n.multiply(0.25))
           .add(ndbi_n.multiply(0.25))
           .rename("HPS"))

    point_value = hps.reduceRegion(
        ee.Reducer.mean(), point, 30, maxPixels=1e6
    ).get("HPS").getInfo()

    hps_range = hps.reduceRegion(
        ee.Reducer.minMax(), study_area, 30, maxPixels=1e6
    ).getInfo()

    return {
        "point": point,
        "study_area": study_area,
        "start_date": start_date,
        "end_date": end_date,
        "lst_composite": lst,
        "ndvi_composite": ndvi,
        "ndbi_composite": ndbi,
        "lst_normalized": lst_n,
        "ndvi_normalized": ndvi_n,
        "vegetation_deficit": vd_n,
        "ndbi_normalized": ndbi_n,
        "heat_priority": hps,
        "summary": {
            "landsat_images": landsat.size().getInfo(),
            "usable_landsat_images": usable_landsat.size().getInfo(),
            "sentinel_images": sentinel.size().getInfo(),
            "usable_sentinel_images": usable_sentinel.size().getInfo(),
            "hps": point_value,
            "hps_min": hps_range["HPS_min"],
            "hps_max": hps_range["HPS_max"],
            "hps_class": classify_hps(point_value),
        },
    }
