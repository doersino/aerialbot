import io
import math
import os
import re
import random
import sys
import time
from datetime import datetime

import argparse

import logging
import logging.config
import traceback

import concurrent.futures
import threading

import requests

from configobj import ConfigObj

import shapefile
import shapely.geometry

from PIL import Image, ImageEnhance, ImageOps
Image.MAX_IMAGE_PIXELS = None

import tweepy


TILE_SIZE = 256  # in pixels
EARTH_CIRCUMFERENCE = 40075.016686 * 1000  # in meters, at the equator

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/35.0.1916.47 Safari/537.36"

LOGGER = None
VERBOSITY = None


class WebMercator:
    """Various functions related to the Web Mercator projection."""

    @staticmethod
    def project(geopoint, zoom):
        """
        An implementation of the Web Mercator projection (see
        https://en.wikipedia.org/wiki/Web_Mercator_projection#Formulas) that
        returns floats. That's required for cropping of stitched-together tiles
        such that they only show the configured area, hence no use of math.floor
        here.
        """

        factor = (1 / (2 * math.pi)) * 2 ** zoom
        x = factor * (math.radians(geopoint.lon) + math.pi)
        y = factor * (math.pi - math.log(math.tan((math.pi / 4) + (math.radians(geopoint.lat) / 2))))
        return (x, y)

class GeoPoint:
    """
    A latitude-longitude coordinate pair, in that order due to ISO 6709, see:
    https://stackoverflow.com/questions/7309121/preferred-order-of-writing-latitude-longitude-tuples
    """

    def __init__(self, lat, lon):
        assert -90 <= lat <= 90 and -180 <= lon <= 180

        self.lat = lat
        self.lon = lon

    def __repr__(self):
        return f"GeoPoint({self.lat}, {self.lon})"

    def fancy(self):
        """Stringifies the point in a more fancy way than __repr__, e.g.
        "44°35'27.6"N 100°21'53.1"W", i.e. with minutes and seconds."""

        # helper function as both latitude and longitude are stringified
        # basically the same way
        def fancy_coord(coord, pos, neg):
            coord_dir = pos if coord > 0 else neg
            coord_tmp = abs(coord)
            coord_deg = math.floor(coord_tmp)
            coord_tmp = (coord_tmp - math.floor(coord_tmp)) * 60
            coord_min = math.floor(coord_tmp)
            coord_sec = round((coord_tmp - math.floor(coord_tmp)) * 600) / 10
            coord = f"{coord_deg}°{coord_min}'{coord_sec}\"{coord_dir}"
            return coord

        lat = fancy_coord(self.lat, "N", "S")
        lon = fancy_coord(self.lon, "E", "W")

        return f"{lat} {lon}"

    @classmethod
    def random(cls, georect):
        """
        Generating a random point with regard to actual surface area is a bit
        tricky due to meridians being closer together at high latitudes (see
        https://en.wikipedia.org/wiki/Mercator_projection#Distortion_of_sizes),
        which is why this isn't just a matter of doing something like this:
        lat = random.uniform(georect.sw.lat, georect.ne.lat)
        lon = random.uniform(georect.sw.lon, georect.ne.lon)
        """

        # latitude
        north = math.radians(georect.ne.lat)
        south = math.radians(georect.sw.lat)
        lat = math.degrees(math.asin(random.random() * (math.sin(north) - math.sin(south)) + math.sin(south)))

        # longitude
        west = georect.sw.lon
        east = georect.ne.lon
        width = east - west
        if width < 0:
            width += 360
        lon = west + width * random.random()
        if lon > 180:
            lon -= 360
        elif lon < -180:
            lon += 360

        # for debugging:
        """
        for i in range(1000):
            p = GeoPoint.random(GeoRect(GeoPoint(0,0),GeoPoint(90,10)))
            print(f"{p.lon} {p.lat}")
        sys.exit()
        # run as: python3 aerialbot.py | gnuplot -p -e "plot '<cat'"
        """

        return cls(lat, lon)

    def to_maptile(self, zoom):
        """
        Conversion of this geopoint to a tile through application of the Web
        Mercator projection and flooring to get integer tile corrdinates.
        """

        x, y = WebMercator.project(self, zoom)
        return MapTile(zoom, math.floor(x), math.floor(y))

    def to_shapely_point(self):
        """
        Conversion to a point as expected by shapely. Note that latitude and
        longitude are reversed here – this matches their order in shapefiles.
        """

        return shapely.geometry.Point(self.lon, self.lat)

    def compute_zoom_level(self, max_meters_per_pixel):
        """
        Computes the outermost (i.e. lowest) zoom level that still fulfills the
        constraint. See:
        https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Resolution_and_Scale
        """

        meters_per_pixel_at_zoom_0 = ((EARTH_CIRCUMFERENCE / TILE_SIZE) * math.cos(math.radians(self.lat)))

        # 23 seems to be highest zoom level supported anywhere in the world, see
        # https://stackoverflow.com/a/32407072 (although 19 or 20 is the highest
        # in many places in practice)
        for zoom in reversed(range(0, 23+1)):
            meters_per_pixel = meters_per_pixel_at_zoom_0 / (2 ** zoom)

            # once meters_per_pixel eclipses the maximum, we know that the
            # previous zoom level was correct
            if meters_per_pixel > max_meters_per_pixel:
                return zoom + 1
        else:

            # if no match, the required zoom level would have been too high
            raise RuntimeError("your settings seem to require a zoom level higher than is commonly available")

