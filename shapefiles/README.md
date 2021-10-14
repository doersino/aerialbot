This directory contains some shapefiles one might feel inclined to use for a specific ærialbot-based Twitter bot.

## Sources

These shapefiles are from the following sources, their authors have mandated attribution as shown.

| Folder | Source |  Notes | License/Attribution |
| --- | --- | --- | --- |
| `usa/` | [🔗](https://www.census.gov/geographies/mapping-files/time-series/geo/carto-boundary-file.html) | Used `cb_2018_us_state_5m.zip`. | Public domain |
| `southkorea/` | [🔗](https://github.com/southkorea/southkorea-maps/blob/master/kostat/2012/shp/skorea-provinces-2012.shp) | Used `kostat/2012/shp/skorea-provinces-2012.shp`. | "Free to share or remix" [📝](https://github.com/southkorea/southkorea-maps#license) |
| `germany/` | [🔗](https://gdz.bkg.bund.de/index.php/default/catalog/product/view/id/766/s/gebietseinheiten-1-2-500-000-ge2500/category/8/?___store=default) | Used `ge2500.gk3.shape.zip`. | "Datenlizenz Deutschland – Namensnennung – Version 2.0" [📝](https://www.govdata.de/dl-de/by-2-0) |
| `japan/` | [🔗](https://www.gsi.go.jp/kankyochiri/gm_japan_e.html) |  Used `coastl_jpn.shp` from `gm-jpn-all_u_2_2.zip`. | "Source: Geospatial Information Authority of Japan website (https://www.gsi.go.jp/kankyochiri/gm_japan_e.html)" [📝](https://www.gsi.go.jp/ENGLISH/page_e30286.html) |
| `world/` | [🔗](https://tapiquen-sig.jimdofree.com/english-version/free-downloads/world/) | Used `World_Countries.rar`. | "Shape downloaded from http://tapiquen-sig.jimdo.com. Carlos Efraín Porto Tapiquén. Orogénesis Soluciones Geográficas. Porlamar, Venezuela, 2015." [📝](https://tapiquen-sig.jimdofree.com/english-version/free-downloads/world/) |
| `denmark/` | [🔗](https://download.kortforsyningen.dk/content/danmarks-administrative-geografiske-inddeling-1500000) | Used `REGION.SHP` from `DAGI500_SHAPE_UTM32-EUREF89.zip`. | "Source: Styrelsen for Dataforsyning og Effektivisering website  https://download.kortforsyningen.dk/content/danmarks-administrative-geografiske-inddeling-1500000" [📝](https://download.kortforsyningen.dk/content/danmarks-administrative-geografiske-inddeling-1500000) |
| `thailand/` | [🔗](https://data.opendevelopmentmekong.net/en/dataset/thailand-country-boundary) | Used `tha_admbnda_adm0_rtsd_20190221.zip`. | "Source: Open Development Mekong website  https://data.opendevelopmentmekong.net/en/dataset/thailand-country-boundary" [📝](https://data.opendevelopmentmekong.net/en/dataset/thailand-country-boundary) |
| `newyorkcity/` | [🔗](https://data.cityofnewyork.us/City-Government/Borough-Boundaries/tqmj-j8zm) | Exported from website as shapefile. | Public domain, "Data Provided By Department of City Planning (DCP)" [📝](https://data.cityofnewyork.us/City-Government/Borough-Boundaries/tqmj-j8zm#About) |
| `urbanareas/` | [🔗](https://earthworks.stanford.edu/catalog/stanford-xg070wh7159) | "World Urban Areas, 1:10 million (2012) [...] This polygon shapefile contains the boundaries of urban areas with dense areas of human habitation worldwide derived from 2002-2003 MODIS satellite data at 1 km resolution." Preferred over a [similar file based on LandScan data](https://earthworks.stanford.edu/catalog/stanford-yk247bg4748) since that one doesn't seem to jive with `pyshp` (for some records a "UserWarning: Shapefile shape has invalid polygon: found orphan hole (not contained by any of the exteriors); interpreting as exterior" is created, which eventually leads to an exception) and is sorta blocky. Both also available [here](https://github.com/nvkelso/natural-earth-vector/tree/master/10m_cultural). | "This item is in the public domain. There are no restrictions on use." [📝](https://earthworks.stanford.edu/catalog/stanford-xg070wh7159) |

If you're looking for a shapefile of a country or region that's not provided here, have some advice:

* You can probably find one fairly easily by searching for "REGION shapefile".
* The shapefiles found on the following sites that frequently crop up in search results aren't suitable for use with ærialbot:
    * https://www.eea.europa.eu/data-and-maps/data/eea-reference-grids-2 (see [here](https://github.com/doersino/aerialbot/issues/4) for an explanation)
    * http://download.geofabrik.de (they contain a bunch of features, but crucially *not* country outlines)
* However, the shapefiles found in these places seem to be quite good:
    * https://gadm.org/download_country_v3.html (select country, click on "Shapefile" link, then use the files named `gadm36_XXX_0`)
    * https://globalmaps.github.io/national.html (click "Download National/Regional data")
* National governments often provide publicly available shapefiles:
    * https://www.census.gov/geographies/mapping-files/time-series/geo/carto-boundary-file.html (for regions within the US)
    * https://gdz.bkg.bund.de/index.php/default/catalog/product/view/id/766/s/gebietseinheiten-1-2-500-000-ge2500/category/8/?___store=default (for regions within Germany)
    * https://www.gsi.go.jp/kankyochiri/gm_japan_e.html (for regions within Japan)
    * ...
* Use [mapshaper.org](https://mapshaper.org) as described below to inspect and, if required, process your shapefile.


## Processing

Most of these Shapefiles have been processed to fit ærialbot's needs, which are

1. that they contain a single layer
2. with one or more records/shapes
3. each of type `POLYGON`
4. whose points are notated as longitude-latitude pairs (CRS: `+proj=longlat`).

In order to coerce the original versions of the shapefiles (which are kept in `orig/` subdirectories just in case future changes are required) to match these conventions, the excellent [mapshaper web interface](https://mapshaper.org) was used as follows.

1. Upload all relevant files (`.dbf`, `.prj`, `.shp`, and `.shx`).
2. Simplify to desired level (depends on input granularity, often around 10%) with visual slider tool – on the [command line](https://github.com/mbloch/mapshaper/wiki/Command-Reference), this could be achieved via the `-simplify` flag.
3. If polygon overlaps are present: `mapshaper -clean`.
4. Fix projection if required (run `mapshaper info` to check) via `mapshaper -proj crs=wgs84 target=LAYER_NAME` (the important bit is `+proj=longlat`, which is implied by `wgs84`).
5. If it's a polyline (run `mapshaper info` to check): `mapshaper -polygons`.
6. Optionally: Remove features/regions you don't want (like Antarctica or large bodies of water, for example) via the visual tools.
7. Optionally: Remove any extraneous data: `mapshaper -drop fields=*`.
8. ~~Turn all features/states/provinces/counties into a single feature: `mapshaper -dissolve`.~~
 *This used to be required – for simplicity's sake, ærialbot only supported single-shape Shapefiles in its infancy, but setting up [@citiesatanangle](https://twitter.com/citiesatanangle) required adding support for multiple shapes. Turns out: Due to implementation details, random point generation is almost always more efficient for multi-shape Shapefiles!*
9. Export.

Some useful exploration steps using `pyshp` in the Python REPL:

```python
>>> import shapefile
>>> sf = shapefile.Reader(INSERT_SHAPEFILE_PATH_HERE)
>>> shapes = sf.shapes()
>>> len(shapes)
1
>>> sf.shapeTypeName
'POLYGON'
>>> shapes[0].shapeTypeName
'POLYGON'
>>> len(shapes[0].points)
30901
```
