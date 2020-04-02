# ærialbot

*A simple bot that tweets geotagged aerial imagery of a random location in the world.*

#### ~~Check out [@americasquared](https://twitter.com/americasquared), an instance of ærialbot that tweets a satellite view of a randomly selected square mile of the United States every 4 hours!~~ Twitter has suspended this account, and it seems as though they won't permit any ærialbot instances – but you can still use this tool locally. Read on to find how how. Bummer, though. 😕

![One square mile each, somewhere in the United Sates, centered around (from top left to bottom right): 31.056747601478456,-89.61225567756193; 26.44943037843055,-97.69999657039938; 39.32223925968352,-95.06302508257909; 33.830621832157895,-102.7345327711916; 46.149781016546264,-108.95292330126662; 20.755048248172997,-156.98230879693344; 41.21859102806858,-83.97344375576749; 36.89466223259036,-89.52366337871948; 36.07100491499848,-115.26963797305373; 42.87888803844798,-113.90920385179305; 33.90737575723908,-113.46512478011427; 45.009510867796266, -117.01147828430616](example.jpg)

In a bit more detail, whenever you run ærialbot, it...

* **loads a shapefile** from disk,
* generates a **random point**꙳ within the bounds of this shape,
* figures out **which map tiles need to be downloaded** to cover a certain area around the point in sufficient꙳ detail,
* **downloads those map tiles** from a provider of your choice real fast (a threadpool is involved!),
* **stitches** them together and **crops** the resulting image to precisely match the configured area,
* **saves** that to disk,
* and **tweets** the image, optionally with geo information.

If ærialbot was a cake, the icing would be its extensive **configurabitlity** and **logging** functionality.


## Features

Here's why ærialbot is a [Good Bot](https://www.reddit.com/r/OutOfTheLoop/comments/6oca11/what_is_up_with_good_bot_bad_bot_comments/):

* **Configurability:** Take a look at `config.sample.ini` – you can supply your own shapefile (or instead define a fixed point), control output verbosity, choose from different tile imagery providers, define the filenames of the result images, scale them to your preferred size, define the text of the tweet, and more!
* ꙳**Correctness:** Because neighboring meridians are closer at the poles than at the equator, uniformly sampling the allowable range of latitudes would bias the generated random points toward the poles. Instead, ærialbot makes sure they are distributed with regard to surface area. For the same reason (plus the Mercator projection), the number of map tiles required to cover an area depends on the latitide – ærialbot accounts for this, too.
* ꙳**Automatic zoom level determination:** Simply define the dimensions of the desired area around the generated point – ærialbot will then take care of dialing in a (more than) sufficent zoom level.
* **Comes with batteries included:** The `shapefiles/` directory contains a number of shapefiles to get you started, along with a guide on preparing further shapefiles for use with ærialbot.
* **Tile grabbing performance:** Multiple map tiles are downloaded in parallel, and there's a snazzy progress indicator (see below) to show this off.
* **Geotagging:** Tweets will be geotagged with the precise location – you can disable this, of course.
* **Logging:** Keeps a log file – whether that's for debugging or reminiscing is your call. Again, you can disable this easily.

![What is this? It's a progress indicator. What does it do? It indicates progress.](demo.gif)

(Side note: If that's all a bit much for you, check out [gomati](https://github.com/doersino/gomati), my previous (and much more basic) shot at a Google Maps tile downloader and stitcher.)


## Usage

### Setup

Being a good [Python 3](https://www.python.org) citizen, ærialbot uses `venv` to avoid dependency hell. Run the following commands to get it installed on your system:

```
$ git clone https://github.com/doersino/aerialbot
$ python3 -m venv aerialbot
$ cd aerialbot
$ source bin/activate
$ pip3 install -r requirements.txt
```

(To deactivate the virtual enviroment, run `deactivate`.)


### Configuration

Copy `config.sample.ini` to `config.ini`, open it and modify it based on the (admittedly wordy) instructions in the comments.


### Running

Once you've set everything up and configured it to your liking, run:

```
$ python3 aerialbot.py
```

That's basically it! If you want your bot to tweet at predefined intervals, use `cron`, [`runwhen`](http://code.dogmap.org/runwhen/) or a similar tool.

*Pro tip:* If you want to host multiple instances of ærialbot, you don't need multiple copies of the code – multiple config files suffice: simply run `python3 aerialbot.py one-of-your-config-files.ini`.


## FAQ

### Why the name?

Because it's cute and I like the "æ" ligature. In fact, before Twitter suspended @americasquared, I was planning on commissioning [@smolrobots](https://twitter.com/smolrobots/status/1224096411056320514) to draw a little mascot – maybe a satellite with a camera, or planet earth taking a selfie.

### Why did you make this tool?

Because satellite imagery [can be extremely beautiful](https://earthview.withgoogle.com), and I was looking for a way of regularly receiving high-resolution satellite views of arbitrary locations such as [the center pivot irrigation farms of the American heartland](http://www.thegreatamericangrid.com/archives/1441) in my Twitter timeline.

### Something is broken – can you fix it?

Possibly. Please feel free to [file an issue](https://github.com/doersino/aerialbot/issues) – I'll be sure to take a look!


## Future Work

*Due to Twitter's suspension of @americasquared, these TODOs are now shelved indefinitely.*

* Retry tile downloads once or twice if they fail – sometimes, packets just get lost forever even when using TCP, and it would be a shame to give up because of that if a bunch of tiles have already been downladed successfully.
* In addition to `GeoShape.random_geopoint`, also implement a `Shape.random_edge_geopoint` function for generating points on the edge of polygons (and polylines), and make it available via a config setting. This would 1. help test whether a given shapefile is accurate (and whether its projection is suitable), and 2. enable tweeting images of coasts or border regions, which might be interesting.
* Split `aerialbot.py` up into multiple modules, take inspiration from [here](https://github.com/joaquinlpereyra/twitterImgBot).
* Set up a...
    * ... Japan-focused instance at @nihonmugenkei with screen name "日本∞景", i.e. "infinite views of Japan" in reference to [Hiroshige's series of 100 woodblock prints](https://en.wikipedia.org/wiki/One_Hundred_Famous_Views_of_Edo).
    * ... Korea-focused instance at @baekmanpyeong with screen name "백만평" in reference to the traditional area unit [Pyeong](https://en.wikipedia.org/wiki/Pyeong), which corresponds to 3.3058 m², meaning that a square of a million (baekman) Pyeong would be 1.818 kilometers on each side.
    * ... "worldwide" instance, maybe around 5 kilometers square.
    * ...n instance based on a shapefile containing the world's train tracks, if that's even publicly available. Perhaps this would benefit from implementing a rotation feature.
