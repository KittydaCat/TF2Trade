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

    def get_killstreak_flipping(self, quality: str = ""):
        # check all weapons to see if buying and applying a killstreak kit is worth it.

        # create a list with all the profitability values each with a format of [weapon name, [min profit, max profit]]
        kit_to_weapon_profits = []

        # open the weapon names file and copy it to a list after removing duplicates
        with open("killstreakable_weapons_names.txt", encoding='utf-8') as file:
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

    def grab_listings(self, item_name: str, retries: int = 3, fails: int = 0):

        logging.info(item_name)

        # make a request to the backpack.tf API
        page = requests.get("https://backpack.tf/api/classifieds/listings/snapshot",
                            data={'sku': item_name, 'appid': '440', 'token': self.token})

        match page.status_code:

            # if the request is successful
            case 200:

                response = page.json()

            case 429:

                print(page)
                print(page.content)
                print(page.reason)
                print(page.text)

                print(f"Too many requests waiting for {int(page.headers['retry-after'])} seconds")

                time.sleep(int(page.headers['retry-after']))
            case _:

                print(f"Listing lookup failed on {item_name} with a code of {page.status_code}")
                print(page.reason)

        if not page.ok:

            if retries > 0:

                listings = self.grab_listings(item_name, retries=retries - 1, fails=fails)

            else:

                return None

        # print(listings)

        # if our listings are for the correct weapon
        if response['sku'] != item_name:

            time.sleep(5)

            return self.grab_listings(item_name, fails=fails+1)

        else:

            print(f"Fails until load of {item_name}: {fails}")

            return response['listings']

    def sort_listings(self, intent, item_name, banned_attributes: tuple = ()):

        listings = self.grab_listings(item_name)

        if listings is None:
            return None

        valid_listings = []

        for listing in listings:

            if listing['intent'] == intent:

                # checks if the listing has any banned attributes by comparing each attribute with the banned ones
                if True not in [(int(attribute['defindex']) in banned_attributes) for attribute in
                                listing['item']['attributes']]:

                    if 'usd' not in listing['currencies']:

                        valid_listings.append(listing)

                    else:

                        logging.info(f"{listing['currencies']}")

        # print(f"Valid listings for {item_name} are {valid_listings}")

        if valid_listings:

            if intent == 'sell':

                return sorted(valid_listings, key=lambda x: x['price'])[0]

            if intent == 'buy':

                return sorted(valid_listings, key=lambda x: x['price'])[-1]

        else:

            print(f"No valid listings for {item_name}")
            return None

    def validate_killstreak_flipping(self, profits: list, quality: str = ''):
        # check the listings we have been given and refine them
        # by both returning the corrected list and printing any correct items

        confirmed_profits = []

        if not quality == "":
            quality += " "

        # sort profits by profitability
        profits.sort(reverse=True, key=lambda item: item[1][0])

        # loop thru all given profits
        for profit in profits:

            weapon = profit[0]

            logging.info(weapon)

            kit_listing = self.sort_listings('sell', f"Non-Craftable {quality}Killstreak {weapon} Kit",
                                             banned_attributes=(1004, 1005, 1006, 1007, 1008, 1009))

            print(kit_listing)

            weapon_listing = self.sort_listings('buy', f"{quality}Killstreak {weapon}",
                                                banned_attributes=(1004, 1005, 1006, 1007, 1008, 1009))

            print(weapon_listing)

            if kit_listing is None or weapon_listing is None:
                logging.info(f"Lookup failed on {weapon}")

                continue

            print(f"Flipping {weapon} grants {weapon_listing['price'] - kit_listing['price']} scrap")

            confirmed_profits.append([weapon, weapon_listing['price'] - kit_listing['price']])

        confirmed_profits.sort(reverse=True, key=lambda item: item[1][0])

        print(confirmed_profits)

        return confirmed_profits


