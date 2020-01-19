#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright (c) Karol Będkowski, 2020
# This file is part of tbviewer
#
# Distributed under terms of the GPLv3 license.

"""

"""
import logging
import math


_LOG = logging.getLogger(__name__)


class InvalidFileException(RuntimeError):
    pass


class Point:
    def __init__(self, x, y, lat, lon):
        self.idx = None
        self.x = x
        self.y = y
        self.lat = lat
        self.lon = lon

    def __repr__(self):
        return prettydict(self.__dict__)


def degree2minsec(d, lz='S', gz='N'):
    symb = gz
    if d < 0:
        d *= -1
        symb = lz

    return int(d), (d - int(d)) * 60, symb


class MapFile():
    def __init__(self):
        self.clear()

    def clear(self):
        self.filename = None
        self.img_filename = None
        self.img_filepath = None
        self.projection = None
        self.map_projection = None
        self.points = []
        self.mmpxy = []
        self.mmpll = []
        self.mmpnum = None
        self.mm1b = None
        self.image_width = None
        self.image_height = None

    def __str__(self):
        return "<MapMeta {}>".format(", ".join(
            "{}={}".format(k, v)
            for k, v in self.__dict__.items()
            if k[0] != '_'
        ))

    def parse_map(self, content):
        """Parse content of .map file."""
        self.clear()
        content = [line.strip() for line in content.split("\n")]
        if content[0] != 'OziExplorer Map Data File Version 2.2':
            raise InvalidFileException(
                "Wrong .map file - wrong header %r" % content[0])

        self.img_filename = content[1]
        self.img_filepath = content[2]
        # line 3 - skip
        self.projection = content[4]
        # line 5-6 - reserverd
        # line 7 - Magnetic variation
        self.map_projection = content[8]

        for line in content[9:]:
            if line.startswith("Point"):
                point = _parse_point(line)
                if point:
                    self.points.append(point)
            elif line.startswith('IWH,Map Image Width/Height,'):
                self.image_width, self.image_height = \
                    map(int, line[27:].split(','))
            elif line.startswith('MMPNUM,'):
                self.mmpnum = int(line[7:])
            elif line.startswith('MMPLL'):
                point_id, lat, lon = _parse_mmpll(line)
                if point_id - 1 != len(self.mmpll):
                    raise Error()
                self.mmpll.append((lat, lon))
            elif line.startswith('MMPXY'):
                point_id, x, y = _parse_mmpxy(line)
                if point_id - 1 != len(self.mmpxy):
                    _LOG.warn("parse mmpxy error: %r", line)
                    raise InvalidFileException()
                self.mmpxy.append((x, y))
            elif line.startswith('MM1B,'):
                self.mm1b = float(line[5:])

    def to_str(self):
        points = []
        for idx, p in enumerate(self.points):
            _LOG.debug("%r, %r", idx, p)
            lat_m, lat_s, lat_d = degree2minsec(p.lat, 'W', 'E')
            lon_m, lon_s, lon_d = degree2minsec(p.lon, 'S', 'N')
            points.append(_MAP_POINT_TEMPLATE.format(
                idx=idx, x=int(p.x), y=int(p.y),
                lat_m=lat_m, lat_s=lat_s, lat_d=lat_d,
                lon_m=lon_m, lon_s=lon_s, lon_d=lon_d
            ))
        mmpxy = [_MAP_MMPXY_TEMPLATE.format(idx=idx+1, x=x, y=y)
                 for idx, (x, y) in enumerate(self.mmpxy)]
        mmpll = [_MAP_MMPLL_TEMPLATE.format(idx=idx+1, lat=lat, lon=lon)
                 for idx, (lat, lon) in enumerate(self.mmpll)]
        return _MAP_TEMPALTE.format(
            img_filename=self.img_filename or "dummy.jpg",
            img_filepath=self.img_filepath or "dummy.jpg",
            points="\n".join(points),
            mmplen=len(mmpxy),
            mmpxy="\n".join(mmpxy),
            mmpll="\n".join(mmpll),
            mm1b=self.mm1b,
            image_width=self.image_width,
            image_height=self.image_height
        )

    def set_points(self, points):
        _LOG.debug("points: %r", points)
        self.points = [Point(x, y, lat, lon)
                       for x, y, lat, lon in points]

    def calibrate(self):
        mmp = _calibrate_calculate(self.points, self.image_width,
                                   self.image_height)
        self.mmpll = []
        self.mmpxy = []
        for x, y, lat, lon in mmp:
            self.mmpxy.append((x, y))
            self.mmpll.append((lat, lon))

        self.mmpnum = len(self.mmpll)

        # calc MM1B - The scale of the image meters/pixel, its
        # calculated in the left / right image direction.
        lat_w_avg = (self.mmpll[0][0] + self.mmpll[3][0]) / 2
        lat_e_avg = (self.mmpll[1][0] + self.mmpll[2][0]) / 2
        lon_avg = (self.mmpll[0][1] + self.mmpll[3][1] +
                   self.mmpll[1][1] + self.mmpll[2][1]) / 4

        d_lat = lat_e_avg - lat_w_avg
        d_lat_dist = abs(d_lat * math.pi / 180.0 * 6378137.0 *
                         math.cos(math.radians(lon_avg)))

        self.mm1b = d_lat_dist / self.image_width

    def validate(self):
        _LOG.debug("mapfile: %s", self)
        return self.mmpnum == len(self.mmpxy) == len(self.mmpll) == 4

    def xy2latlon(self, x, y):
        if not self.mmpll:
            return None
        return _map_xy_lonlat(
            self.mmpll[0], self.mmpll[1], self.mmpll[2], self.mmpll[3],
            self.image_width, self.image_height,
            x, y)


