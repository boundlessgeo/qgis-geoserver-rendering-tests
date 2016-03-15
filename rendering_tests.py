# -*- coding: utf-8 -*-

"""
***************************************************************************
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

__author__ = 'Alessandro Pasotti'
__date__ = '2016/03/10'
__copyright__ = 'Copyright 2016, Boundless'
# This will get replaced with a git SHA1 when you do a git archive
__revision__ = '$Format:%H$'

import sip
sip.setapi('QVariant', 2)

import os
import sys
import re
import urllib
import urllib3
import urlparse
import unittest
import operator
import cgi
from xml.dom import minidom
from xml.parsers.expat import ExpatError


from PyQt4 import QtGui, QtCore
from PyQt4.QtXml import QDomDocument
from qgis.core import *
from qgis.gui import *

from nose_parameterized import parameterized
from skimage.measure import compare_mse, compare_ssim
from skimage.io import imread, imsave
from skimage.transform import rescale
from skimage.feature import match_template


from libs.sldadapter import getGsCompatibleSld


# Load default config
from config import *


# Load custom config overrides
try:
    from config_local import *
except ImportError:
    pass


def compare_images(pathA, pathB):
    # compute the mean squared error structural similarity index
    # and template match for the images
    # s: a decimal value between -1 and 1, and value 1 is only
    #   reachable in the case of two identical sets of data.
    # m: 0.0 in case of two identical sets of data
    # r: 1.0 in case of two identical sets of data
    imageA = imread(pathA)
    imageB = imread(pathB)
    m = compare_mse(imageA, imageB)
    s = compare_ssim(imageA, imageB, multichannel=True)
    # Template match on donwscaled image
    if imageA.shape[0] <= 300:
        r = match_template(imageA, imageB)[0][0][0]
    else:
        factor = 300 / float(imageA.shape[0])
        r = match_template(rescale(imageA, factor), rescale(imageB, factor))[0][0][0]
    # Wang's original algorithm
    # s = compare_ssim(imageA, imageB, multichannel=True, gaussian_weights=True, sigma=1.5, use_sample_covariance=False)
    imageC = imageB - imageA
    # Store diffs
    imsave(pathA.replace('geoserver_getmap.png', 'diffs.png'), imageC)
    return s, m, r


def get_test_parameters():
    """Return tuple with test name and image comparison"""
    # load QGIS project
    # get all test layers SLDs
    # Init QGIS
    app = QtGui.QApplication(sys.argv)
    QgsApplication.setPrefixPath('/usr', True)
    QgsApplication.initQgis()

    # Load project
    assert(QgsProject.instance().read(QtCore.QFileInfo(QGIS_TEST_PROJECT)))

    # Read registry
    registry = QgsMapLayerRegistry.instance()

    # Map layer types: http://qgis.org/api/classQgsMapLayer.html#pub-types
    LAYER_TYPES = {
        0 : 'vector',
        1 : 'raster',
        2 : 'plugin',
    }

    test_params = []
    test_layers = [layer for id, layer in registry.mapLayers().iteritems() if layer.name().startsWith('test_') and 0 == layer.type()]
    for layer in test_layers:

        # Extract vars
        s = QgsExpressionContextUtils.layerScope(layer)
        try:
            expected_ssim = float(s.variable('expected_ssim'))
        except (ValueError, TypeError):
            expected_ssim = EXPECTED_SSIM
        try:
            expected_match = float(s.variable('expected_match'))
        except (ValueError, TypeError):
            expected_match = EXPECTED_MATCH
        try:
            expected_mse = float(s.variable('expected_mse'))
        except (ValueError, TypeError):
            expected_mse = EXPECTED_MSE
        try:
            bbox = s.variable('bbox')
        except (ValueError, TypeError):
            bbox = BBOX
        if not bbox:
            bbox = BBOX
        try:
            width = int(s.variable('width'))
        except (ValueError, TypeError):
            width = WIDTH
        try:
            height = int(s.variable('height'))
        except (ValueError, TypeError):
            height = HEIGHT

        test_name = str(layer.name())
        geoserver_name = urlparse.parse_qs(urlparse.urlparse(str(layer.dataProvider().dataSourceUri())).query)['TYPENAME'][0]
        try:
            sld, icons = getGsCompatibleSld(layer) # rename to match the gs layer name
            sld = sld.replace(layer.name(), geoserver_name)
        except AttributeError:
            sld = ''
            icons = []

        # qgis_layer_name, test_name, sld, expected_ssim, expected_mse
        test_params.append((
            test_name,
            str(layer.name()), # qgis layer name
            geoserver_name, # geoserver layer name
            sld,
            expected_ssim,
            expected_mse,
            expected_match,
            bbox,
            width,
            height,
        ))
        # Also store SLD (1.1)  and QML for reference
        qml_file = os.path.join(RESULTS_DIR, '%s.qml' % test_name)
        sld_file = os.path.join(RESULTS_DIR, '%s_sld_1.1.sld' % test_name)
        layer.saveNamedStyle(qml_file)
        layer.saveSldStyle(sld_file)

    return test_params



class TestWMSRendering(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Check dirs
        try:
            os.mkdir(RESULTS_DIR)
        except OSError:
            pass
        # Clean env just to be sure
        env_vars = ['QUERY_STRING', 'QGIS_PROJECT_FILE']
        for ev in env_vars:
            try:
                del os.environ[ev]
            except KeyError:
                pass
        TestWMSRendering.pool = urllib3.PoolManager()
        TestWMSRendering.results = {}


    @classmethod
    def tearDownClass(cls):
        """Writes a report"""
        sorted_res = sorted(TestWMSRendering.results.items(), key=operator.itemgetter(0))
        rows_html = ''
        with open(os.path.join(TEMPLATES_DIR, 'row.html'), 'r') as f:
            row_tpl = f.read()
        with open(os.path.join(TEMPLATES_DIR, 'main.html'), 'r') as f:
            main_tpl = f.read()

        for k, r in sorted_res:
            res_tpl = row_tpl
            # {test_name} {test_status} {sld} {qg_img} {gs_img}
            rows_html += res_tpl.format(**r)

        main_tpl = main_tpl.replace('{rows}', rows_html)
        with open(os.path.join(RESULTS_DIR, 'results.html'), 'w+') as f:
            f.write(main_tpl)


    def getmap(self, endpoint, layers, bbox, width=300, height=200, sld=None, extra_params={}, save_as=None):
        params = {
            'BBOX': bbox,
            'HEIGHT': height,
            'WIDTH': width,
            'SERVICE': 'WMS',
            'VERSION' : '1.3.0',
            'REQUEST': 'GetMap',
            'SRS': 'EPSG:4326',
            'FORMAT' : 'image/png',
            'LAYERS': layers,
            #'TRANSPARENT': 'TRUE',
        }
        if sld is not None:
            params.update({'SLD_BODY': sld})
        params.update(extra_params)
        url = endpoint + urllib.urlencode(params)
        #print url
        response = TestWMSRendering.pool.urlopen('GET', url, headers={'Content-Type': 'text/xml'})
        if save_as:
            with open(save_as, 'w+') as f:
                f.write(response.data)
        return response, url


    def geoserver_getmap(self, layers, bbox, width=300, height=200, sld=None, save_as=None):
        """GeoServer getmap request"""
        return self.getmap(GEOSERVER_URI, layers, bbox, width=width, height=height, sld=sld, save_as=save_as)


    def qgis_getmap(self, layers, bbox, width=300, height=200, sld=None, save_as=None):
        """QGIS getmap request"""
        return self.getmap(QGIS_URI, layers, bbox,  width=width, height=height, sld=sld, extra_params={'MAP': QGIS_TEST_PROJECT}, save_as=save_as)


    @unittest.skip("dev only")
    def test_getmap(self):
        bbox = BBOX
        self.geoserver_getmap('sf:bugsites',
                        bbox=bbox,
                        width=WIDTH,
                        height=HEIGHT,
                        save_as=os.path.join(RESULTS_DIR, 'qgis_getmap.png'),
                    )
        self.qgis_getmap('sf:bugsites',
                        bbox=bbox,
                        width=WIDTH,
                        height=HEIGHT,
                        save_as=os.path.join(RESULTS_DIR, 'geoserver_getmap.png'),
                    )


    @unittest.skip("dev only")
    def test_getmap_with_sld(self):
        sld = """
        <?xml version="1.0" encoding="UTF-8"?>
            <sld:StyledLayerDescriptor xmlns="http://www.opengis.net/sld" xmlns:sld="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc" xmlns:gml="http://www.opengis.net/gml" version="1.0.0">
            <sld:NamedLayer>
                <sld:Name>sf:bugsites</sld:Name>
                    <sld:UserStyle>
                        <sld:Title>SLD Cook Book: Simple Point</sld:Title>
                        <sld:FeatureTypeStyle>
                            <sld:Rule>
                                <sld:PointSymbolizer>
                                    <sld:Graphic>
                                        <sld:Mark>
                                            <sld:WellKnownName>circle</sld:WellKnownName>
                                            <sld:Fill><CssParameter name="fill">#FF0000</CssParameter></sld:Fill>
                                        </sld:Mark>
                                        <sld:Size>6</sld:Size>
                                    </sld:Graphic>
                                </sld:PointSymbolizer>
                            </sld:Rule>
                        </sld:FeatureTypeStyle>
                    </sld:UserStyle>
                </sld:NamedLayer>
            </sld:StyledLayerDescriptor>
        """.replace('\n', '').replace(' ' * 4, '')

        bbox = BBOX

        self.geoserver_getmap('sf:bugsites',
                        bbox=bbox,
                        width=WIDTH,
                        height=HEIGHT,
                        sld=sld,
                        save_as=os.path.join(RESULTS_DIR, 'geoserver_getmap_with_sld.png')
                      )


    @parameterized.expand(get_test_parameters())
    def test_sldadapter(self,
                        test_name,
                        qgis_layer_name,
                        geoserver_layer_name,
                        sld,
                        expected_ssim=EXPECTED_SSIM,
                        expected_mse=EXPECTED_MSE,
                        expected_match=EXPECTED_MATCH,
                        bbox=BBOX,
                        width=WIDTH,
                        height=HEIGHT):
        qg_img = os.path.join(RESULTS_DIR, '%s_qgis_getmap.png' % test_name)
        gs_img = os.path.join(RESULTS_DIR, '%s_geoserver_getmap.png' % test_name)
        sld_path = os.path.join(RESULTS_DIR, '%s_sld_1.0.sld' % test_name)
        # call qg
        (qg_response, qg_url) = self.qgis_getmap( qgis_layer_name,
                        bbox=bbox,
                        width=width,
                        height=height,
                        save_as=qg_img,
                      )
        # call gs
        (gs_response, gs_url) = self.geoserver_getmap( geoserver_layer_name,
                        bbox=bbox,
                        width=width,
                        height=height,
                        sld=sld,
                        save_as=gs_img,
                      )

        try:
            xml = minidom.parseString(sld)
            sld = xml.toprettyxml(indent=" "*4)
            sld = "\n".join([ll.rstrip() for ll in sld.splitlines() if ll.strip()])
        except ExpatError, e:
            raise AssertionError('Invalid SLD %s' % e)
        finally:
            # Store SLD
            with open(sld_path, 'w+') as f:
                f.write(sld)

        ct = gs_response.getheaders()['content-type']
        if 'image/png' == ct:
            s, m, r = compare_images(gs_img, qg_img)
        else:
            with open(gs_img, 'r') as f:
               gs_error = cgi.escape(f.read())
               
            TestWMSRendering.results[test_name] = {
                'test_name': test_name,
                'test_title': test_name.replace('_', ' '),
                'alert_status': 'danger',
                'test_status': 'fail',
                'qg_img': os.path.relpath(qg_img, RESULTS_DIR),
                'gs_img': os.path.relpath(FAILURE_IMAGE, RESULTS_DIR),
                'diff_img': os.path.relpath(FAILURE_IMAGE, RESULTS_DIR),
                'expected_ssim': expected_ssim,
                'expected_mse': expected_mse,
                'expected_match': expected_match,
                'actual_mse': 'n/a',
                'actual_ssim': 'n/a',
                'actual_match': 'n/a',
                'sld': cgi.escape(sld),
                'gs_error': '<pre><code class="xml">' + gs_error + '</code></pre>',
                'gs_url': gs_url,
                'qg_url': qg_url,
            }
            raise AssertionError('GeoServer failed!')
        try:
            self.assertTrue(s >= expected_ssim and m <= expected_mse and r >= expected_match, \
                "Images differ (%s >= %s and %s <= %s and %s >= %s)" % \
                    (s, expected_ssim, m, expected_mse, r, expected_match))
            success = True
        except AssertionError, e:
            success = False
            raise e
        finally:
            TestWMSRendering.results[test_name] = {
                'test_name': test_name,
                'test_title': test_name.replace('_', ' '),
                'alert_status': 'success' if success else 'danger',
                'test_status': 'success' if success else 'fail',
                'qg_img': os.path.relpath(qg_img, RESULTS_DIR),
                'gs_img': os.path.relpath(gs_img, RESULTS_DIR),
                'diff_img': os.path.relpath(gs_img, RESULTS_DIR).replace('geoserver_getmap', 'diffs'),
                'expected_ssim': expected_ssim,
                'expected_mse': expected_mse,
                'expected_match': expected_match,
                'actual_mse': m,
                'actual_ssim': s,
                'actual_match': r,
                'sld': cgi.escape(sld),
                'gs_error': '',
                'gs_url': gs_url,
                'qg_url': qg_url,
            }

if __name__ == '__main__':
    unittest.main()
