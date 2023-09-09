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

        self.price_auth_token = ""
        self.request_price_auth()

        self.today = date.today()
        self.days_until_old = days_until_old

    def request_price_auth(self):
        # request and save the auth code

        self.price_auth_token = requests.post("https://api2.prices.tf/auth/access").json()["accessToken"]

    def check_price(self, name: str = None, item_sku: str = None, retries: int = 3, rq_update: bool = True):

        price = None

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

            # if our authorization fades
            case 401:

                logging.info("Auth faded")
                self.request_price_auth()

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
                price = self.check_price(name=name, item_sku=item_sku, retries=retries - 1, rq_update=rq_update)

        return price

    def check_killstreak_flipping(self, quality: str = ""):
        # check all weapons to see if buying and applying a killstreak kit is worth it.

        # create a list with all the profitability values each with a format of [weapon name, [min profit, max profit]]
        kit_to_weapon_profits = []
        confirmed_k2w_profits = []

        # open the weapon names file and copy it to a list after removing duplicates
        with open("weapon_names.txt", encoding='utf-8') as file:
            weapon_names = file.read().split("\n")

        weapon_names = list(dict.fromkeys([weapon for weapon in weapon_names if weapon != ""]))

        # for each weapon and its kit check the price and compare for both the optimistic and pessimistic values
        for weapon in weapon_names:

            # load the prices
            weapon_json = self.check_price(name=f"Killstreak {weapon}")
            kit_json = self.check_price(name=f"Non-Craftable {quality} Killstreak {weapon} Kit")

            # if either of the price check fails
            if weapon_json is None or kit_json is None:

                logging.info(f"Price lookup failed on {weapon}")

                continue

            # scrape the values
            weapon_high = weapon_json['sellKeyHalfScrap'] if weapon_json['sellKeys'] else weapon_json['sellHalfScrap']
            weapon_low = weapon_json['buyKeyHalfScrap'] if weapon_json['buyKeys'] else weapon_json['buyHalfScrap']
            kit_high = kit_json['sellKeyHalfScrap'] if kit_json['sellKeys'] else kit_json['sellHalfScrap']
            kit_low = kit_json['buyKeyHalfScrap'] if kit_json['buyKeys'] else kit_json['buyHalfScrap']

            # set the maximum and minimum profits
            kit_to_weapon_profits.append([weapon, [weapon_low - kit_high, weapon_high - kit_low]])

            logging.info(f"{weapon} with between {weapon_low-kit_high} and {weapon_high-kit_low}")

        # sort it by profitability and return it
        kit_to_weapon_profits.sort(reverse=True, key=lambda weapon: weapon[1][0])

        logging.info(kit_to_weapon_profits)

        return kit_to_weapon_profits

    def grab_listings(self, item_name: str = None, item_sku: str = None):

        # if only a Name is provided
        if item_sku is not None:

            # convert it to a sku
            item_name = sku.parser.Sku.sku_to_name(item_sku)

        # make a request to the backpack.tf API
        page = requests.get("https://backpack.tf/api/classifieds/listings/snapshot",
                            data={'sku': item_name, 'appid': '440', 'token': self.token})

        match page.status_code:

            # if the request is successful
            case 200:

                listings = page

            case _:

                logging.info(f"Listing lookup failed on {item_name} with a code of {page.status_code}")

        if not page.ok:

            listings = None

        return listings


if __name__ == '__main__':

    with open("auth.json") as file:

        auth = json.load(file)

    grabber = PriceGrabber(token=auth['token'], api_key=auth["api_key"])
    listings = grabber.grab_listings("Killstreak Fists").json()['listings']

    buy_listings = []

    for listing in listings:

        if listing['intent'] == 'buy':

            buy_listings.append(listing)

    print(buy_listings)

    # Killstreak "Fists" kit "backpack.tf"
