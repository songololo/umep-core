# -*- coding: utf-8 -*-

"""
/***************************************************************************
 ProcessingUMEP
                                 A QGIS plugin
 UMEP for processing toolbox
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2020-04-02
        copyright            : (C) 2020 by Fredrik Lindberg
        email                : fredrikl@gvc.gu.se
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/

"SOLWEIG (v2022a) is a model which can be used to estimate spatial variations of 3D radiation fluxes and "
"mean radiant temperature (Tmrt) in complex urban settings. The SOLWEIG model follows the same "
"approach commonly adopted to observe Tmrt, with shortwave and longwave radiation fluxes from  "
"six directions being individually calculated to derive Tmrt. The model requires a limited number "
"of inputs, such as direct, diffuse and global shortwave radiation, air temperature, relative "
"humidity, urban geometry and geographical information (latitude, longitude and elevation). "
"Additional vegetation and ground cover information can also be used to imporove the estimation of Tmrt.\n"
"\n"
"Tools to generate sky view factors, wall height and aspect etc. is available in the pre-processing past in UMEP\n"
"\n"
"------------\n"
"\n"
"Full manual available via the <b>Help</b>-button."
"https://umep-docs.readthedocs.io/en/latest/processor/Outdoor%20Thermal%20Comfort%20SOLWEIG.html"
"""

__author__ = "Fredrik Lindberg"
__date__ = "2020-04-02"
__copyright__ = "(C) 2020 by Fredrik Lindberg"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"

import random
import string
import zipfile
from pathlib import Path
from shutil import rmtree

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyproj
from pvlib.iotools import read_epw
from rasterio.transform import rowcol, xy
from tqdm import tqdm

from umep import common
from umep.functions.SOLWEIGpython import PET_calculations as p
from umep.functions.SOLWEIGpython import Solweig_2022a_calc_forprocessing as so
from umep.functions.SOLWEIGpython import UTCI_calculations as utci
from umep.functions.SOLWEIGpython import WriteMetadataSOLWEIG
from umep.util.SEBESOLWEIGCommonFiles.clearnessindex_2013b import clearnessindex_2013b
from umep.util.SEBESOLWEIGCommonFiles.Solweig_v2015_metdata_noload import (
    Solweig_2015a_metdata_noload,
)