def _parse_point(line):
    fields = line.split(',')
    if fields[2].strip() == "":
        return None
    point = Point(
        int(fields[2]), int(fields[3]),
        int(fields[9]) + float(fields[10]) / 60.,
        int(fields[6]) + float(fields[7]) / 60.)
    point.idx = int(fields[0][6:])
    if fields[8] == 'E':
        point.lat *= -1
    if fields[11] == 'S':
        point.lon *= -1
    return point


def _parse_mmpxy(line):
    fields = line.split(',')
    if len(fields) != 4:
        raise InvalidFileException(
            "Wrong .map file - wrong number of fields in MMPXY field %r"
            % line)
    _, point_id, x, y = [field.strip() for field in fields]
    try:
        point_id = int(point_id)
        x = int(x)
        y = int(y)
    except ValueError as err:
        raise InvalidFileException(
            "Wrong .map file - wrong MMPXY field %r; %s" % (line, err))
    return point_id, x, y


def _parse_mmpll(line):
    fields = line.split(',')
    if len(fields) != 4:
        raise InvalidFileException(
            "Wrong .map file - wrong number of fields in MMPLL field %r"
            % line)
    _, point_id, lon, lat = [field.strip() for field in fields]
    try:
        point_id = int(point_id)
        lon = float(lon)
        lat = float(lat)
    except ValueError as err:
        raise InvalidFileException(
            "Wrong .map file - wrong MMPLL field %r; %s" % (line, err))
    return point_id, lon, lat


def _sort_points(positions, width, height):
    if not positions:
        return []

    def dist_from(pos, x0, y0):
        return math.sqrt((pos.x - x0) ** 2 + (pos.y - y0) ** 2)

    # TODO: assure distinct points

    nw = sorted(positions, key=lambda x: dist_from(x, 0, 0))[0]
    ne = sorted(positions, key=lambda x: dist_from(x, width, 0))[0]
    sw = sorted(positions, key=lambda x: dist_from(x, 0, height))[0]
    se = sorted(positions, key=lambda x: dist_from(x, width, height))[0]
    _LOG.debug("_sort_points: nw=%r ne=%r sw=%r se=%r", nw, ne, sw, se)
    return (nw, ne, se, sw)