class GeoRect:
    """
    A rectangle between two points. The first point must be the southwestern
    corner, the second point the northeastern corner:
       +---+ ne
       |   |
    sw +---+
    """

    def __init__(self, sw, ne):
        assert sw.lat <= ne.lat
        # not assert sw.lon < ne.lon since it may stretch across the date line

        self.sw = sw
        self.ne = ne

    def __repr__(self):
        return f"GeoRect({self.sw}, {self.ne})"

    @classmethod
    def from_shapefile_bbox(cls, bbox):
        """
        Basically from [sw_lon, sw_lat, ne_lon, sw_lat], which is the order
        pyshp stores bounding boxes in.
        """

        sw = GeoPoint(bbox[1], bbox[0])
        ne = GeoPoint(bbox[3], bbox[2])
        return cls(sw, ne)

    @classmethod
    def around_geopoint(cls, geopoint, width, height):
        """
        Creates a rectangle with the given point at its center. Like the random
        point generator, this accounts for high-latitude longitudes being closer
        together than at the equator. See also:
        https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Resolution_and_Scale
        """

        assert width > 0 and height > 0

        meters_per_degree = (EARTH_CIRCUMFERENCE / 360)

        width_geo = width / (meters_per_degree * math.cos(math.radians(geopoint.lat)))
        height_geo = height / meters_per_degree

        southwest = GeoPoint(geopoint.lat - height_geo / 2, geopoint.lon - width_geo / 2)
        northeast = GeoPoint(geopoint.lat + height_geo / 2, geopoint.lon + width_geo / 2)

        return cls(southwest, northeast)


class GeoShape:
    """
    This class is where shapefiles (of the form detailed in the config example,
    i.e. containing one layer with one polygon shape with lon/lat coordinates)
    are loaded and queried. Note that shapefiles use (lon, lat) coordinates,
    which are sequestered to this class only.
    """

    def __init__(self, shapefile_path):

        sf = shapefile.Reader(shapefile_path)
        shapes = sf.shapes()

        assert len(shapes) == 1
        assert shapes[0].shapeTypeName == 'POLYGON'

        self.outline = shapes[0]

    def contains(self, geopoint):
        """Does the shape contain the point?"""

        point = geopoint.to_shapely_point()
        polygon = shapely.geometry.shape(self.outline)
        return polygon.contains(point)

    def random_geopoint(self):
        """
        A random geopoint, using rejection sampling to make sure it's
        contained within the shape.
        """

        bounds = GeoRect.from_shapefile_bbox(self.outline.bbox)
        geopoint = GeoPoint.random(bounds)

        i = 0
        while not self.contains(geopoint):
            i += 1
            if i > 250:
                raise ValueError("cannot seem to find a point in the shape's bounding box that's within the shape – is your data definitely okay (it may well be if it's a bunch of spread-out islands)? if you're sure, you'll need to raise the iteration limit in this function")
            geopoint = GeoPoint.random(bounds)

        return geopoint


class MapTileStatus:
    """An enum type used to keep track of the current status of map tiles."""

    PENDING = 1
    CACHED = 2
    DOWNLOADING = 3
    DOWNLOADED = 4
    ERROR = 5

