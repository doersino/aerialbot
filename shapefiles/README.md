This directory contains some shapefiles one might feel inclined to use for a specific ærialbot-based Twitter bot.

## Sources

These shapefiles are from the following sources, their authors have mandated attribution as shown.

| Folder | Source |  Notes | License/Attribution |
| --- | --- | --- | --- |
| `usa/` | [🔗](https://www.census.gov/geographies/mapping-files/time-series/geo/carto-boundary-file.html) | Used `cb_2018_us_nation_5m.zip` | Public domain |
| `southkorea/` | [🔗](https://github.com/southkorea/southkorea-maps/blob/master/kostat/2012/shp/skorea-provinces-2012.shp) | Used `kostat/2012/shp/skorea-provinces-2012.shp` | "Free to share or remix" [📝](https://github.com/southkorea/southkorea-maps#license) |
| `germany/` | [🔗](https://gdz.bkg.bund.de/index.php/default/catalog/product/view/id/766/s/gebietseinheiten-1-2-500-000-ge2500/category/8/?___store=default) | Used `ge2500.gk3.shape.zip` | "Datenlizenz Deutschland – Namensnennung – Version 2.0" [📝](https://www.govdata.de/dl-de/by-2-0) |
| `japan/` | [🔗](https://www.gsi.go.jp/kankyochiri/gm_japan_e.html) |  Used `coastl_jpn.shp` from `gm-jpn-all_u_2_2.zip` | "Source: Geospatial Information Authority of Japan website (https://www.gsi.go.jp/kankyochiri/gm_japan_e.html)" [📝](https://www.gsi.go.jp/ENGLISH/page_e30286.html) |
| `world/` | [🔗](https://tapiquen-sig.jimdofree.com/english-version/free-downloads/world/) | Used `World_Countries.rar` | "Shape downloaded from http://tapiquen-sig.jimdo.com. Carlos Efraín Porto Tapiquén. Orogénesis Soluciones Geográficas. Porlamar, Venezuela, 2015." [📝](https://tapiquen-sig.jimdofree.com/english-version/free-downloads/world/) |


## Processing

Most of these Shapefiles have been processed to fit ærialbot's needs, which are

1. that they contain a single layer
2. with a single record
3. of type `POLYGON`
4. whose points are notated as longitude-latitude pairs (CRS: `+proj=longlat`).

In order to coerce the original versions of the shapefiles (which are kept in `orig/` subdirectories just in case future changes are required) to match these conventions, the excellent [mapshaper web interface](https://mapshaper.org) was used as follows.

1. Upload all relevant files (`.dbf`, `.prj`, `.shp`, and `.shx`).
2. Simplify to desired level (depends on input granularity, often around 10%) with visual slider tool – on the [command line](https://github.com/mbloch/mapshaper/wiki/Command-Reference), this could be achieved via the `-simplify` flag.
3. If polygon overlaps are present: `mapshaper -clean`.
4. Fix projection if required via `mapshaper -proj crs=wgs84 target=LAYER_NAME` (the important bit is `+proj=longlat`, which is implied by `wgs84`).
5. If it's a polyline: `mapshaper -polygon`.
6. Optionally: Remove features/regions you don't want (like Antarctica or large bodies of water, for example) via the visual tools.
7. Turn all features/states/provinces/counties into a single feature: `mapshaper -dissolve`.

Some useful exploration steps using `pyshp` in the Python REPL:

```python
>>> import shapefile
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