def generate_solweig(
    dsm_path: str,
    wall_ht_path: str,
    wall_aspect_path: str,
    svf_path: str,
    epw_path: str,
    bbox: list[int, int, int, int],
    out_dir: str,
    start_date_Ymd: str,  # %Y-%m-%d"
    end_date_Ymd: str,  # %Y-%m-%d"
    hours: list[int] = list(range(1, 25)),
    veg_dsm_path: str | None = None,
    pois_gdf: gpd.GeoDataFrame | None = None,
    trans_veg: float = 3,
    trunk_zone_ht_perc: float = 0.25,
    leaf_start: int = 97,
    leaf_end: int = 300,
    conif_trees: bool = False,
    albedo_bldg: float = 0.2,
    albedo_ground: float = 0.15,
    emmisiv_bldg: float = 0.9,
    emmisiv_ground: float = 0.95,
    body_shortwave_absorp: float = 0.7,
    body_longwave_absorp: float = 0.95,
    estimate_radiation_from_global=False,
):
    as_cylinder = 0
    standing = True
    if standing is True:
        Fside = 0.22
        Fup = 0.06
        height = 1.1  # METRES!
        Fcyl = 0.28
    else:
        Fside = 0.166666
        Fup = 0.166666
        height = 0.75  # METRES!
        Fcyl = 0.2
    # for PET
    age = 35
    activity = 80
    clothing = 0.9
    weight = 75
    pers_ht = 1.8  # METRES!  # different from above height param
    sex = "male"
    wind_sensor_ht = 10
    utc = 0

    # veg transmissivity as percentage
    if not trans_veg >= 0 and trans_veg <= 100:
        raise ValueError(
            "Vegetation transmissivity should be a number between 0 and 100"
        )
    trans_veg = trans_veg / 100.0

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out_path_str = str(out_path)

    Path.mkdir(out_path / "shadows", parents=True, exist_ok=True)
    Path.mkdir(out_path / "Tmrt", parents=True, exist_ok=True)

    dsm, dsm_transf, dsm_crs = common.load_raster(dsm_path, bbox)
    dsm_scale = 1 / dsm_transf.a
    dsm_height, dsm_width = dsm.shape  # y rows by x cols
    # y is flipped - so return max for lower row
    minx, miny = xy(dsm_transf, dsm.shape[0], 0)
    # Define the source and target CRS
    source_crs = pyproj.CRS(dsm_crs)
    target_crs = pyproj.CRS(4326)  # WGS 84
    # Create a transformer object
    transformer = pyproj.Transformer.from_crs(source_crs, target_crs, always_xy=True)
    # Perform the transformation
    lon, lat = transformer.transform(minx, miny)

    alt = np.median(dsm)
    if alt < 3:
        alt = 3

    trunkfile = 0
    trunkratio = 0

    if veg_dsm_path is not None:
        usevegdem = 1
        veg_dsm, veg_dsm_transf, veg_dsm_crs = common.load_raster(veg_dsm_path, bbox)
        veg_dsm_height, veg_dsm_width = veg_dsm.shape
        if not (veg_dsm_width == dsm_width) & (veg_dsm_height == dsm_height):
            raise ValueError(
                "Error in Vegetation Canopy DSM: All rasters must be of same extent and resolution"
            )
        trunkratio = trunk_zone_ht_perc / 100.0
        veg_dsm_2 = veg_dsm * trunkratio
        veg_dsm_2_height, veg_dsm_2_width = veg_dsm_2.shape
        if not (veg_dsm_2_width == dsm_width) & (veg_dsm_2_height == dsm_height):
            raise ValueError(
                "Error in Trunk Zone DSM: All rasters must be of same extent and resolution"
            )
        veg_dsm_2_path = None
    else:
        usevegdem = 0
        veg_dsm = np.zeros([dsm_height, dsm_width])
        veg_dsm_2 = np.zeros([dsm_height, dsm_width])
        veg_dsm_2_path = None

    # Land cover
    filePath_lc = None
    landcover = 0

    # DEM
    demforbuild = 0

    # SVFs
    temp_dir_name = "temp-" + "".join(
        random.choice(string.ascii_uppercase) for _ in range(8)
    )
    temp_dir = out_path_str + "/" + temp_dir_name
    zip = zipfile.ZipFile(svf_path, "r")
    zip.extractall(temp_dir)
    zip.close()

    svf, _, _ = common.load_raster(temp_dir + "/svf.tif", bbox)
    svfN, _, _ = common.load_raster(temp_dir + "/svfN.tif", bbox)
    svfS, _, _ = common.load_raster(temp_dir + "/svfS.tif", bbox)
    svfE, _, _ = common.load_raster(temp_dir + "/svfE.tif", bbox)
    svfW, _, _ = common.load_raster(temp_dir + "/svfW.tif", bbox)

    if usevegdem == 1:
        svfveg, _, _ = common.load_raster(temp_dir + "/svfveg.tif", bbox)
        svfNveg, _, _ = common.load_raster(temp_dir + "/svfNveg.tif", bbox)
        svfSveg, _, _ = common.load_raster(temp_dir + "/svfSveg.tif", bbox)
        svfEveg, _, _ = common.load_raster(temp_dir + "/svfEveg.tif", bbox)
        svfWveg, _, _ = common.load_raster(temp_dir + "/svfWveg.tif", bbox)
        svfaveg, _, _ = common.load_raster(temp_dir + "/svfaveg.tif", bbox)
        svfNaveg, _, _ = common.load_raster(temp_dir + "/svfNaveg.tif", bbox)
        svfSaveg, _, _ = common.load_raster(temp_dir + "/svfSaveg.tif", bbox)
        svfEaveg, _, _ = common.load_raster(temp_dir + "/svfEaveg.tif", bbox)
        svfWaveg, _, _ = common.load_raster(temp_dir + "/svfWaveg.tif", bbox)
    else:
        svfveg = np.ones((dsm_height, dsm_width))
        svfNveg = np.ones((dsm_height, dsm_width))
        svfSveg = np.ones((dsm_height, dsm_width))
        svfEveg = np.ones((dsm_height, dsm_width))
        svfWveg = np.ones((dsm_height, dsm_width))
        svfaveg = np.ones((dsm_height, dsm_width))
        svfNaveg = np.ones((dsm_height, dsm_width))
        svfSaveg = np.ones((dsm_height, dsm_width))
        svfEaveg = np.ones((dsm_height, dsm_width))
        svfWaveg = np.ones((dsm_height, dsm_width))

    svf_dsm_height, svf_dsm_width = svfveg.shape
    if not (svf_dsm_width == dsm_width) & (svf_dsm_height == dsm_height):
        raise ValueError(
            "Error in SVF: All rasters must be of same extent and resolution"
        )
    tmp = svf + svfveg - 1.0
    tmp[tmp < 0.0] = 0.0
    svfalfa = np.arcsin(np.exp((np.log((1.0 - tmp)) / 2.0)))

    wh_rast, wh_transf, wh_crs = common.load_raster(wall_ht_path, bbox)
    wh_height, wh_width = wh_rast.shape
    if not (wh_width == dsm_width) & (wh_height == dsm_height):
        raise ValueError(
            "Error in Wall height raster: All rasters must be of same extent and resolution"
        )
    wa_rast, wa_transf, wa_crs = common.load_raster(wall_aspect_path, bbox)
    wa_height, wa_width = wa_rast.shape
    if not (wa_width == dsm_width) & (wa_height == dsm_height):
        raise ValueError(
            "Error in Wall aspect raster: All rasters must be of same extent and resolution"
        )

    # Metdata
    metfileexist = 1
    epw_df, epw_info = read_epw(epw_path)
    # Filter by date range
    filtered_df = epw_df.loc[start_date_Ymd:end_date_Ymd]
    # Filter by hours
    filtered_df = filtered_df[filtered_df.index.hour.isin(hours)]
    # raise if empty
    if len(filtered_df) == 0:
        raise ValueError("No EPW dates intersect start and end dates and / or hours.")
    umep_df = pd.DataFrame(
        {
            "iy": filtered_df.index.year,
            "id": filtered_df.index.dayofyear,
            "it": filtered_df.index.hour,
            "imin": filtered_df.index.minute,
            "Q": -999,
            "QH": -999,
            "QE": -999,
            "Qs": -999,
            "Qf": -999,
            "Wind": filtered_df["wind_speed"],
            "RH": filtered_df["relative_humidity"],
            "Tair": filtered_df["temp_air"],
            "pres": filtered_df["atmospheric_pressure"],  # Pascal
            "rain": -999,
            "Kdown": filtered_df["ghi"],
            "snow": filtered_df["snow_depth"],
            "ldown": filtered_df["ghi_infrared"],
            "fcld": filtered_df["total_sky_cover"],
            "wuh": filtered_df["precipitable_water"],
            "xsmd": -999,
            "lai_hr": -999,
            "Kdiff": filtered_df["dhi"],
            "Kdir": filtered_df["dni"],
            "Wdir": filtered_df["wind_direction"],
        }
    )
    umep_df_filt = umep_df[(umep_df["Kdown"] < 0) & (umep_df["Kdown"] > 1300)]
    if len(umep_df_filt):
        print(umep_df_filt.head())
        raise ValueError(
            "Error: Kdown - beyond what is expected",
        )

    # use -999 for NaN to mesh with UMEP
    umep_df = umep_df.fillna(-999)

    print("Calculating sun positions for each time step")
    met_data = umep_df.to_numpy()
    location = {"longitude": lon, "latitude": lat, "altitude": alt}
    YYYY, altitude, azimuth, zen, jday, leafon, dectime, altmax = (
        Solweig_2015a_metdata_noload(met_data, location, utc)
    )

    # Creating vectors from meteorological input
    DOY = umep_df.loc[:, "id"].values
    hours = umep_df.loc[:, "it"].values
    minu = umep_df.loc[:, "imin"].values
    Ta = umep_df.loc[:, "Tair"].values
    RH = umep_df.loc[:, "RH"].values
    radG = umep_df.loc[:, "Kdown"].values
    radD = umep_df.loc[:, "Kdiff"].values
    radI = umep_df.loc[:, "Kdir"].values
    umep_df.loc[:, "pres"] /= 100  # convert from Pa to hPa
    P = umep_df.loc[:, "pres"].values
    Ws = umep_df.loc[:, "Wind"].values

    # %Radiative surface influence, Rule of thumb by Schmid et al. (1990).
    first = np.round(height)
    if first == 0.0:
        first = 1.0
    second = np.round((height * 10.0))  # NOTE: using 10 instead of 20

    if usevegdem == 1:
        # Conifer or deciduous
        if conif_trees is True:
            leafon = np.ones((1, DOY.shape[0]))
        else:
            leafon = np.zeros((1, DOY.shape[0]))
            if leaf_start > leaf_end:
                leaf_bool = (DOY > leaf_start) | (DOY < leaf_end)
            else:
                leaf_bool = (DOY > leaf_start) & (DOY < leaf_end)
            leafon[0, leaf_bool] = 1

        # % Vegetation transmittivity of shortwave radiation
        psi = leafon * trans_veg
        psi[leafon == 0] = 0.5
        # amaxvalue
        vegmax = veg_dsm.max()
        amaxvalue = dsm.max() - dsm.min()
        amaxvalue = np.maximum(amaxvalue, vegmax)

        # Elevation vegdsms if buildingDEM includes ground heights
        veg_dsm = veg_dsm + dsm
        veg_dsm[veg_dsm == dsm] = 0
        veg_dsm_2 = veg_dsm_2 + dsm
        veg_dsm_2[veg_dsm_2 == dsm] = 0

        # % Bush separation
        bush = np.logical_not((veg_dsm_2 * veg_dsm)) * veg_dsm

        svfbuveg = svf - (1.0 - svfveg) * (
            1.0 - trans_veg
        )  # % major bug fixed 20141203
    else:
        psi = leafon * 0.0 + 1.0
        svfbuveg = svf
        bush = np.zeros([dsm_height, dsm_width])
        amaxvalue = 0

    # %Initialization of maps
    Knight = np.zeros((dsm_height, dsm_width))
    Tgmap1 = np.zeros((dsm_height, dsm_width))
    Tgmap1E = np.zeros((dsm_height, dsm_width))
    Tgmap1S = np.zeros((dsm_height, dsm_width))
    Tgmap1W = np.zeros((dsm_height, dsm_width))
    Tgmap1N = np.zeros((dsm_height, dsm_width))

    buildings = dsm.copy()
    buildings[buildings < 2.0] = 1.0
    buildings[buildings >= 2.0] = 0.0

    # Import shadow matrices (Anisotropic sky)
    anisotropic_sky = 0
    diffsh = None
    shmat = None
    vegshmat = None
    vbshvegshmat = None
    asvf = None
    patch_option = 0

    # % Ts parameterisation maps
    TgK = Knight + 0.37
    Tstart = Knight - 3.41
    alb_grid = Knight + albedo_ground
    emis_grid = Knight + emmisiv_ground
    TgK_wall = 0.37
    Tstart_wall = -3.41
    TmaxLST = 15.0
    TmaxLST_wall = 15.0

    # Initialisation of time related variables
    if Ta.__len__() == 1:
        timestepdec = 0
    else:
        timestepdec = dectime[1] - dectime[0]
    timeadd = 0.0
    firstdaytime = 1.0

    WriteMetadataSOLWEIG.writeRunInfo(
        out_path_str,
        dsm_path,
        dsm_crs,
        usevegdem,
        veg_dsm_path,
        trunkfile,
        veg_dsm_2_path,
        lat,
        lon,
        utc,
        landcover,
        filePath_lc,
        metfileexist,
        epw_path,
        met_data,
        body_shortwave_absorp,
        body_longwave_absorp,
        albedo_bldg,
        albedo_ground,
        emmisiv_bldg,
        emmisiv_ground,
        estimate_radiation_from_global,
        trunkratio,
        trans_veg,
        dsm_height,
        dsm_width,
        int(standing),
        0,  # elvis
        as_cylinder,
        demforbuild,
        anisotropic_sky,
    )

    print(
        "Writing settings for this model run to specified output folder (Filename: RunInfoSOLWEIG_YYYY_DOY_HHMM.txt)"
    )

    #  If metfile starts at night
    CI = 1.0

    # Main function
    print("Executing main model")

    tmrtplot = np.zeros((dsm_height, dsm_width))
    TgOut1 = np.zeros((dsm_height, dsm_width))

    # Initiate array for I0 values
    if np.unique(DOY).shape[0] > 1:
        unique_days = np.unique(DOY)
        first_unique_day = DOY[DOY == unique_days[0]]
        I0_array = np.zeros((first_unique_day.shape[0]))
    else:
        first_unique_day = DOY.copy()
        I0_array = np.zeros((DOY.shape[0]))

    for i in tqdm(np.arange(0, Ta.__len__())):
        # Nocturnal cloudfraction from Offerle et al. 2003
        if (dectime[i] - np.floor(dectime[i])) == 0:
            daylines = np.where(np.floor(dectime) == dectime[i])
            if daylines.__len__() > 1:
                alt = altitude[0][daylines]
                alt2 = np.where(alt > 1)
                rise = alt2[0][0]
                [_, CI, _, _, _] = clearnessindex_2013b(
                    zen[0, i + rise + 1],
                    jday[0, i + rise + 1],
                    Ta[i + rise + 1],
                    RH[i + rise + 1] / 100.0,
                    radG[i + rise + 1],
                    location,
                    P[i + rise + 1],
                )  # i+rise+1 to match matlab code. correct?
                if (CI > 1.0) or (CI == np.inf):
                    CI = 1.0
            else:
                CI = 1.0

        # radI[i] = radI[i]/np.sin(altitude[0][i] * np.pi/180)

        (
            Tmrt,
            Kdown,
            Kup,
            Ldown,
            Lup,
            Tg,
            ea,
            esky,
            I0,
            CI,
            shadow,
            firstdaytime,
            timestepdec,
            timeadd,
            Tgmap1,
            Tgmap1E,
            Tgmap1S,
            Tgmap1W,
            Tgmap1N,
            Keast,
            Ksouth,
            Kwest,
            Knorth,
            Least,
            Lsouth,
            Lwest,
            Lnorth,
            KsideI,
            TgOut1,
            TgOut,
            radIout,
            radDout,
            Lside,
            Lsky_patch_characteristics,
            CI_Tg,
            CI_TgG,
            KsideD,
            dRad,
            Kside,
        ) = so.Solweig_2022a_calc(
            i,
            dsm,
            dsm_scale,
            dsm_height,
            dsm_width,
            svf,
            svfN,
            svfW,
            svfE,
            svfS,
            svfveg,
            svfNveg,
            svfEveg,
            svfSveg,
            svfWveg,
            svfaveg,
            svfEaveg,
            svfSaveg,
            svfWaveg,
            svfNaveg,
            veg_dsm,
            veg_dsm_2,
            albedo_bldg,
            body_shortwave_absorp,
            body_longwave_absorp,
            emmisiv_bldg,
            Fside,
            Fup,
            Fcyl,
            altitude[0][i],
            azimuth[0][i],
            zen[0][i],
            jday[0][i],
            usevegdem,
            int(estimate_radiation_from_global),
            buildings,
            location,
            psi[0][i],
            landcover,  # set to 0
            None,  # lcgrid
            dectime[i],
            altmax[0][i],
            wa_rast,
            wh_rast,
            as_cylinder,
            0,  # elvis
            Ta[i],
            RH[i],
            radG[i],
            radD[i],
            radI[i],
            P[i],
            amaxvalue,
            bush,
            None,  # Twater - used for landcover
            TgK,
            Tstart,
            alb_grid,
            emis_grid,
            TgK_wall,
            Tstart_wall,
            TmaxLST,
            TmaxLST_wall,
            first,
            second,
            svfalfa,
            svfbuveg,
            firstdaytime,
            timeadd,
            timestepdec,
            Tgmap1,
            Tgmap1E,
            Tgmap1S,
            Tgmap1W,
            Tgmap1N,
            CI,
            TgOut1,
            diffsh,
            shmat,
            vegshmat,
            vbshvegshmat,
            anisotropic_sky,
            asvf,
            patch_option,
        )

        if i < first_unique_day.shape[0]:
            I0_array[i] = I0

        tmrtplot = tmrtplot + Tmrt

        if altitude[0][i] > 0:
            w = "D"
        else:
            w = "N"

        if hours[i] < 10:
            XH = "0"
        else:
            XH = ""

        if minu[i] < 10:
            XM = "0"
        else:
            XM = ""

        time_code = (
            str(int(YYYY[0, i]))
            + "_"
            + str(int(DOY[i]))
            + "_"
            + XH
            + str(int(hours[i]))
            + XM
            + str(int(minu[i]))
            + w
        )

        if pois_gdf is not None:
            for idx, row in pois_gdf.iterrows():
                centroid = row["geometry"].centroid
                row_idx, col_idx = rowcol(dsm_transf, centroid.x, centroid.y)
                row_idx = int(row_idx)
                col_idx = int(col_idx)
                pois_gdf.at[idx, "yyyy"] = YYYY[0][i]
                pois_gdf.at[idx, "id"] = jday[0][i]
                pois_gdf.at[idx, "it"] = hours[i]
                pois_gdf.at[idx, "imin"] = minu[i]
                pois_gdf.at[idx, "dectime"] = dectime[i]
                pois_gdf.at[idx, "altitude"] = altitude[0][i]
                pois_gdf.at[idx, "azimuth"] = azimuth[0][i]
                pois_gdf.at[idx, "kdir"] = radIout
                pois_gdf.at[idx, "kdiff"] = radDout
                pois_gdf.at[idx, "kglobal"] = radG[i]
                pois_gdf.at[idx, "kdown"] = Kdown[row_idx, col_idx]
                pois_gdf.at[idx, "kup"] = Kup[row_idx, col_idx]
                pois_gdf.at[idx, "keast"] = Keast[row_idx, col_idx]
                pois_gdf.at[idx, "ksouth"] = Ksouth[row_idx, col_idx]
                pois_gdf.at[idx, "kwest"] = Kwest[row_idx, col_idx]
                pois_gdf.at[idx, "knorth"] = Knorth[row_idx, col_idx]
                pois_gdf.at[idx, "ldown"] = Ldown[row_idx, col_idx]
                pois_gdf.at[idx, "lup"] = Lup[row_idx, col_idx]
                pois_gdf.at[idx, "least"] = Least[row_idx, col_idx]
                pois_gdf.at[idx, "lsouth"] = Lsouth[row_idx, col_idx]
                pois_gdf.at[idx, "lwest"] = Lwest[row_idx, col_idx]
                pois_gdf.at[idx, "lnorth"] = Lnorth[row_idx, col_idx]
                pois_gdf.at[idx, "Ta"] = Ta[i]
                pois_gdf.at[idx, "Tg"] = TgOut[row_idx, col_idx]
                pois_gdf.at[idx, "RH"] = RH[i]
                pois_gdf.at[idx, "Esky"] = esky
                pois_gdf.at[idx, "Tmrt"] = Tmrt[row_idx, col_idx]
                pois_gdf.at[idx, "I0"] = I0
                pois_gdf.at[idx, "CI"] = CI
                pois_gdf.at[idx, "Shadow"] = shadow[row_idx, col_idx]
                pois_gdf.at[idx, "SVF_b"] = svf[row_idx, col_idx]
                pois_gdf.at[idx, "SVF_bv"] = svfbuveg[row_idx, col_idx]
                pois_gdf.at[idx, "KsideI"] = KsideI[row_idx, col_idx]
                # Recalculating wind speed based on powerlaw
                WsPET = (1.1 / wind_sensor_ht) ** 0.2 * Ws[i]
                WsUTCI = (10.0 / wind_sensor_ht) ** 0.2 * Ws[i]
                resultPET = p._PET(
                    Ta[i],
                    RH[i],
                    Tmrt[row_idx, col_idx],
                    WsPET,
                    weight,
                    age,
                    pers_ht,
                    activity,
                    clothing,
                    sex,
                )
                pois_gdf.at[idx, "PET"] = resultPET
                resultUTCI = utci.utci_calculator(
                    Ta[i], RH[i], Tmrt[row_idx, col_idx], WsUTCI
                )
                pois_gdf.at[idx, "UTCI"] = resultUTCI
                pois_gdf.at[idx, "CI_Tg"] = CI_Tg
                pois_gdf.at[idx, "CI_TgG"] = CI_TgG
                pois_gdf.at[idx, "KsideD"] = KsideD[row_idx, col_idx]
                pois_gdf.at[idx, "Lside"] = Lside[row_idx, col_idx]
                pois_gdf.at[idx, "diffDown"] = dRad[row_idx, col_idx]
                pois_gdf.at[idx, "Kside"] = Kside[row_idx, col_idx]
            pois_gdf.to_file(out_path_str + "/POI.gpkg", layer=time_code, driver="GPKG")

        common.save_raster(
            out_path_str + "/Tmrt/Tmrt_" + time_code + ".tif",
            Tmrt,
            dsm_transf,
            dsm_crs,
        )
        common.save_raster(
            out_path_str
            + "/shadows/Shadow_"
            + str(int(YYYY[0, i]))
            + "_"
            + str(int(DOY[i]))
            + "_"
            + XH
            + str(int(hours[i]))
            + XM
            + str(int(minu[i]))
            + w
            + ".tif",
            shadow,
            dsm_transf,
            dsm_crs,
        )

    # Output I0 vs. Kglobal plot
    radG_for_plot = radG[DOY == first_unique_day[0]]
    hours_for_plot = hours[DOY == first_unique_day[0]]
    fig, ax = plt.subplots()
    ax.plot(hours_for_plot, I0_array, label="I0")
    ax.plot(hours_for_plot, radG_for_plot, label="Kglobal")
    ax.set_ylabel("Shortwave radiation [$Wm^{-2}$]")
    ax.set_xlabel("Hours")
    ax.set_title("UTC" + str(int(utc)))
    ax.legend()
    fig.savefig(out_path_str + "/metCheck.png", dpi=150)

    # Copying met file for SpatialTC
    umep_df.to_csv(out_path_str + "/metforcing.csv")

    tmrtplot = tmrtplot / Ta.__len__()  # fix average Tmrt instead of sum, 20191022
    common.save_raster(
        out_path_str + "/Tmrt_average.tif", tmrtplot, dsm_transf, dsm_crs
    )

    rmtree(temp_dir, ignore_errors=True)