class MapTile:
    """
    A map tile: coordinates and, if it's been downloaded yet, image, plus some
    housekeeping stuff.
    """

    # static class members set based on the configuration
    tile_path_template = None
    tile_url_template = None

    def __init__(self, zoom, x, y):
        self.zoom = zoom
        self.x = x
        self.y = y

        # initialize the other variables
        self.status = MapTileStatus.PENDING
        self.image = None
        self.filename = None
        if (MapTile.tile_path_template):
            self.filename = MapTile.tile_path_template.format(zoom=self.zoom, x=self.x, y=self.y)

    def __repr__(self):
        return f"MapTile({self.zoom}, {self.x}, {self.y})"

    def zoomed(self, zoom_delta):
        """
        Returns a MapTileGrid of the area covered by this map tile, but zoomed
        by zoom_delta. This works this way because by increasing the zoom level
        by 1, a tile's area is subdivided into 4 quadrants.
        """

        zoom = self.zoom + zoom_delta
        fac = (2 ** zoom_delta)
        return MapTileGrid([[MapTile(zoom, self.x * fac + x, self.y * fac + y)
                             for y in range(0, fac)]
                             for x in range(0, fac)])

    def load(self):
        """Loads the image either from cache or initiates a download."""

        if self.filename is None:
            self.download()
        else:

            # check if already downloaded in tile store, otherwise download
            try:
                self.image = Image.open(self.filename)
                self.image.load()
                self.status = MapTileStatus.CACHED
            except IOError:
                self.download()

    def download(self):
        """
        Downloads a tile image. Sets the status to ERROR if things don't work
        out for whatever reason. Finally, writes the image to the cache if
        enabled.
        """

        self.status = MapTileStatus.DOWNLOADING

        try:
            url = MapTile.tile_url_template.format(x=self.x, y=self.y, zoom=self.zoom)
            r = requests.get(url, headers={'User-Agent': USER_AGENT})
        except requests.exceptions.ConnectionError:
            self.status = MapTileStatus.ERROR
            return

        # error handling (note that a warning is appropriate here – if this tile
        # is one of a tiles used in imagery quality testing, an error is not an
        # unexpected outcome and should thus not be thrown)
        if r.status_code != 200:
            LOGGER.warning(f"Unable to download {self}, status code {r.status_code}.")
            self.status = MapTileStatus.ERROR
            return

        # convert response into an image
        data = r.content
        self.image = Image.open(io.BytesIO(data))

        # sanity check
        assert self.image.mode == "RGB"
        assert self.image.size == (TILE_SIZE, TILE_SIZE)

        # save original data (not: re-encoded via image.save) in tile store if
        # enabled (and create the directory first if it doesn't already exist)
        if self.filename is not None:
            d = os.path.dirname(self.filename)
            if not os.path.isdir(d):
                os.makedirs(d)
            with open(self.filename, 'wb') as f:
                f.write(data)

        self.status = MapTileStatus.DOWNLOADED


class ProgressIndicator:
    """
    Displays and updates a progress indicator during tile download. Designed
    to run in a separate thread, polling for status updates frequently.
    """

    def __init__(self, maptilegrid):
        self.maptilegrid = maptilegrid

    def update_tile(self, maptile):
        """
        Updates a single tile depending on its state: pending tiles are grayish,
        cached tiles are blue, downloading tiles are yellow, successfully
        downloaded tiles are green, and tiles with errors are red. For each
        tile, two characters are printed – in most fonts, this is closer to a
        square than a single character. See https://stackoverflow.com/a/39452138
        for color escapes.
        """

        def p(s): print(s + "\033[0m", end='')

        if maptile.status == MapTileStatus.PENDING:
            p("░░")
        elif maptile.status == MapTileStatus.CACHED:
            p("\033[34m" + "██")
        elif maptile.status == MapTileStatus.DOWNLOADING:
            p("\033[33m" + "▒▒")
        elif maptile.status == MapTileStatus.DOWNLOADED:
            p("\033[32m" + "██")
        elif maptile.status == MapTileStatus.ERROR:
            p("\033[41m\033[37m" + "XX")

    def update_text(self):
        """
        Displays percentage and counts only.
        """

        cached = 0
        downloaded = 0
        errors = 0
        for maptile in self.maptilegrid.flat():
            if maptile.status == MapTileStatus.CACHED:
                cached += 1
            elif maptile.status == MapTileStatus.DOWNLOADED:
                downloaded += 1
            elif maptile.status == MapTileStatus.ERROR:
                errors += 1

        done = cached + downloaded
        total = self.maptilegrid.width * self.maptilegrid.height
        percent = int(10 * (100 * done / total)) / 10

        details = f"{done}/{total}"
        if cached:
            details += f", {cached} cached"
        if downloaded:
            details += f", {downloaded} downloaded"
        if errors:
            details += f", {errors} error"
            if errors > 1:
                details += "s"


        # need a line break after it so that the first line of the next
        # iteration of the progress indicator starts at col 0
        print(f"{percent}% ({details})")

    def update(self):
        """Updates the progress indicator."""

        # if normal verbosity is selected, don't do anything fancy
        if VERBOSITY == "normal":
            self.update_text()
            return

        for y in range(self.maptilegrid.height):
            for x in range(self.maptilegrid.width):
                maptile = self.maptilegrid.at(x, y)
                self.update_tile(maptile)
            print()  # line break

        self.update_text()

        # move cursor back up to the beginning of the progress indicator for
        # the next iteration, see
        # http://www.tldp.org/HOWTO/Bash-Prompt-HOWTO/x361.html
        print(f"\033[{self.maptilegrid.height + 1}A", end='')

    def loop(self):
        """Main loop."""

        if VERBOSITY == "quiet":
            return

        while any([maptile.status is MapTileStatus.PENDING or
                   maptile.status is MapTileStatus.DOWNLOADING
                   for maptile in self.maptilegrid.flat()]):
            self.update()
            time.sleep(0.1)
        self.update()  # final update to show that we're all done

    def cleanup(self):
        """Moves the cursor back to the bottom after completion."""

        if VERBOSITY == "quiet" or VERBOSITY == "normal":
            return

        print(f"\033[{self.maptilegrid.height}B")


