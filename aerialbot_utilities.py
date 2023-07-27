from geopy.geocoders import Nominatim
import requests
import json

def get_location_nominatim(geopoint):
    full_name = ""
    country = ""

    try:
        geolocator = Nominatim(user_agent="aerialbot")
        location = geolocator.reverse((geopoint.lat, geopoint.lon), language='th', zoom=14)
        full_name = location.address
        country = location.raw['address']['country']

    except KeyError:

        # can apparently sometimes occur if twitter doesn't have geodata
        # for the selected location
        pass

    return (full_name, country)

def get_location_googlemaps(geopoint, google_maps_reverse_geocoding_language, google_maps_api_key):
    full_name = ""
    country = ""

    try:
        url = "https://maps.googleapis.com/maps/api/geocode/json?latlng={},{}&result_type=administrative_area_level_1|administrative_area_level_2|administrative_area_level_3&language={}&key={}".format(geopoint.lat,geopoint.lon,google_maps_reverse_geocoding_language,google_maps_api_key)
        response = requests.get(url)
        if response.status_code == 200:
            data = json.loads(response.content)
            subdistrict = data["results"][0]["address_components"][0]["long_name"]
            district = data["results"][0]["address_components"][1]["long_name"]
            province = data["results"][0]["address_components"][2]["long_name"]
            country = data["results"][0]["address_components"][3]["long_name"]
            full_name = subdistrict+" "+district+" "+province
            country = country

    except KeyError:

        # can apparently sometimes occur if twitter doesn't have geodata
        # for the selected location
        pass

    return (full_name, country)
