# -*- coding: utf-8 -*-

"""
***************************************************************************
    Default configuration for:
    Tests for QGIS GeoServer rendering comparison

    ---------------------
    Date                 : March 2016
    Copyright            : © 2016 Boundless
    Contact              : info@boundlessgeo.com
    Author               : Alessandro Pasotti

***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************

"""

import os

# Endpoints
GEOSERVER_URI='http://localhost:8080/geoserver/sf/wms?'
QGIS_URI='http://localhost:80/cgi-bin/qgis_mapserv.fcgi?'
# This project contains the test
DATA_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__))
, 'data')
QGIS_TEST_PROJECT=os.path.join(DATA_DIR, 'qgis_test_project.qgs')


# Results (images, SLD, QML etc.) will be stored here
RESULTS_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')
# Templates for the results.html report
TEMPLATES_DIR=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
FAILURE_IMAGE=os.path.join(TEMPLATES_DIR, 'fail.png')


# Defaults, can be overridden in individuale test configuration by settings
# layer's variables (same name but lowercase)
BBOX='44.36645793914795,-103.8418550491333,44.44324207305908,-103.76507091522217'
WIDTH=995/2
HEIGHT=995/2
EXPECTED_SSIM=0.6
EXPECTED_MATCH=0.5
EXPECTED_MSE=500