class MapTileGrid:
    """
    A grid of map tiles, kepts as a nested list such that indexing works via
    [x][y]. Manages the download and stitching of map tiles into a preliminary
    result image.
    """

    def __init__(self, maptiles):
        self.maptiles = maptiles
        self.width = len(maptiles)
        self.height = len(maptiles[0])
        self.image = None

    def __repr__(self):
        return f"MapTileGrid({self.maptiles})"

    @classmethod
    def from_georect(cls, georect, zoom):
        """Divides a GeoRect into a grid of map tiles."""

        southwest = georect.sw.to_maptile(zoom)
        northeast = georect.ne.to_maptile(zoom)

        maptiles = []
        for x in range(southwest.x, northeast.x + 1):
            col = []

            # it's correct to have northeast and southwest reversed here (with
            # regard to the outer loop) since y axis of the tile coordinates
            # points toward the south, while the latitude axis points due north
            for y in range(northeast.y, southwest.y + 1):
                maptile = MapTile(zoom, x, y)
                col.append(maptile)
            maptiles.append(col)

        return cls(maptiles)

    def at(self, x, y):
        """Accessor with wraparound for negative values: x/y<0 => x/y+=w/h."""

        if x < 0:
            x += self.width
        if y < 0:
            y += self.height
        return self.maptiles[x][y]

    def flat(self):
        """Returns the grid as a flattened list."""

        return [maptile for col in self.maptiles for maptile in col]

    def has_high_quality_imagery(self):
        """
        Checks if the corners of the grid are available two levels more zoomed
        in, which should make sure that we're getting high-quality imagery at
        the original zoom level.
        """

        zoom_delta = 2

        # since the at() function wraps around, [self.at(x, y) for x and y in
        # [0,-1]] selects the four corners of the grid, then for each of them a
        # "subgrid" is generated using .zoomed(), and for each of them, the
        # relevant corner is accessed through reuse of x and y
        corners = [self.at(x, y).zoomed(zoom_delta).at(x, y) for x in [0, -1] for y in [0, -1]]

        # check if they have all downloaded successfully
        all_good = True
        for c in corners:
            c.load()
            if c.status == MapTileStatus.ERROR:
                all_good = False
                break
        return all_good

    def download(self):
        """
        Downloads the constitudent tiles using a threadpool for performance
        while updating the progress indicator.
        """

        # set up progress indicator
        prog = ProgressIndicator(self)
        prog_thread = threading.Thread(target=prog.loop)
        prog_thread.start()

        # shuffle the download order of the tiles, this serves no actual purpose
        # but it makes the progress indicator look really cool!
        tiles = self.flat()
        random.shuffle(tiles)

        # download tiles using threadpool (2-10 times faster than
        # [maptile.load() for maptile in self.flat()]), see
        # https://docs.python.org/dev/library/concurrent.futures.html#threadpoolexecutor-example
        threads = max(self.width, self.height)
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
            {executor.submit(maptile.load): maptile for maptile in tiles}

        # retry failed downloads if fewer than 2% of tiles are missing (happens
        # frequently when pulling from naver map)
        missing_tiles = [maptile for maptile in self.flat() if maptile.status == MapTileStatus.ERROR]
        if 0 < len(missing_tiles) < 0.02 * len(self.flat()):
            if VERBOSITY != "quiet":
                print("Retrying missing tiles...")
            for maptile in missing_tiles:
                maptile.load()

        # finish up progress indicator
        prog_thread.join()
        prog.cleanup()

        # check if we've got everything now
        missing_tiles = [maptile for maptile in self.flat() if maptile.status == MapTileStatus.ERROR]
        if missing_tiles:
            raise RuntimeError(f"unable to load one or more map tiles: {missing_tiles}")

    def stitch(self):
        """
        Stitches the tiles together. Must not be called before all tiles have
        been loaded.
        """

        image = Image.new('RGB', (self.width * TILE_SIZE, self.height * TILE_SIZE))
        for x in range(0, self.width):
            for y in range(0, self.height):
                image.paste(self.maptiles[x][y].image, (x * TILE_SIZE, y * TILE_SIZE))
        self.image = image