if __name__ == '__main__':

    with open("auth.json") as file:

        auth = json.load(file)

    # logging.basicConfig(level=logging.DEBUG)

    grabber = PriceGrabber(token=auth['token'], api_key=auth["api_key"])

    kits = grabber.validate_killstreak_flipping([['Bazaar Bargain', [166, 238]], ['Mantreads', [148, 228]], ['Three-Rune Blade', [122, 204]], ['Tide Turner', [116, 434]], ['Your Eternal Reward', [116, 178]], ['Big Earner', [116, 220]], ['Quick-Fix', [108, 168]], ['Apoco-Fists', [106, 126]], ["L'Etranger", [106, 132]], ['Gunslinger', [82, 344]], ["Beggar's Bazooka", [48, 70]], ['Overdose', [48, 100]], ['Phlogistinator', [34, 348]], ['Bat Outta Hell', [22, 70]], ['Righteous Bison', [20, 114]], ['Maul', [16, 132]], ['Sharpened Volcano Fragment', [16, 100]], ['Vita-Saw', [14, 36]], ['Splendid Screen', [8, 238]], ['Sun-on-a-Stick', [6, 158]], ["Fan O'War", [6, 56]], ['Ubersaw', [6, 24]], ['Diamondback', [4, 28]], ['Wanga Prick', [4, 104]], ['Fortified Compound', [2, 26]], ['Kukri', [2, 38]], ['Unarmed Combat', [-2, 44]], ['Eviction Notice', [-2, 36]], ['Winger', [-4, 114]], ['Eureka Effect', [-4, 54]], ['Market Gardener', [-6, 174]], ["Nessie's Nine Iron", [-6, 38]], ['Scottish Resistance', [-10, 134]], ["Cleaner's Carbine", [-10, 32]], ['Atomizer', [-12, 314]], ['Wrap Assassin', [-12, 60]], ['Killing Gloves of Boxing', [-12, 128]], ['Solemn Vow', [-12, 16]], ['Natascha', [-14, 8]], ['Fists', [-14, 38]], ['Vaccinator', [-14, 40]], ['Cow Mangler 5000', [-16, 10]], ['Liberty Launcher', [-18, 150]], ['Neon Annihilator', [-18, 18]], ['Southern Hospitality', [-18, 4]], ['Freedom Staff', [-18, 92]], ['Axtinguisher', [-20, 20]], ["Scotsman's Skullcutter", [-20, 114]], ['AWPer Hand', [-20, 118]], ['Third Degree', [-22, 58]], ['Wrench', [-22, 94]], ['Sharp Dresser', [-22, 14]], ["Pretty Boy's Pocket Pistol", [-24, 160]], ["Hitman's Heatmaker", [-24, 6]], ['Boston Basher', [-26, 14]], ['Spy-cicle', [-26, 30]], ['Amputator', [-28, 50]], ['Candy Cane', [-30, 22]], ['Shahanshah', [-30, 18]], ['Equalizer', [-32, 26]], ['Rainblower', [-32, 14]], ['Homewrecker', [-32, 18]], ['Back Scatter', [-34, 24]], ['Shotgun', [-34, 378]], ["Crusader's Crossbow", [-34, 110]], ['Frying Pan', [-34, -6]], ['Fire Axe', [-36, 14]], ['Quickiebomb Launcher', [-36, 26]], ['Holiday Punch', [-36, 142]], ['Blutsauger', [-38, 0]], ['Sydney Sleeper', [-38, 8]], ["Tribalman's Shiv", [-38, 14]], ['Shortstop', [-40, 262]], ['Flying Guillotine', [-40, 154]], ['Bat', [-40, 102]], ['Huo-Long Heater', [-40, 136]], ['Jag', [-40, 262]], ['Classic', [-40, 90]], ['Ham Shank', [-40, 28]], ['Backburner', [-44, 0]], ['Lollichop', [-44, 26]], ['Force-A-Nature', [-46, 216]], ['Manmelter', [-46, 56]], ['Persian Persuader', [-46, 26]], ['Short Circuit', [-46, 10]], ['Disciplinary Action', [-48, 122]], ['Eyelander', [-48, 184]], ['Gloves of Running Urgently', [-48, 88]], ['Escape Plan', [-50, 14]], ['Back Scratcher', [-50, 20]], ['Enforcer', [-50, -30]], ['Direct Hit', [-52, -24]], ['Shovel', [-52, 168]], ['Flare Gun', [-52, 32]], ['Bonesaw', [-52, 14]], ['Machina', [-52, 6]], ['Pain Train', [-54, 22]], ["Warrior's Spirit", [-56, 36]], ['Syringe Gun', [-56, 22]], ['Loch-n-Load', [-58, 90]], ['Pistol', [-60, 12]], ['Bottle', [-60, -6]], ['Frontier Justice', [-60, 68]], ["Baby Face's Blaster", [-62, 34]], ['Ullapool Caber', [-64, 50]], ['Holy Mackerel', [-66, 22]], ['Soda Popper', [-68, 210]], ['Scorch Shot', [-68, 34]], ['Postal Pummeler', [-72, 6]], ['Claidheamh Mòr', [-76, 106]], ['SMG', [-76, 10]], ['Half-Zatoichi', [-78, 38]], ['Bushwacka', [-78, 48]], ['Brass Beast', [-80, 16]], ['Ambassador', [-80, 6]], ['Air Strike', [-82, 10]], ['Family Business', [-82, -6]], ['Pomson 6000', [-82, 8]], ['Kritzkrieg', [-82, -16]], ['Reserve Shooter', [-84, 12]], ['Scottish Handshake', [-84, 262]], ['Revolver', [-92, 8]], ['Sandman', [-94, 10]], ['Detonator', [-94, 10]], ['Loose Cannon', [-94, 60]], ['Widowmaker', [-102, -36]], ['Fists of Steel', [-104, -8]], ['Rescue Ranger', [-104, 40]], ['Powerjack', [-108, 8]], ["Chargin' Targe", [-112, 0]], ['Tomislav', [-120, 874]], ['Huntsman', [-122, -6]], ['Minigun', [-128, -74]], ["Conniver's Kunai", [-148, 48]], ['Original', [-160, 304]], ['Stickybomb Launcher', [-178, 86]], ['Sniper Rifle', [-202, -48]], ['Scattergun', [-208, -172]], ['Degreaser', [-212, 62]], ['Medi Gun', [-296, -64]], ['Knife', [-308, -16]], ['Grenade Launcher', [-386, -332]], ['Rocket Launcher', [-390, -132]], ['Flame Thrower', [-404, -400]], ['Black Box', [-406, 38]], ['Conscientious Objector', [-480, 234]]])

    print(kits)

    # Killstreak "Fists" kit "backpack.tf"