def _calibrate_calculate(positions, width, height):
    _LOG.debug("calibrate_calculate: %r, %r, %r", positions, width, height)
    poss = _sort_points(positions, width, height)
    nw, ne, se, sw = poss

    # west/east - north
    ds = (nw.lat - ne.lat) / (nw.x - ne.x)
    nw_lat = nw.lat - ds * nw.x
    ne_lat = nw_lat + ds * width

    # west/east - south
    ds = (se.lat - sw.lat) / (se.x - sw.x)
    sw_lat = sw.lat - ds * sw.x
    se_lat = sw_lat + ds * width

    # north / south - west
    ds = (nw.lon - sw.lon) / (nw.y - sw.y)
    nw_lon = nw.lon - ds * nw.y
    sw_lon = nw_lon + ds * height

    # north / south - east
    ds = (ne.lon - se.lon) / (ne.y - se.y)
    ne_lon = ne.lon - ds * ne.y
    se_lon = ne_lon + ds * height

    res = [
        (0, 0, nw_lat, nw_lon),  # nw
        (width, 0, ne_lat, ne_lon),  # ne
        (width, height, se_lat, se_lon),  # se
        (0, height, sw_lat, sw_lon)  # sw
    ]
    _LOG.debug("_calibrate_calculate %r", res)
    return res

def _map_xy_lonlat(xy0, xy1, xy2, xy3, sx, sy, x, y):
    x0, y0 = xy0
    x1, y1 = xy1
    x2, y2 = xy2
    x3, y3 = xy3

    syy = sy - y
    sxx = sx - x

    return _intersect_lines(
        (syy * x0 + y * x3) / sy, (syy * y0 + y * y3) / sy,
        (syy * x1 + y * x2) / sy, (syy * y1 + y * y2) / sy,
        (sxx * x0 + x * x1) / sx, (sxx * y0 + x * y1) / sx,
        (sxx * x3 + x * x2) / sx, (sxx * y3 + x * y2) / sx)


def _det(a, b, c, d):
    return a * d - b * c


def _intersect_lines(x1, y1, x2, y2, x3, y3, x4, y4):
    d = _det(x1 - x2, y1 - y2, x3 - x4, y3 - y4) or 1
    d1 = _det(x1, y1, x2, y2)
    d2 = _det(x3, y3, x4, y4)
    px = _det(d1, x1 - x2, d2, x3 - x4) / d
    py = _det(d1, y1 - y2, d2, y3 - y4) / d
    return px, py


def prettydict(d):
    return "\n".join(
        str(key) + "=" + repr(val)
        for key, val in sorted(d.items())
    )


_MAP_POINT_TEMPLATE = \
    "Point{idx},xy,{x:>5},{y:>5},in, deg,{lon_m:>4},{lon_s:3.7f},{lon_d},"\
    "{lat_m:>4},{lat_s:3.7f},{lat_d}, grid,   ,           ,           ,N"

_MAP_MMPXY_TEMPLATE = "MMPXY,{idx},{x},{y}"
_MAP_MMPLL_TEMPLATE = "MMPLL,{idx},{lat:3.7f},{lon:3.7f}"

_MAP_TEMPALTE = """OziExplorer Map Data File Version 2.2
{img_filename}
{img_filepath}
1 ,Map Code,
WGS 84,WGS 84,   0.0000,   0.0000,WGS 84
Reserved 1
Reserved 2
Magnetic Variation,,,E
Map Projection,Latitude/Longitude,PolyCal,No,AutoCalOnly,No,BSBUseWPX,No
{points}
Projection Setup,,,,,,,,,,
Map Feature = MF ; Map Comment = MC     These follow if they exist
Track File = TF      These follow if they exist
Moving Map Parameters = MM?    These follow if they exist
MM0,Yes
MMPNUM,{mmplen}
{mmpxy}
{mmpll}
MM1B,{mm1b}
MOP,Map Open Position,0,0
IWH,Map Image Width/Height,{image_width},{image_height}
"""