class MapTileImage:
    """Image cropping, resizing and enhancement."""

    def __init__(self, image):
        self.image = image

    def save(self, path, quality=90):
        self.image.save(path, quality=quality)

    def crop(self, zoom, georect):
        """
        Crops the image such that it really only covers the area within the
        input GeoRect. This function must only be called once per image.
        """

        sw_x, sw_y = WebMercator.project(georect.sw, zoom)
        ne_x, ne_y = WebMercator.project(georect.ne, zoom)

        # determine what we'll cut off
        sw_x_crop = round(TILE_SIZE * (sw_x % 1))
        sw_y_crop = round(TILE_SIZE * (1 - sw_y % 1))
        ne_x_crop = round(TILE_SIZE * (1 - ne_x % 1))
        ne_y_crop = round(TILE_SIZE * (ne_y % 1))

        # left, top, right, bottom
        crop = (sw_x_crop, ne_y_crop, ne_x_crop, sw_y_crop)

        # snip snap
        self.image = ImageOps.crop(self.image, crop)

    def scale(self, width, height):
        """
        Scales an image. This can distort the image if width and height don't
        match the original aspect ratio.
        """

        # Image.LANCZOS apparently provides the best quality, see
        # https://pillow.readthedocs.io/en/latest/handbook/concepts.html#concept-filters
        self.image = self.image.resize((round(width), round(height)), resample=Image.LANCZOS)

    def enhance(self):
        """Slightly increases contrast and brightness."""

        # these values seem to work well for most images – a more adaptive
        # method would but nice, but it's not a priority
        contrast = 1.07
        brightness = 1.01

        self.image = ImageEnhance.Contrast(self.image).enhance(contrast)
        self.image = ImageEnhance.Brightness(self.image).enhance(brightness)

class Log:
    """
    A simplifying wrapper around the parts of the logging module that are
    relevant here, plus some minor extensions. Goal: Logging of warnings
    (depending on verbosity level), errors and exceptions on stderr, other
    messages (modulo verbosity) on stdout, and everything (independent of
    verbosity) in a logfile.
    """

    def __init__(self, logfile):

        # name and initialize logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        # via https://stackoverflow.com/a/36338212
        class LevelFilter(logging.Filter):
            def __init__(self, low, high):
                self.low = low
                self.high = high
                logging.Filter.__init__(self)
            def filter(self, record):
                return self.low <= record.levelno <= self.high

        # log errors (and warnings if a higher verbosity level is dialed in) on
        # stderr
        eh = logging.StreamHandler()
        if VERBOSITY == "quiet":
            eh.setLevel(logging.ERROR)
        else:
            eh.setLevel(logging.WARNING)
        eh.addFilter(LevelFilter(logging.WARNING, logging.CRITICAL))
        stream_formatter = logging.Formatter('%(message)s')
        eh.setFormatter(stream_formatter)
        self.logger.addHandler(eh)

        # log other messages on stdout if verbosity not set to quiet
        if VERBOSITY != "quiet":
            oh = logging.StreamHandler(stream=sys.stdout)
            if VERBOSITY == "deafening":
                oh.setLevel(logging.DEBUG)
            elif VERBOSITY == "verbose" or VERBOSITY == "normal":
                oh.setLevel(logging.INFO)
            oh.addFilter(LevelFilter(logging.DEBUG, logging.INFO))
            stream_formatter = logging.Formatter('%(message)s')
            oh.setFormatter(stream_formatter)
            self.logger.addHandler(oh)

        # log everything to file independent of verbosity
        if logfile is not None:
            fh = logging.FileHandler(logfile)
            fh.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s', datefmt='%Y-%m-%dT%H:%M:%S')
            fh.setFormatter(file_formatter)
            self.logger.addHandler(fh)

    def debug(self, s): self.logger.debug(s)
    def info(self, s): self.logger.info(s)
    def warning(self, s): self.logger.warning(s)
    def error(self, s): self.logger.error(s)
    def critical(self, s): self.logger.critical(s)

    def exception(self, e):
        """
        Logging of game-breaking exceptions, based on:
        https://stackoverflow.com/a/40428650
        """

        e_traceback = traceback.format_exception(e.__class__, e, e.__traceback__)
        traceback_lines = []
        for line in [line.rstrip('\n') for line in e_traceback]:
            traceback_lines.extend(line.splitlines())
        for line in traceback_lines:
            self.critical(line)
        sys.exit(1)

