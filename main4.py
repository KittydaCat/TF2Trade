import requests
import sku.parser
from datetime import date, timedelta
import time
import json
import logging


class PriceGrabber:

    def __init__(self, token: str, api_key: str, days_until_old: float = 5):

        # load the necessary secrets
        self.token = token
        self.api_key = api_key

        # start up communication with price.tf and load the date to check accuracy

        self.price_auth_token = requests.post("https://api2.prices.tf/auth/access").json()["accessToken"]

        self.today = date.today()
        self.days_until_old = days_until_old

        # record the last time backpack.tf snapshot was accessed
        self.last_bp_sc = 0

    def check_price(self, name: str = None, item_sku: str = None, retries: int = 3, rq_update: bool = True):

        # if a name is supplied
        if name:

            # convert name to a sku
            item_sku = sku.parser.Sku.name_to_sku(name)

        # request a price check from price.tf
        # supply the reformatted sku and the auth token
        page = requests.get("https://api2.prices.tf/prices/" + item_sku.replace(';', '%3B'),
                            headers={"Authorization": f"Bearer {self.price_auth_token}"})

        match page.status_code:

            # if the page loads successfully
            case 200:

                # get the price json
                price = page.json()

                # if we can request an update and if the query is over the set acceptable days old
                if (rq_update and self.today > date.fromisoformat(price["updatedAt"][:10])
                        + timedelta(days=self.days_until_old)):

                    # request an update
                    requests.post('https://api2.prices.tf/prices/{0}/refresh'.format(item_sku.replace(';', '%3B')),
                                  headers={"Authorization": f"Bearer {self.price_auth_token}"})

                    logging.info(f"Requested price update on {name}")

            # if Error: Unauthorized
            case 401:

                logging.info("Auth faded")
                self.price_auth_token = requests.post("https://api2.prices.tf/auth/access").json()["accessToken"]

            # if our item is not priced
            case 404:

                # print(f"Item price for {name} not found. Requesting price check")

                # request for it to be priced
                requests.post(f"https://api2.prices.tf/prices/{item_sku.replace(';', '%3B')}/refresh",
                              headers={"Authorization": f"Bearer {self.price_auth_token}"})

                # do not try to price it again rn
                retries = 0

            # if Error: Too Many Requests
            case 429:

                print(f"Too many requests waiting for {int(page.headers['retry-after'])/1000} seconds")

                time.sleep(int(page.headers['retry-after'])/1000)

            # if the page fails for some other reason
            case _:

                logging.info(f"Error {page.status_code}: Price check failed on {name} with an sku of {item_sku}")

        # if the page fails to load
        if not page.ok:

            # if we have reloading retries left
            if retries:

                # print("Retrying")

                # retry loading the page
                return self.check_price(name=name, item_sku=item_sku, retries=retries - 1, rq_update=rq_update)

            # if we do not have any retries left
            else:

                return None

        # if the page loaded successfully
        else:

            return price

    def grab_listings(self, item_name: str, retries: int = 3, fails: int = 0):

        print(item_name)

        # wait until backpack.tf un-cashes the listings

        if (time_till_un_cash := (self.last_bp_sc + 60) - time.time()) > 0:  # if we have to wait

            print(f"Too many requests: Cannot request for {int(time_till_un_cash)} seconds")
            time.sleep(time_till_un_cash)

        # make a request to the backpack.tf API
        page = requests.get("https://backpack.tf/api/classifieds/listings/snapshot",
                            data={'sku': item_name, 'appid': '440', 'token': self.token})

        # update the time btw API calls
        self.last_bp_sc = time.time()

        match page.status_code:

            # if the request is successful
            case 200:

                # get the response payload
                response = page.json()

            # if Error: Too many requests
            case 429:

                # dump info
                print(page)
                print(page.content)
                print(page.reason)
                print(page.text)

                # wait the retry after length
                print(f"Too many requests waiting for {int(page.headers['retry-after'])} seconds")

                # FYI the retry-after header is always returned as 6
                time.sleep(int(page.headers['retry-after']))

            # if an unknown error occurs
            case _:

                # log it
                print(f"Listing lookup failed on {item_name} with a code of {page.status_code}")
                print(page.reason)

        # if the page failed to load
        if not page.ok:

            # if we have retries
            if retries > 0:

                # retry loading
                return self.grab_listings(item_name, retries=retries - 1, fails=fails)

            # if we have no retries left
            else:

                # give up
                return None

        # if our listings are not for the correct weapon
        if response['sku'] != item_name:

            print("Got wrong name")

            # try to grab the correct weapon
            return self.grab_listings(item_name)

        # if we were returned the correct weapon
        else:

            # check is any listings were returned
            if "listings" in response:

                return response["listings"]

            else:

                return None

    def sort_listings(self, intent: str, item_name: str, banned_attributes: tuple = ()):
        # if the intent is 'sell' return the highest offering sell listing
        # if the intent is 'buy' return the cheapest buy listing

        # load all the listings for an item
        listings = self.grab_listings(item_name)

        # if we don't have listings return nothing
        if listings is None:
            return None

        # create a list for any listing the fits out intent and without any banned attributes
        valid_listings = []

        # loop thru the listings we were provided
        for listing in listings:

            # if the listing intent matches our intent
            if listing['intent'] == intent:

                # and if the listing has any banned attributes by comparing each attribute with the banned ones

                # loops thru all the attributes and creates a list
                # if the defindex, in the attribute, is in banned attributes a True is returned
                # if any Trues are in the list a banned attribute is detected
                if True not in [(int(attribute['defindex']) in banned_attributes) for attribute in
                                listing['item']['attributes']]:

                    # and if the listing is not in usd
                    if 'usd' not in listing['currencies']:

                        # add it to the valid listing
                        valid_listings.append(listing)

                    else:

                        logging.info(f"{listing['currencies']}")

        # if we have valid listings
        if valid_listings:

            # if we want to find sell listings
            if intent == 'sell':

                # return the cheapest sell listing
                return sorted(valid_listings, key=lambda x: x['price'])[0]

            # if we want to find buy listings
            if intent == 'buy':

                # return the most profitable listing
                return sorted(valid_listings, key=lambda x: x['price'])[-1]

        # if there are no valid listings
        else:

            return None

    def price_ks_flips(self, quality: str = ""):
        # use price.tf to quickly get an idea of ks profitability

        # if we have a quality append a space to the end for easy concatenation
        if quality != "":

            quality += " "

        with open("killstreakable_weapons_names.txt", encoding='utf-8') as file:
            weapon_names = file.read().split("\n")

        # remove any blank lines from the list of weapons and set up the keys for our profit dict
        flips = dict.fromkeys([weapon for weapon in weapon_names if weapon != ""])

        # loop thru each weapon and find how profitable ks flipping it is
        for flip in flips:

            # load the prices
            weapon_json = self.check_price(name=f"{quality} Killstreak {flip}")
            kit_json = self.check_price(name=f"Non-Craftable {quality}Killstreak {flip} Kit")

            # if either of the price check fails
            if weapon_json is None or kit_json is None:
                logging.info(f"Price lookup failed on {flip}")

                flips[flip] = None

                continue

            # scrape the kit and ks weapon prices
            # TODO check this code
            kit_price = kit_json['sellKeyHalfScrap'] if kit_json['sellKeys'] else kit_json['sellHalfScrap']
            weapon_price = weapon_json['buyKeyHalfScrap'] if weapon_json['buyKeys'] else weapon_json['buyHalfScrap']

            logging.info(f"Flipping {flip} grants {weapon_price - kit_price} half scrap.")
            flips[flip] = weapon_price - kit_price

        logging.info(flips)
        return flips

    def refine_ks_flips(self, flips: dict, quality: str = ""):
        # loop thru all the killstreak flipping values we are given
        # and check each one for a valid kit and weapon listing

        flips = self.sort_flips(flips)

        # if we have a quality append a space to the end for easy concatenation
        if quality != "":

            quality += " "

        for flip in flips:

            logging.info(flip)

            kit_listing = self.sort_listings('sell', f"Non-Craftable {quality}Killstreak {flip} Kit",
                                             banned_attributes=(1004, 1005, 1006, 1007, 1008, 1009))
            print(kit_listing)

            weapon_listing = self.sort_listings('buy', f"{quality}Killstreak {flip}",
                                                banned_attributes=(1004, 1005, 1006, 1007, 1008, 1009))
            print(weapon_listing)

            # if either the kit of weapon listing fail
            if kit_listing is None or weapon_listing is None:

                logging.info(f"Lookup failed on {flip}")
                flips[flip] = None

                continue

            print(f"Flipping {flip} grants {weapon_listing['price'] - kit_listing['price']} scrap")
            flips[flip] = weapon_listing['price'] - kit_listing['price']

        return self.sort_flips(flips)

    @staticmethod
    def sort_flips(flips):
        # sort all

        # remove all the nones so we can sort by profitability
        unpriced_flips = {key: None for key in flips if flips[key] is None}
        for flip in unpriced_flips:
            flips.pop(flip)

        # "sort" the dict in order of profit
        flips = {key: val for key, val in sorted(flips.items(), key=lambda ele: ele[1], reverse=True)}

        # add the un-priced flips to the end of the dictionary
        flips.update(unpriced_flips)

        return flips


if __name__ == '__main__':

    with open("auth.json") as fl:

        auth = json.load(fl)

    grabber = PriceGrabber(token=auth['token'], api_key=auth["api_key"])

    with open("kit_flips.json", "r+", encoding='utf-8') as fl:

        json.dump(grabber.refine_ks_flips(json.load(fl)), fl)  # json.load(fl)

    # Killstreak "Fists" kit "backpack.tf"
