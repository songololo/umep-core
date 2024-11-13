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

 "This algorithm identiies wall pixels and "
"their height from ground and building digital surface models (DSM) by using a filter as "
"presented by Lindberg et al. (2015a). Optionally, wall aspect can also be estimated using "
"a specific linear filter as presented by Goodwin et al. (1999) and further developed by "
"Lindberg et al. (2015b) to obtain the wall aspect. Wall aspect is given in degrees where "
"a north facing wall pixel has a value of zero. The output of this plugin is used in other "
"UMEP plugins such as SEBE (Solar Energy on Building Envelopes) and SOLWEIG (SOlar LongWave "
"Environmental Irradiance Geometry model).\n"
"------------------ \n"
"Goodwin NR, Coops NC, Tooke TR, Christen A, Voogt JA (2009) Characterizing urban surface cover and structure with airborne lidar technology. Can J Remote Sens 35:297–309\n"
"Lindberg F., Grimmond, C.S.B. and Martilli, A. (2015a) Sunlit fractions on urban facets - Impact of spatial resolution and approach Urban Climate DOI: 10.1016/j.uclim.2014.11.006\n"
"Lindberg F., Jonsson, P. & Honjo, T. and Wästberg, D. (2015b) Solar energy on building envelopes - 3D modelling in a 2D environment Solar Energy 115 369–378"
"-------------\n"
"Full manual available via the <b>Help</b>-button."
"https://umep-docs.readthedocs.io/en/latest/pre-processor/Urban%20Geometry%20Wall%20Height%20and%20Aspect.html"
"""

__author__ = "Fredrik Lindberg"
__date__ = "2020-04-02"
__copyright__ = "(C) 2020 by Fredrik Lindberg"

# This will get replaced with a git SHA1 when you do a git archive

__revision__ = "$Format:%H$"


from pathlib import Path

from umep import common
from umep.functions import wallalgorithms as wa


def generate_wall_hts(
    dsm_path: str,
    bbox: list[int, int, int, int],
    out_dir: str,
    wall_limit: float = 0,
):
    """ """
    dsm_rast, dsm_transf, dsm_crs = common.load_raster(dsm_path, bbox)
    dsm_scale = 1 / dsm_transf.a

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out_path_str = str(out_path)

    walls = wa.findwalls(dsm_rast, wall_limit)
    common.save_raster(out_path_str + "/" + "wall_hts.tif", walls, dsm_transf, dsm_crs)

    dirwalls = wa.filter1Goodwin_as_aspect_v3(walls, dsm_scale, dsm_rast)
    common.save_raster(
        out_path_str + "/" + "wall_aspects.tif", dirwalls, dsm_transf, dsm_crs
    )