class Tweeter:
    """Basic class for tweeting images, a simple wrapper around tweepy."""

    def __init__(self, consumer_key, consumer_secret, access_token, access_token_secret):

        # for references, see:
        # http://docs.tweepy.org/en/latest/api.html#status-methods
        # https://developer.twitter.com/en/docs/tweets/post-and-engage/guides/post-tweet-geo-guide
        auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
        auth.set_access_token(access_token, access_token_secret)
        self.api = tweepy.API(auth)

    def get_location(self, geopoint):
        full_name = ""
        country = ""

        try:
            location = self.api.reverse_geocode(geopoint.lat, geopoint.lon)
            if location:
                full_name = location[0].full_name
                country = location[0].country
        except KeyError:

            # can apparently sometimes occur if twitter doesn't have geodata
            # for the selected location
            pass

        return (full_name, country)

    def upload(self, path):
        """Uploads an image to Twitter."""

        return self.api.media_upload(path)

    def tweet(self, text, media, geopoint=None):
        if geopoint:
            self.api.update_status(
                text,
                media_ids=[media.media_id],
                lat=geopoint.lat,
                long=geopoint.lon,
                display_coordinates=True
            )
        else:
            self.api.update_status(text, media_ids=[media.media_id])

def main():
    global VERBOSITY
    global LOGGER

    # handle potential cli arguments
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--help', action='help', default=argparse.SUPPRESS, help=argparse._('show this help message and exit'))  # override default help argument so that only --help (and not -h) can call
    parser.add_argument('config_path', metavar='CONFIG_PATH', type=str, nargs='?', default="config.ini", help='config file to use instead of looking for config.ini in the current working directory')
    parser.add_argument('-p', '--point', dest='point', metavar='LAT,LON', type=str, help='a point, e.g. \'37.453896,126.446829\', that will override your configuration (if its latitide is negative, option parsing might throw an error – simply write -p="LAT,LON" in that case)')  # https://stackoverflow.com/questions/16174992/cant-get-argparse-to-read-quoted-string-with-dashes-in-it
    parser.add_argument('-m', '--max-meters-per-pixel', dest='max_meters_per_pixel', metavar='N', type=float, help='a maximum meters per pixel constraint that will override your configuration')
    parser.add_argument('-w', '--width', dest='width', metavar='N', type=float, help='width of the depicted area in meters, will override your configuration')
    parser.add_argument('-h', '--height', dest='height', metavar='N', type=float, help='height of the depicted area in meters, will override your configuration')
    parser.add_argument('--image_width', dest='image_width', metavar='N', type=float, help='width of the result image, will override your configuration (where you can also find an explanation of how this option interacts with the -m, -w, and -h options)')
    parser.add_argument('--image_height', dest='image_height', metavar='N', type=float, help='height of the result image, will override your configuration (where you can also find an explanation of how this option interacts with the -m, -w, and -h options)')
    args = parser.parse_args()

    # load configuration either from config.ini or from a user-supplied file
    # (the latter option is handy if you want to run multiple instances of
    # ærialbot with different configurations)
    config = ConfigObj(args.config_path, unrepr=True)

    # first of all, set up logging at the correct verbosity (and make the
    # verbosity available globally since it's needed for the progress indicator)
    VERBOSITY = config['GENERAL']['verbosity']
    logfile = config['GENERAL']['logfile']
    LOGGER = Log(logfile)

    ############################################################################

    # copy the configuration into variables for brevity
    tile_path_template = config['GENERAL']['tile_path_template']
    image_path_template = config['GENERAL']['image_path_template']

    tile_url_template = config['GEOGRAPHY']['tile_url_template']

    shapefile = config['GEOGRAPHY']['shapefile']
    point = config['GEOGRAPHY']['point']

    width = config['GEOGRAPHY']['width']
    height = config['GEOGRAPHY']['height']

    image_width = config['IMAGE']['image_width']
    image_height = config['IMAGE']['image_height']

    max_meters_per_pixel = config['IMAGE']['max_meters_per_pixel']

    apply_adjustments = config['IMAGE']['apply_adjustments']
    image_quality = config['IMAGE']['image_quality']

    consumer_key = config['TWITTER']['consumer_key']
    consumer_secret = config['TWITTER']['consumer_secret']
    access_token = config['TWITTER']['access_token']
    access_token_secret = config['TWITTER']['access_token_secret']

    tweet_text = config['TWITTER']['tweet_text']
    include_location_in_metadata = config['TWITTER']['include_location_in_metadata']

    # override configured options with values supplied via the cli
    if args.point:
        point = tuple(map(float, args.point.split(",")))
    if args.max_meters_per_pixel:
        max_meters_per_pixel = args.max_meters_per_pixel
    if args.width:
        width = args.width
    if args.height:
        height = args.height
    if args.image_width:
        image_width = args.image_width
    if args.image_height:
        image_height = args.image_height

    ############################################################################

    LOGGER.info("Processing configuration...")

    # handle tile url special cases
    if tile_url_template == "googlemaps":
        tile_url_template = "https://khms2.google.com/kh/v={google_maps_version}?x={x}&y={y}&z={zoom}"
    elif tile_url_template == "navermap":
        tile_url_template = "https://map.pstatic.net/nrb/styles/satellite/{naver_map_version}/{zoom}/{x}/{y}.jpg?mt=bg"

    if "{google_maps_version}" in tile_url_template:
        LOGGER.info("Determining current Google Maps version and patching tile URL template...")

        # automatic fallback: current as of July 2021, will likely continue
        # to work for at least a while
        google_maps_version = '904'

        try:
            google_maps_page = requests.get("https://www.google.com/maps/", headers={'User-Agent': USER_AGENT}).content
            match = re.search(rb'khms0\.google\.com\/kh\/v\\u003d([0-9]+)', google_maps_page)
            if match:
                google_maps_version = match.group(1).decode('ascii')
                LOGGER.debug(google_maps_version)
            else:
                LOGGER.warning(f"Unable to extract current version, proceeding with outdated version {google_maps_version} instead.")
        except requests.RequestException as e:
            LOGGER.warning(f"Unable to load Google Maps, proceeding with outdated version {google_maps_version} instead.")

        tile_url_template = tile_url_template.replace("{google_maps_version}", google_maps_version)

    if "{naver_map_version}" in tile_url_template:
        LOGGER.info("Determining current Naver Map version and patching tile URL template...")
        naver_map_version = requests.get("https://map.pstatic.net/nrb/styles/satellite.json", headers={'User-Agent': USER_AGENT}).json()["version"]
        LOGGER.debug(naver_map_version)
        tile_url_template = tile_url_template.replace("{naver_map_version}", naver_map_version)

    MapTile.tile_path_template = tile_path_template
    MapTile.tile_url_template = tile_url_template

    # process max_meters_per_pixel setting
    if image_width is None and image_height is None:
        assert max_meters_per_pixel is not None
    elif image_height is None:
        max_meters_per_pixel = (max_meters_per_pixel or 1) * (width / image_width)
    elif image_width is None:
        max_meters_per_pixel = (max_meters_per_pixel or 1) * (height / image_height)
    else:
        # if both are set, effectively use whatever imposes a tighter constraint
        if width / image_width <= height / image_height:
            max_meters_per_pixel = (max_meters_per_pixel or 1) * (width / image_width)
        else:
            max_meters_per_pixel = (max_meters_per_pixel or 1) * (height / image_height)

    # process image width and height for scaling
    if image_width is not None or image_height is not None:
        if image_height is None:
            image_height = height * (image_width / width)
        elif image_width is None:
            image_width = width * (image_height / height)

    # whether to enable or disable tweeting
    tweeting = all(x is not None for x in [consumer_key, consumer_secret, access_token, access_token_secret])

    ############################################################################

    if shapefile is None and point is None:
        raise RuntimeError("neither shapefile path nor point configured")
    elif point is None:
        LOGGER.info("Loading shapefile...")
        LOGGER.debug(shapefile)
        shape = GeoShape(shapefile)

    tries = 0
    while True:
        tries += 1
        if tries > 10:
            raise RuntimeError("too many retries – maybe there's no internet connection? either that, or your max_meters_per_pixel setting is too low")

        if point is None:
            LOGGER.info("Generating random point within shape...")
            p = shape.random_geopoint()
        else:
            LOGGER.info("Using configured point instead of shapefile...")
            p = GeoPoint(point[0], point[1])
        LOGGER.debug(p)

        LOGGER.info("Computing required tile zoom level at point...")
        zoom = p.compute_zoom_level(max_meters_per_pixel)
        LOGGER.debug(zoom)

        LOGGER.info("Generating rectangle with your selected width and height around point...")
        rect = GeoRect.around_geopoint(p, width, height)
        LOGGER.debug(rect)

        LOGGER.info("Turning rectangle into a grid of map tiles at the required zoom level...")
        grid = MapTileGrid.from_georect(rect, zoom)
        LOGGER.debug(grid)

        # no need to do check quality if the point was set manually – clearly
        # the user won't mind low-quality imagery
        if point is not None:
            break

        LOGGER.info("Checking quality of imagery available for the map tile grid...")
        if not grid.has_high_quality_imagery():
            LOGGER.info("Not good enough, let's try this again...")
        else:
            LOGGER.info("Lookin' good, let's proceed!")
            break

    ############################################################################

    LOGGER.info("Downloading tiles...")
    grid.download()

    LOGGER.info("Stitching tiles together into an image...")
    grid.stitch()
    image = MapTileImage(grid.image)

    LOGGER.info("Cropping image to match the chosen area width and height...")
    LOGGER.debug((width, height))
    image.crop(zoom, rect)

    if image_width is not None or image_height is not None:
        LOGGER.info("Scaling image...")
        LOGGER.debug((image_width, image_height))
        image.scale(image_width, image_height)

    if apply_adjustments:
        LOGGER.info("Enhancing image...")
        image.enhance()

    LOGGER.info("Saving image to disk...")
    image_path = image_path_template.format(
        datetime=datetime.today().strftime("%Y-%m-%dT%H.%M.%S"),
        latitude=p.lat,
        longitude=p.lon,
        width=width,
        height=height,
        max_meters_per_pixel=max_meters_per_pixel,
        xmin=grid.at(0, 0).x,
        xmax=grid.at(0, 0).x+grid.width,
        ymin=grid.at(0, 0).y,
        ymax=grid.at(0, 0).y+grid.height,
        zoom=zoom,
        georect=f"sw{rect.sw.lat},{rect.sw.lon}ne{rect.ne.lat},{rect.ne.lon}"
    )
    LOGGER.debug(image_path)
    d = os.path.dirname(image_path)
    if not os.path.isdir(d):
        os.makedirs(d)
    image.save(image_path, image_quality)

    ############################################################################

    if tweeting:
        LOGGER.info("Connecting to Twitter...")
        tweeter = Tweeter(consumer_key, consumer_secret, access_token, access_token_secret)

        #if "location_full_name" in tweet_text or "location_country" in tweet_text:
        LOGGER.info("Getting location information from Twitter...")
        (location_full_name, location_country) = tweeter.get_location(p)
        LOGGER.debug((location_full_name, location_country))

        osm_url = f"https://www.openstreetmap.org/#map={zoom}/{p.lat}/{p.lon}"
        googlemaps_url = f"https://www.google.com/maps/@{p.lat},{p.lon},{zoom}z"

        LOGGER.info("Uploading image to Twitter...")
        media = tweeter.upload(image_path)

        LOGGER.info("Sending tweet...")
        tweet_text = tweet_text.format(
            latitude=p.lat,
            longitude=p.lon,
            point_fancy=p.fancy(),
            osm_url=osm_url,
            googlemaps_url=googlemaps_url,
            location_full_name=location_full_name,
            location_country=location_country
        )
        LOGGER.debug(tweet_text)
        if include_location_in_metadata:
            tweeter.tweet(tweet_text, media, p)
        else:
            tweeter.tweet(tweet_text, media)

    LOGGER.info("All done!")


if __name__ == "__main__":

    # log all exceptions
    try:
        main()
    except Exception as e:
        LOGGER.exception(e)
