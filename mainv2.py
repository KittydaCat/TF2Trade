import requests
import json
import time


class PriceGrabber:

    def __init__(self, token: str, api_key: str):

        # load the necessary secrets
        self.token = token
        self.api_key = api_key

    def grab_listings(self, item_name: str, retries: int = 3):

        print(item_name)

        # make a request to the backpack.tf API
        page = requests.get("https://backpack.tf/api/classifieds/listings/snapshot",
                            data={'sku': item_name, 'appid': '440', 'token': self.token})

        match page.status_code:

            # if the request is successful
            case 200:

                listings = page.json()['listings']

            case 429:

                print(page)
                print(page.content)
                print(page.reason)
                print(page.text)

                print(f"Too many requests waiting for {int(page.headers['retry-after'])} seconds")

                time.sleep(int(page.headers['retry-after']))
            case _:

                print(f"Listing lookup failed on {item_name} with a code of {page.status_code}")

        if not page.ok:

            if retries > 0:

                listings = self.grab_listings(item_name, retries=retries-1)

            else:

                listings = None

        # print(listings)

        return listings

    def sort_listings(self, intent, item_name, banned_attributes: tuple = ()):

        listings = self.grab_listings(item_name)

        if listings is None:

            return None

        valid_listings = []

        for listing in listings:

            if listing['intent'] == intent:

                # checks if the listing has any banned attributes by comparing each attribute with the banned ones
                if True not in [(attribute['defindex'] in banned_attributes) for attribute in listing['item']['attributes']]:

                    if 'usd' not in listing['currencies']:

                        valid_listings.append(listing)

                    else:

                        print(f"{listing['currencies']}")

        # print(f"Valid listings for {item_name} are {valid_listings}")

        if valid_listings:

            return sorted(valid_listings, reverse=True, key=lambda x: x['price'])[0]

        else:

            print(f"No valid listings for {item_name}")
            return None

    def check_killstreak_flipping(self, quality: str = ""):
        # check all weapons to see if buying and applying a killstreak kit is worth it.

        if not quality == "":
            quality += " "

        # create a list with all the profitability values each with a format of [weapon name, [min profit, max profit]]
        kit_to_weapon_profits = []

        # open the weapon names file and copy it to a list after removing duplicates
        with open("weapon_names.txt", encoding='utf-8') as file:
            weapon_names = file.read().split("\n")

        weapon_names = list(dict.fromkeys([weapon for weapon in weapon_names if weapon != ""]))

        # for each weapon and its kit check the price and compare for both the optimistic and pessimistic values
        for weapon in weapon_names:

            print(weapon)

            kit_listing = self.sort_listings('sell', f"Non-Craftable {quality}Killstreak {weapon} Kit",
                                             banned_attributes=(1004, 1005, 1006, 1007, 1008, 1009))

            weapon_listing = self.sort_listings('buy', f"{quality}Killstreak {weapon}",
                                                banned_attributes=(1004, 1005, 1006, 1007, 1008, 1009))

            if kit_listing is None or weapon_listing is None:
                print(f"Lookup failed on {weapon}")

                continue

            print(weapon_listing)
            print(kit_listing)
            print(f"Flipping {weapon} grants {weapon_listing['price'] - kit_listing['price']} scrap")

            kit_to_weapon_profits.append([weapon, weapon_listing['price'] - kit_listing['price']])

        # sort it by profitability and return it
        kit_to_weapon_profits.sort(reverse=True, key=lambda weapon: weapon[1])

        print(kit_to_weapon_profits)

        return kit_to_weapon_profits


if __name__ == '__main__':
    with open("auth.json") as file:
        auth = json.load(file)

    grabber = PriceGrabber(token=auth['token'], api_key=auth['api_key'])

    print(grabber.check_killstreak_flipping())

    # Killstreak "Fists" kit "backpack.tf"
