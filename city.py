import wx
import wx.lib.mixins.listctrl as listmix # For ListCtrlAutoWidthMixin
import math
import json
import base64
import random
import datetime
import os
import time as pytime # Avoid conflict with wx.Timer
import traceback # For detailed error logging

# --- Constants and Global Data ---
TEAMS = ['Hoboken Zephyrs', 'Shelbyville Sharks', 'Santa Destroy Warriors', 'New New York Yankees', 'North Shore High Lions']
SPORTS = ['Airball', 'Blernsball', 'Brockian Ultra-Cricket', 'Chess', 'Dungeons & Dungeons', 'Laserball', 'Quidditch']

RESIDENT_MULTIPLIER = 1.05
COMMERCE_MULTIPLIER = 1.1
INDUSTRY_MULTIPLIER = 1.1

SAVE_FILE = "cityclicker_save.json"

# --- Formatting Helpers ---
def format_currency(amount, symbol="¤"):
    """Formats a number as currency, handling large numbers and potential errors."""
    if amount is None: return f"0{symbol}"
    try:
        amount = float(amount)
        # Handle infinite values gracefully
        if math.isinf(amount): return f"∞{symbol}"
        if math.isnan(amount): return f"?{symbol}"

        if amount > 9:
            amount = math.floor(amount)
        else:
            amount = math.floor(amount * 100) / 100

        if amount > 9999999:
            formatted_amount = "{:.2e}".format(amount)
        else:
            # Handle potential floating point inaccuracies for display
            if abs(amount - round(amount)) < 0.001 and amount > 9:
                 formatted_amount = str(int(round(amount)))
            elif abs(amount * 100 - round(amount * 100)) < 0.001 :
                 formatted_amount = "{:.2f}".format(amount)
            else:
                 formatted_amount = str(amount) # Fallback

        return f"{formatted_amount}{symbol}"
    except (ValueError, TypeError):
        return f"?{symbol}" # Indicate error


def format_time_needed(city, cost):
    """Calculates and formats the time needed to afford a cost based on current income."""
    if not city or city.tax is None: return "Calculating..."
    if city.tax <= 0: return "Never (no income)"
    try:
        cost = float(cost)
        currency = float(city.currency)
        tax = float(city.tax)

        # Handle infinite cost
        if math.isinf(cost): return "Never (infinite cost)"

        if cost <= currency: return "Now"
        if tax == 0: return "Never (no income)" # Should be caught by city.tax <= 0, but safety first

        # Prevent overflow if cost is huge and tax is tiny
        try:
            time_seconds = math.ceil((cost - currency) / tax)
        except OverflowError:
            return "A very long time"

        time_seconds = max(0, time_seconds) # Ensure non-negative

        if time_seconds == 1: return f"{time_seconds} second"
        if time_seconds < 60: return f"{time_seconds} seconds"
        if time_seconds < 3600: return f"{time_seconds // 60}m {time_seconds % 60}s"

        # Handle very large times more gracefully
        days = time_seconds // 86400
        remaining_seconds = time_seconds % 86400
        hours = remaining_seconds // 3600
        minutes = (remaining_seconds % 3600) // 60
        if days > 365 * 10: return f"{days // 365} decades" # Approximate
        if days > 365: return f"{days // 365} years {days % 365} days"
        if days > 0: return f"{days}d {hours}h {minutes}m"

        return f"{hours}h {minutes}m"

    except (ValueError, TypeError, ZeroDivisionError):
        return "Calculating..." # Catch-all for other errors

def format_generic(amount, symbol=""):
    """Formats a generic number, handling large numbers and potential errors."""
    if amount is None: return f"0{symbol}"
    try:
        amount = float(amount)
        if math.isinf(amount): return f"∞{symbol}"
        if math.isnan(amount): return f"?{symbol}"

        if amount > 9:
            amount = math.floor(amount)
        else:
            amount = math.floor(amount * 100) / 100

        if amount > 9999999:
             formatted_amount = "{:.2e}".format(amount)
        else:
             if abs(amount - round(amount)) < 0.001 and amount > 9:
                 formatted_amount = str(int(round(amount)))
             elif abs(amount * 100 - round(amount * 100)) < 0.001 :
                 formatted_amount = "{:.2f}".format(amount)
             else:
                 formatted_amount = str(amount) # Fallback
        return f"{formatted_amount}{symbol}"
    except (ValueError, TypeError):
         return f"?{symbol}" # Indicate error

# --- Custom ListCtrl Base Class ---
class AccessibleListCtrl(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    """ Base ListCtrl with auto-width and item data handling. """
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition, size=wx.DefaultSize, style=0):
        wx.ListCtrl.__init__(self, parent, id, pos, size, style)
        listmix.ListCtrlAutoWidthMixin.__init__(self)
        # Store mapping from list index to data key (e.g., zone size index or update id_name)
        self._item_data_map = {}
        self._data_item_map = {}

    def SetItemData(self, index, data):
        """ Associates data with a list item index. """
        # Use list index as internal item data for wx compatibility if needed
        # super().SetItemData(index, index)
        self._item_data_map[index] = data
        self._data_item_map[data] = index

    def GetItemData(self, index):
        """ Retrieves the data associated with a list item index. """
        return self._item_data_map.get(index, None)

    def FindItemData(self, data):
        """ Finds the list index associated with the given data. Returns -1 if not found. """
        return self._data_item_map.get(data, -1)

    def ClearAllData(self):
        """ Clears the internal data maps and the list items. """
        self._item_data_map.clear()
        self._data_item_map.clear()
        self.DeleteAllItems() # Also clear the list itself

    def SetItemTextColour(self, index, colour):
        """ Safely sets the text color for an item. """
        if index < 0 or index >= self.GetItemCount(): return # Index out of bounds
        try:
            item = self.GetItem(index)
            item.SetTextColour(colour)
            self.SetItem(item)
        except Exception as e:
            # This can sometimes fail if the list is being updated rapidly or item doesn't exist
            # print(f"Warning: Could not set text colour for item {index}: {e}")
            pass

    def GetItemCount(self):
        """ Override to ensure consistency, though base method should work. """
        return super().GetItemCount()


# --- Model Classes ---

class ZoneSize:
    """Represents a specific size level within a Zone."""
    def __init__(self, index, symbol, density, load_data=None):
        self.index = index # Keep index for reference
        self.symbol = symbol
        self.density = max(0, density) # Ensure density is non-negative
        self.label = self._create_label(index + 1, symbol)
        self.amount = 0  # Zoned
        self.built = 0   # Actually constructed based on demand

        if load_data:
            self.amount = load_data.get('amount', 0)
            self.built = load_data.get('built', 0)

        self.tooltip_provider = None # Function to generate tooltip string

    def _create_label(self, i, symbol):
        if i <= 3: return symbol * i
        return f"{symbol}x{i}"

    def price(self):
        safe_amount = max(0, self.amount)
        # Add safety for large exponents
        try:
            # Prevent extremely large numbers early
            if safe_amount > 500: # Arbitrary limit to prevent huge calculation time/overflow
                return float('inf')
            pow_val = math.pow(1.1, safe_amount)
        except OverflowError:
            return float('inf')

        # Prevent overflow from density * pow_val
        if self.density == float('inf') or pow_val == float('inf'):
            return float('inf')
        try:
             # Check for potential overflow before multiplication
             max_safe_density = float('inf') if pow_val == 0 else (float('inf') / pow_val)
             if self.density > max_safe_density:
                 return float('inf')
             result = self.density * pow_val
             # Final check if result somehow became inf
             if math.isinf(result): return float('inf')
             return math.floor(result)
        except OverflowError:
            return float('inf')


    def capacity(self): return self.built * self.density
    def zoned_capacity(self): return self.amount * self.density
    def data(self): return {'amount': self.amount, 'built': self.built}

class Zone:
    """Represents a type of zone (Residential, Commercial, Industrial)."""
    def __init__(self, city, type_name, symbol, load_data=None):
        self.city = city
        self.type_name = type_name
        self.symbol = symbol
        self.tax = 10 # Default tax rate %
        self.demand = 0.0 # Use float

        if load_data:
            self.tax = load_data.get('tax', 10)

        self.sizes = []
        for i in range(10):
            try:
                exp_term = 0.5 * (i + 1) * (i + 1) + 0.5 * (i + 1)
                # Limit exponent to prevent immediate overflow
                density = math.pow(10, min(exp_term, 300)) # Limit exponent size
            except OverflowError:
                density = float('inf')
            size_load_data = load_data.get(str(i)) if load_data else None
            self.sizes.append(ZoneSize(i, symbol, density, size_load_data))

        self.panel = None # The wx.Panel containing the list control

    def buy(self, size_index):
        if 0 <= size_index < len(self.sizes):
            size = self.sizes[size_index]
            cost = size.price()
            if self.city.spend(cost):
                size.amount += 1
                return True
        return False

    def total_capacity(self): return sum(s.capacity() for s in self.sizes)
    def total_zoned_capacity(self): return sum(s.zoned_capacity() for s in self.sizes)
    def data(self):
        serial = {'tax': self.tax}
        for i, size in enumerate(self.sizes):
            serial[str(i)] = size.data()
        return serial
    def income(self, tax_rate=None):
        rate = tax_rate if tax_rate is not None else self.tax
        if rate is None: rate = 0
        # Ensure total_capacity doesn't overflow
        cap = self.total_capacity()
        if math.isinf(cap): return float('inf') # Income is infinite if capacity is
        return (rate / 100.0) * cap / 10.0

    def update_construction(self):
        current_demand = self.demand
        built_cap = self.total_capacity()
        if math.isinf(built_cap): return # Already infinite capacity

        remaining_demand = current_demand - built_cap
        if remaining_demand <= 0: return

        for size in reversed(self.sizes):
            if remaining_demand <= 0: break
            buildable_count = size.amount - size.built
            if buildable_count > 0:
                if size.density <= 0: continue
                try:
                    # Avoid division by zero or with infinity
                    if math.isinf(remaining_demand) and not math.isinf(size.density):
                         needed_slots = float('inf')
                    elif math.isinf(size.density):
                         needed_slots = 1 # Need at least 1 slot for infinite density
                    else:
                         needed_slots = math.ceil(remaining_demand / size.density)

                except (OverflowError, ValueError):
                    needed_slots = float('inf')

                build_count = min(buildable_count, needed_slots)
                if math.isinf(build_count) or math.isnan(build_count):
                    build_count = buildable_count # Build as many as possible if calculation fails
                build_count = int(min(build_count, 1000000)) # Limit build count per tick

                if build_count > 0:
                    size.built += build_count
                    # Avoid subtracting infinity from infinity
                    if not math.isinf(build_count * size.density):
                         remaining_demand -= build_count * size.density
                    else: # If we built infinite capacity, demand is met
                         remaining_demand = 0


class Update:
    """Represents an upgrade purchase."""
    def __init__(self, city, id_name, base_cost, scale, message_source, levels=None, stats_provider=None, load_level=0):
        self.city = city
        self.id_name = id_name # For saving/loading
        self.level = load_level
        self.base_cost = base_cost
        self.scale = scale or 2.0 # Default scale
        self.message_source = message_source # String, list, or function(self)
        self.levels = levels or [] # Specific level messages override message_source
        self.stats_provider = stats_provider # Optional function(self) to generate tooltip stats
        self.tooltip_provider = None # Function to generate tooltip string

    def price(self):
        safe_level = max(0, self.level)
        try:
            # Limit level to prevent huge calculation time/overflow
            if safe_level > 1000: return float('inf')
            return self.base_cost * math.pow(self.scale, safe_level)
        except OverflowError:
            return float('inf')

    def get_current_message(self):
        msg = None
        # Check level before accessing lists/functions
        safe_level = int(max(0, self.level))

        if self.levels and safe_level < len(self.levels):
            msg = self.levels[safe_level]
        elif callable(self.message_source):
             try: msg = self.message_source(self)
             except Exception as e: msg = f"Error: {e}"
        elif isinstance(self.message_source, str): msg = self.message_source
        else: msg = f"Invalid source"

        if not msg: return None # Upgrade maxed out or error

        city_name = self.city.name if self.city and self.city.name else "CITY"
        return msg.replace('CITY', f'{city_name}')

    def buy(self):
        cost = self.price()
        if math.isinf(cost): return False # Cannot afford infinite cost
        if not self.get_current_message(): return False # Maxed out

        if self.city.spend(cost):
            self.level += 1
            try:
                # Update tax rates safely
                if self.id_name == 'resident_tax' and self.city.resident: self.city.resident.tax += 1
                elif self.id_name == 'commerce_tax' and self.city.commerce: self.city.commerce.tax += 1
                elif self.id_name == 'industry_tax' and self.city.industry: self.city.industry.tax += 1
            except AttributeError as e: print(f"Warning: Could not update tax for {self.id_name}. Error: {e}")
            return True
        return False

    def data(self): return self.level

    def get_tooltip_text(self):
        cost = self.price()
        title = "Upgrade Details"
        attributes = {}
        current_message = self.get_current_message()
        if current_message and "." in current_message: title = current_message.split('.')[0]
        elif current_message: title = current_message
        else: title = f"Upgrade {self.id_name}"

        if self.stats_provider:
            try: attributes = self.stats_provider(self)
            except Exception as e: attributes = {'Error': f'Could not load stats: {e}'}
        else: attributes = {}

        attributes['Time to purchase'] = format_time_needed(self.city, cost)
        lines = [f"--- {title} ---"]
        for k, v in attributes.items(): lines.append(f"{k}: {str(v)}")
        return "\n".join(lines)

class City:
    """The main game state container."""
    def __init__(self, load_data=None):
        data = load_data or {}
        self.currency = data.get('currency', 100.0)
        self.day = data.get('day', 0)
        self.name = data.get('name', 'The City')
        self.population = data.get('population', 0.0)
        self.tax = 0.0 # Total tax income per second, calculated in update

        self.items = [] # All zones and updates for easier iteration

        # Zones - Initialize first
        self.resident = Zone(self, 'Residential', '♥', data.get('resident'))
        self.commerce = Zone(self, 'Commercial', '♦', data.get('commerce'))
        self.industry = Zone(self, 'Industrial', '♣', data.get('industry'))
        self.items.extend([self.resident, self.commerce, self.industry])

        # Updates - Load level from data if present
        self.transport = Update(self, 'transport', 1000, 2.1,
            'Increase advertising budget.', [
                'Add a road to CITY.', 'Connect a highway to CITY.', 'Connect the railway to CITY.',
                'Build a seaport in CITY.', 'Build an airport in CITY.', 'Advertise CITY in other cities.',
                'Absorb neighboring city into CITY.', 'Advertise CITY in other countries.', 'Build a spaceport in CITY.',
                'Build cloning vats in CITY.', 'Build a space elevator in CITY.', 'Attach CITY to teleporter network.',
                'Advertise CITY on other planets.', 'Advertise CITY in other solar systems.', 'Advertise CITY to other galaxies.',
                'Achieve CITY consciousness.', 'Expand CITY across the void.',
            ],
            stats_provider=self._transport_stats,
            load_level=data.get('transport', 0)
        )
        self.residentDemand = Update(self, 'resident_demand', 5000, 1.9,
            'Pay people for moving to CITY.', [
                'Build a school in CITY.', 'Build a hospital in CITY.', 'Increase CITY education budget.',
                'Build a college in CITY.', 'Increase CITY healthcare budget.', 'Add parks to CITY.',
                'Build a marina in CITY.', 'Build a zoo in CITY.', 'Add wildlife to CITY parks.',
                'Build a sports stadium in CITY.', 'Build a pleasure dome in CITY.', 'Build a world wonder in CITY.',
                'Embue CITY park wildlife with magic.', 'Provide free healthcare in CITY.', 'Move other world wonders to CITY.',
                'Build Fountain of Youth in CITY.', 'Mandate universal basic happiness.',
             ],
            stats_provider=self._resident_demand_stats,
            load_level=data.get('residentDemand', 0)
        )
        self.commerceDemand = Update(self, 'commerce_demand', 5000, 1.8,
            'Give corporations extra votes.', [
                'Put up billboards in CITY.', 'Build a mall in CITY.', 'Build direct CITY monorail to mall.',
                'Legalize gambling in CITY.', 'Upgrade CITY Mall to CITY Megamall.', 'Add giant TVs to all CITY intersections.',
                'Remove liquor restrictions.', 'Allow anonymously held corporations.', 'Legalize prostitution in CITY.',
                'Turn CITY into mall.', 'Declare corporations people.', 'Declare corporations better people.',
                'Legalize all narcotics.', 'Give corporations CITY keys.', 'Mandatory corporate branding on newborns.',
            ],
            stats_provider=self._commerce_demand_stats,
            load_level=data.get('commerceDemand', 0)
        )
        self.industryDemand = Update(self, 'industry_demand', 10000, 1.7,
            'Increase robot workforce.', [
                'Build a power plant in CITY.', 'Build a factory in CITY.', 'Build an army base in CITY.',
                'Repeal environmental protections.', 'Build a mine in CITY.', 'Automate CITY construction.',
                'Upgrade CITY Power Plant to fission.', 'Build worker housing near CITY.', 'Upgrade CITY mine to strip mine.',
                'Build toxic waste dump in CITY.', 'Upgrade CITY Power Plant to fusion.', 'Remove minimum wage in CITY.',
                'Build CITY robot factories.', 'Upgrade workers to cyborgs.', 'Repeal human rights protections.',
                'Nerve staple cyborg workers.', 'Replace atmosphere with nutrient paste.',
            ],
            stats_provider=self._industry_demand_stats,
            load_level=data.get('industryDemand', 0)
        )

        # Tax Updates - Use functions for messages
        self.residentTax = Update(self, 'resident_tax', 1000, 2.6,
            lambda u: f'Raise Residential tax ({self.resident.tax if self.resident else "N/A"}%).',
            stats_provider=self._resident_tax_stats,
            load_level=data.get('residentTax', 0)
        )
        if self.resident: self.resident.tax = 10 + self.residentTax.level

        self.commerceTax = Update(self, 'commerce_tax', 1000, 2.4,
            lambda u: f'Raise Commercial tax ({self.commerce.tax if self.commerce else "N/A"}%).',
            stats_provider=self._commerce_tax_stats,
            load_level=data.get('commerceTax', 0)
        )
        if self.commerce: self.commerce.tax = 15 + self.commerceTax.level

        self.industryTax = Update(self, 'industry_tax', 1000, 2.2,
            lambda u: f'Raise Industrial tax ({self.industry.tax if self.industry else "N/A"}%).',
            stats_provider=self._industry_tax_stats,
            load_level=data.get('industryTax', 0)
        )
        if self.industry: self.industry.tax = 12 + self.industryTax.level

        # Special Updates
        self.rename = Update(self, 'rename', 1000, 1.2, 'Rename CITY.', load_level=data.get('rename', 0))
        self.reset = Update(self, 'reset', 0, 1, 'Reset game.', load_level=0)
        self.news = Update(self, 'news', 1, 1.07, self._get_news_message, load_level=data.get('news', 0))

        self.items.extend([
            self.transport, self.residentDemand, self.commerceDemand, self.industryDemand,
            self.residentTax, self.commerceTax, self.industryTax,
            self.rename, self.reset, self.news
        ])

        self.news_log = data.get('news_log', []) if data else []


    # --- Stat Provider Methods for Updates ---
    def _transport_stats(self, update):
        res_tax = self.resident.tax if self.resident else 10
        multiplier = max(1.01, 2.0 - res_tax / 100.0)
        current_rate = math.pow(multiplier, max(0, update.level))
        next_rate = math.pow(multiplier, max(0, update.level + 1))
        return {
            'Multiplier': format_generic(multiplier, '×'),
            'Current growth': format_generic(current_rate, '♥/sec'),
            'Upgrade growth': format_generic(next_rate, '♥/sec'),
        }

    def _resident_demand_stats(self, update):
         base_demand = self._calculate_base_resident_demand()
         current_total_demand = base_demand * math.pow(RESIDENT_MULTIPLIER, max(0, update.level))
         next_total_demand = base_demand * math.pow(RESIDENT_MULTIPLIER, max(0, update.level + 1))
         return {
             'Multiplier': format_generic(RESIDENT_MULTIPLIER, '×'),
             'Current demand': format_generic(current_total_demand, '♥'),
             'Upgrade demand': format_generic(next_total_demand, '♥'),
         }

    def _commerce_demand_stats(self, update):
        base_demand = self._calculate_base_commerce_demand()
        current_total_demand = base_demand * math.pow(COMMERCE_MULTIPLIER, max(0, update.level))
        next_total_demand = base_demand * math.pow(COMMERCE_MULTIPLIER, max(0, update.level + 1))
        return {
            'Multiplier': format_generic(COMMERCE_MULTIPLIER, '×'),
            'Current demand': format_generic(current_total_demand, '♦'),
            'Upgrade demand': format_generic(next_total_demand, '♦'),
         }

    def _industry_demand_stats(self, update):
        base_demand = self._calculate_base_industry_demand()
        current_total_demand = base_demand * math.pow(INDUSTRY_MULTIPLIER, max(0, update.level))
        next_total_demand = base_demand * math.pow(INDUSTRY_MULTIPLIER, max(0, update.level + 1))
        return {
            'Multiplier': format_generic(INDUSTRY_MULTIPLIER, '×'),
            'Current demand': format_generic(current_total_demand, '♣'),
            'Upgrade demand': format_generic(next_total_demand, '♣'),
         }

    def _resident_tax_stats(self, update):
        if not self.resident: return {'Error': 'Residential zone N/A'}
        current_income = self.resident.income()
        next_income = self.resident.income(self.resident.tax + 1)
        return {
            'New Rate': f"{self.resident.tax + 1}%",
            'Current income': format_currency(current_income),
            'Upgrade income': format_currency(next_income),
        }

    def _commerce_tax_stats(self, update):
        if not self.commerce: return {'Error': 'Commercial zone N/A'}
        current_income = self.commerce.income()
        next_income = self.commerce.income(self.commerce.tax + 1)
        return {
            'New Rate': f"{self.commerce.tax + 1}%",
            'Current income': format_currency(current_income),
            'Upgrade income': format_currency(next_income),
        }

    def _industry_tax_stats(self, update):
        if not self.industry: return {'Error': 'Industrial zone N/A'}
        current_income = self.industry.income()
        next_income = self.industry.income(self.industry.tax + 1)
        return {
            'New Rate': f"{self.industry.tax + 1}%",
            'Current income': format_currency(current_income),
            'Upgrade income': format_currency(next_income),
        }

    def _get_news_message(self, update):
        pop = self.population
        if pop > 1e16: return 'Receive CITY thought broadcast.'
        if pop > 1e12: return 'Check CITY app.'
        if pop > 1e8: return 'Watch CITY news.'
        if pop > 1e4: return 'Check CITY website.'
        return 'Read CITY Times.'


    # --- Core City Logic ---
    def spend(self, cost):
        try:
            cost_float = float(cost)
            if math.isinf(cost_float) or math.isnan(cost_float): return False # Cannot spend infinity/NaN
            if cost_float <= self.currency:
                self.currency -= cost_float
                return True
            return False
        except (ValueError, TypeError): return False


    def get_date_string(self):
        try:
            start_date = datetime.date(2024, 1, 1)
            # Handle large day numbers potentially causing OverflowError
            day_int = int(self.day)
            if abs(day_int) > 365 * 10000: # Limit to 10k years
                return "Distant Future" if day_int > 0 else "Distant Past"
            current_date = start_date + datetime.timedelta(days=day_int)
            return current_date.strftime("%a, %b %d, %Y")
        except (ValueError, TypeError, OverflowError): return "Invalid Date"


    def _calculate_base_commerce_demand(self):
        pop = max(0, self.population or 0)
        tax = self.commerce.tax if self.commerce and self.commerce.tax is not None else 15
        try:
            pop_log = math.log(pop) if pop > 0 else 0
        except ValueError: pop_log = 0 # Handle potential domain error
        ratio_percent = max(20.0, min(80.0, 10.0 + pop_log * 4.0))
        ratio = ratio_percent / 100.0
        demand = 1.1 * max(1.0, pop * max(0.1, ratio - tax / 100.0))
        return demand

    def _calculate_base_industry_demand(self):
        pop = max(0, self.population or 0)
        tax = self.industry.tax if self.industry and self.industry.tax is not None else 12
        try:
            pop_log = math.log(pop) if pop > 0 else 0
        except ValueError: pop_log = 0
        ratio_percent = max(20.0, min(80.0, 10.0 + pop_log * 4.0))
        ratio = ratio_percent / 100.0
        demand = 1.1 * max(1.0, pop * max(0.1, (1.0 - ratio) - tax / 100.0))
        return demand

    def _calculate_base_resident_demand(self):
         res_tax = self.resident.tax if self.resident and self.resident.tax is not None else 10
         com_demand = self.commerce.demand if self.commerce and self.commerce.demand is not None else 0
         com_cap = self.commerce.total_capacity() if self.commerce else 0
         ind_demand = self.industry.demand if self.industry and self.industry.demand is not None else 0
         ind_cap = self.industry.total_capacity() if self.industry else 0

         # Prevent calculations with infinity
         if any(math.isinf(x) for x in [com_demand, com_cap, ind_demand, ind_cap]):
              return float('inf') # If any driver is infinite, demand is infinite

         factor = max(0.1, 1.0 - res_tax / 100.0)
         driver = (com_demand + com_cap + ind_demand + ind_cap / 4.0)
         demand = max(1.0, factor * driver)
         return demand

    def update(self, tick=False):
        """Calculates demand, income, and optionally progresses time."""
        try:
            # 1. Calculate Demand
            if self.commerce and self.commerceDemand:
                self.commerce.demand = self._calculate_base_commerce_demand() * \
                                    math.pow(COMMERCE_MULTIPLIER, max(0, self.commerceDemand.level))
            if self.industry and self.industryDemand:
                self.industry.demand = self._calculate_base_industry_demand() * \
                                    math.pow(INDUSTRY_MULTIPLIER, max(0, self.industryDemand.level))
            if self.resident and self.residentDemand:
                self.resident.demand = self._calculate_base_resident_demand() * \
                                    math.pow(RESIDENT_MULTIPLIER, max(0, self.residentDemand.level))

            # Clamp demand to prevent extreme values if necessary
            # max_demand = 1e18 # Example limit
            # if self.resident: self.resident.demand = min(self.resident.demand, max_demand)
            # if self.commerce: self.commerce.demand = min(self.commerce.demand, max_demand)
            # if self.industry: self.industry.demand = min(self.industry.demand, max_demand)


            # 2. Update Zone Construction
            if tick:
                if self.resident: self.resident.update_construction()
                if self.commerce: self.commerce.update_construction()
                if self.industry: self.industry.update_construction()

            # 3. Calculate Income
            res_income = self.resident.income() if self.resident else 0
            com_income = self.commerce.income() if self.commerce else 0
            ind_income = self.industry.income() if self.industry else 0
            self.tax = res_income + com_income + ind_income
            if math.isinf(self.tax): self.tax = 1e18 # Cap income if it becomes infinite

            # 4. Apply Tick Effects
            if tick:
                # Prevent currency overflow
                if not math.isinf(self.tax):
                    self.currency += self.tax
                    self.currency = min(self.currency, float('inf')) # Should already be float, but ensure finite if possible

                # Population Growth
                if self.resident and self.transport and self.population is not None:
                    res_cap = self.resident.total_capacity()
                    if self.population < res_cap:
                        res_tax = self.resident.tax if self.resident.tax is not None else 10
                        growth_multiplier = max(1.01, 2.0 - res_tax / 100.0)
                        growth_rate = math.pow(growth_multiplier, max(0, self.transport.level))
                        # Prevent huge growth rates
                        growth_rate = min(growth_rate, 1e9) # Limit growth per tick

                        potential_growth = min(growth_rate, res_cap - self.population)
                        # Ensure potential_growth is not negative or NaN
                        potential_growth = max(0, potential_growth) if not math.isnan(potential_growth) else 0

                        self.population += potential_growth
                        self.population = max(0, self.population) # Ensure non-negative
                        # Cap population if it grows excessively
                        # self.population = min(self.population, 1e20) # Example cap

                self.day += 1
        except Exception as e:
            print(f"Error during City.update: {e}\n{traceback.format_exc()}")


    def generate_news_report(self):
        """Generates a news report string. Returns None if unable."""
        if not self.news or not self.news.buy(): return None

        date_str = self.get_date_string()
        report = [f"*** {self.name} News - {date_str} ***\n", "--- Opinion ---"]

        # --- Residential ---
        if self.resident:
            res_capacity = self.resident.total_capacity()
            res_zoned_cap = self.resident.total_zoned_capacity()
            res_demand = self.resident.demand
            res_tax_rate = self.resident.tax
            res_demand_ratio = res_demand / res_capacity if res_capacity > 0 else (1.0 if res_demand > 0 else 0.0)

            first_unbuilt_res_size = -1
            for i, size in enumerate(self.resident.sizes):
                if size.amount > 0 and size.built < size.amount: first_unbuilt_res_size = i; break
                if size.amount == 0 and first_unbuilt_res_size == -1: first_unbuilt_res_size = i if i == 0 else i -1

            if res_demand_ratio >= 1.0 and res_capacity < res_zoned_cap :
                report.append("Housing is currently in high demand! Residents clamor for more homes.")
                if self.residentTax and self.residentTax.price() < self.currency: report.append(f"Perhaps the Mayor should consider raising the {res_tax_rate}% tax?")
                if first_unbuilt_res_size != -1:
                    size = self.resident.sizes[first_unbuilt_res_size]; price = size.price(); label = size.label
                    if price < self.currency: report.append(f"Zoning more {label} residential seems overdue.")
                    else: report.append(f"Expanding {label} residential zones would help meet this need.")
                if self.transport:
                    trans_msg = self.transport.get_current_message()
                    if trans_msg:
                        try: trans_msg_verb = trans_msg.split(' ')[0].lower() + trans_msg.split(' ',1)[1][:-1]; report.append(f"Furthermore, pursuing the plan to {trans_msg_verb} could attract even more citizens.")
                        except IndexError: pass

            elif res_demand_ratio >= 1.0 and res_capacity >= res_zoned_cap:
                report.append("Housing demand is sky-high, but all zoned areas are built!")
                if self.residentTax and self.residentTax.price() < self.currency: report.append(f"Is now the time to increase the {res_tax_rate}% residential tax?")
                else: report.append(f"With demand so high, maybe increasing the {res_tax_rate}% residential tax isn't a bad idea.")
                if first_unbuilt_res_size != -1:
                    size = self.resident.sizes[first_unbuilt_res_size]; price = size.price(); label = size.label
                    if price < self.currency: report.append(f"The Mayor should zone more {label} residential immediately!")
                    else: report.append(f"Citizens desperately need more {label} residential zones.")

            else: # Demand < Capacity
                report.append("Zoned residential areas sit partially empty.")
                if self.residentDemand:
                    res_demand_msg = self.residentDemand.get_current_message()
                    if res_demand_msg:
                        try: res_demand_verb = res_demand_msg.split(' ')[0].lower() + res_demand_msg.split(' ',1)[1][:-1]; report.append(f"Has the Mayor considered the proposal to {res_demand_verb} to encourage move-ins?")
                        except IndexError: pass
                    else: report.append("Perhaps residential demand initiatives have been exhausted?")
        else: report.append("Residential sector status unknown.")

        report.append("") # Spacer

        # --- Commercial ---
        if self.commerce:
            com_capacity = self.commerce.total_capacity(); com_zoned_cap = self.commerce.total_zoned_capacity()
            com_demand = self.commerce.demand; com_tax_rate = self.commerce.tax
            com_demand_ratio = com_demand / com_capacity if com_capacity > 0 else (1.0 if com_demand > 0 else 0.0)
            first_unbuilt_com_size = -1
            for i, size in enumerate(self.commerce.sizes):
                if size.amount > 0 and size.built < size.amount: first_unbuilt_com_size = i; break
                if size.amount == 0 and first_unbuilt_com_size == -1: first_unbuilt_com_size = i if i == 0 else i -1
            res_high_demand = self.resident and (self.resident.demand / self.resident.total_capacity() >= 1.0 if self.resident.total_capacity() > 0 else False)

            if com_demand_ratio >= 1.0 and com_capacity < com_zoned_cap:
                report.append(f"{'Like' if res_high_demand else 'Unlike'} residential, businesses are eager to set up shop!")
                if self.commerceTax and self.commerceTax.price() < self.currency: report.append(f"Time to bump the commercial tax from {com_tax_rate}% perhaps?")
                if first_unbuilt_com_size != -1:
                    size = self.commerce.sizes[first_unbuilt_com_size]; price = size.price(); label = size.label
                    if price < self.currency: report.append(f"Adding more {label} commercial zones seems like a good move.")
                    else: report.append(f"More {label} commercial zones are needed to satisfy businesses.")
            elif com_demand_ratio >= 1.0 and com_capacity >= com_zoned_cap:
                report.append("Commercial demand is booming, but all zoned areas are full!")
                if self.commerceTax and self.commerceTax.price() < self.currency: report.append(f"Increasing the {com_tax_rate}% commercial tax could capitalize on this.")
                else: report.append(f"With such high demand, raising the {com_tax_rate}% commercial tax might be wise.")
                if first_unbuilt_com_size != -1:
                    size = self.commerce.sizes[first_unbuilt_com_size]; price = size.price(); label = size.label
                    if price < self.currency: report.append(f"The city needs more {label} commercial zones, pronto!")
                    else: report.append(f"Businesses are crying out for more {label} commercial zones.")
            else: # Demand < Capacity
                report.append(f"{'Unlike' if res_high_demand else 'Like'} residential, zoned commercial space remains vacant.")
                if self.commerceDemand:
                    com_demand_msg = self.commerceDemand.get_current_message()
                    if com_demand_msg:
                        try: com_demand_verb = com_demand_msg.split(' ')[0].lower() + com_demand_msg.split(' ',1)[1][:-1]; report.append(f"When will the Mayor {com_demand_verb} so businesses can thrive here?")
                        except IndexError: pass
                    else: report.append("It seems efforts to boost commercial demand have reached their peak.")
        else: report.append("Commercial sector status unknown.")

        report.append("") # Spacer

        # --- Industrial ---
        if self.industry:
            ind_capacity = self.industry.total_capacity(); ind_zoned_cap = self.industry.total_zoned_capacity()
            ind_demand = self.industry.demand; ind_tax_rate = self.industry.tax
            ind_demand_ratio = ind_demand / ind_capacity if ind_capacity > 0 else (1.0 if ind_demand > 0 else 0.0)
            first_unbuilt_ind_size = -1
            for i, size in enumerate(self.industry.sizes):
                if size.amount > 0 and size.built < size.amount: first_unbuilt_ind_size = i; break
                if size.amount == 0 and first_unbuilt_ind_size == -1: first_unbuilt_ind_size = i if i == 0 else i -1

            if ind_demand_ratio >= 1.0 and ind_capacity < ind_zoned_cap:
                report.append("Industry is booming and requires expansion!")
                if self.industryTax and self.industryTax.price() < self.currency: report.append(f"Is the Mayor just going to raise the {ind_tax_rate}% industrial tax instead of zoning more?")
                if first_unbuilt_ind_size != -1:
                    size = self.industry.sizes[first_unbuilt_ind_size]; price = size.price(); label = size.label
                    if price < self.currency: report.append(f"Expanding {label} industrial zones seems necessary.")
                    else: report.append(f"The city needs more {label} industrial zones for these factories.")
            elif ind_demand_ratio >= 1.0 and ind_capacity >= ind_zoned_cap:
                report.append("Industrial demand outstrips zoned capacity entirely!")
                if self.industryTax and self.industryTax.price() < self.currency: report.append(f"Raising the {ind_tax_rate}% industrial tax seems unavoidable given the demand.")
                else: report.append(f"Perhaps raising the {ind_tax_rate}% industrial tax is the only option?")
                if first_unbuilt_ind_size != -1:
                    size = self.industry.sizes[first_unbuilt_ind_size]; price = size.price(); label = size.label
                    if price < self.currency: report.append(f"Quickly, zone more {label} industrial areas!")
                    else: report.append(f"More {label} industrial zones are desperately needed!")
            else: # Demand < Capacity
                report.append("For reasons unclear, the Mayor seems focused on industrial incentives.")
                if self.industryDemand:
                    ind_demand_msg = self.industryDemand.get_current_message()
                    if ind_demand_msg:
                        try: ind_demand_verb = ind_demand_msg.split(' ')[0].lower() + ind_demand_msg.split(' ',1)[1][:-1]; report.append(f"The plan to {ind_demand_verb} aims to entice industry."); report.append("While industry drives residential demand, one wonders if this is the best path.")
                        except IndexError: pass
                    else: report.append("Perhaps further industrial incentives are no longer possible.")
        else: report.append("Industrial sector status unknown.")

        report.append("\n--- Sports ---")
        if self.population <= 0:
            report.append(f"{self.name} doesn't yet have a sports team, as no one lives here yet.")
        else:
            try:
                us_score = random.randint(0, 19); them_score = random.randint(0, 19)
                opponent_team = random.choice(TEAMS) if TEAMS else "The Opponents"
                sport_played = random.choice(SPORTS) if SPORTS else "Generic Sport"
                home_team = f"{self.name} Llamas"
                if us_score > them_score: report.append(f"Local heroes, the {home_team}, defeated the {opponent_team} {us_score}-{them_score} in a thrilling {sport_played} match! Go Llamas!")
                elif them_score > us_score:
                    diff = them_score - us_score; report.append(f"A tough loss for the {home_team} against the {opponent_team}. The {sport_played} game ended {us_score}-{them_score}, a {diff}-point defeat.")
                    if diff > 10: report.append(f"A truly dark day for {self.name} sports fans.")
                else: report.append(f"An incredible {sport_played} match ends in a tie! {home_team} {us_score}, {opponent_team} {them_score}. A historic game!")
            except Exception as e: report.append(f"Sports news unavailable: {e}")

        final_report_str = "\n".join(report)
        self.news_log.insert(0, final_report_str)
        if len(self.news_log) > 10: self.news_log.pop()
        return final_report_str


    # --- Save/Load ---
    def data(self):
        """Serializes the city state into a dictionary."""
        save_data = {
            'currency': self.currency, 'day': self.day, 'name': self.name,
            'population': self.population, 'news_log': self.news_log[:10]
        }
        if self.resident: save_data['resident'] = self.resident.data()
        if self.commerce: save_data['commerce'] = self.commerce.data()
        if self.industry: save_data['industry'] = self.industry.data()
        for item in self.items:
             if isinstance(item, Update): save_data[item.id_name] = item.level
        return save_data

    def save_to_file(self, filename=SAVE_FILE):
        """Saves the game state to a file."""
        try:
            save_data = self.data()
            # Use ensure_ascii=False for wider character support if needed
            json_string = json.dumps(save_data, indent=2, ensure_ascii=True)
            encoded_string = base64.b64encode(json_string.encode('utf-8')).decode('utf-8')
            with open(filename, 'w', encoding='utf-8') as f: f.write(encoded_string)
            print(f"Game saved to {filename}")
        except Exception as e: print(f"Error saving game: {e}\n{traceback.format_exc()}")

    @staticmethod
    def load_from_file(filename=SAVE_FILE):
        """Loads game state from a file. Returns data dict or {}."""
        if not os.path.exists(filename): return {}
        try:
            with open(filename, 'r', encoding='utf-8') as f: encoded_string = f.read()
            try: decoded_string = base64.b64decode(encoded_string.encode('utf-8')).decode('utf-8')
            except (base64.binascii.Error, UnicodeDecodeError) as decode_error:
                print(f"Error decoding save file (possibly corrupted): {decode_error}. Starting new game.")
                return {}
            data = json.loads(decoded_string)
            print(f"Game loaded from {filename}")
            return data
        except json.JSONDecodeError as json_error: print(f"Error parsing save file JSON: {json_error}. Starting new game."); return {}
        except Exception as e: print(f"Error loading game: {e}\n{traceback.format_exc()}. Starting new game."); return {}


# --- GUI Classes ---

class ZonePanel(wx.Panel):
    """Panel holding the ListCtrl for one zone type."""
    def __init__(self, parent, zone_object):
        super().__init__(parent)
        self.zone = zone_object
        if not self.zone:
            sizer = wx.BoxSizer(wx.VERTICAL); txt = wx.StaticText(self, label="Zone data unavailable."); sizer.Add(txt, 1, wx.ALIGN_CENTER|wx.ALL, 10); self.SetSizer(sizer)
            self.list_ctrl = None # Ensure list_ctrl is None if zone is invalid
            return

        self.zone.panel = self
        box = wx.StaticBox(self, label=f"{zone_object.type_name} Zone ({zone_object.symbol})")
        main_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        self.list_ctrl = AccessibleListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.list_ctrl.InsertColumn(0, "Level", width=60)
        self.list_ctrl.InsertColumn(1, "Action/Cost", width=120)
        self.list_ctrl.InsertColumn(2, "Status", width=120)
        self.list_ctrl.setResizeColumn(2)

        # Populate initial items safely
        if self.zone.sizes:
            for i, size_data in enumerate(self.zone.sizes):
                if size_data: # Check if size_data is valid
                    idx = self.list_ctrl.InsertItem(i, size_data.label)
                    self.list_ctrl.SetItem(idx, 1, "Zone (...)")
                    self.list_ctrl.SetItem(idx, 2, "Built: 0 / Zoned: 0")
                    self.list_ctrl.SetItemData(idx, i)
                    size_data.tooltip_provider = lambda s=size_data: self.get_zone_size_tooltip(s)

        main_sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(main_sizer)

        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_buy_zone)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_deselected)

    def on_buy_zone(self, event):
        if not self.list_ctrl or not self.zone or not self.zone.city or not self.zone.sizes: return
        list_index = event.GetIndex()
        size_index = self.list_ctrl.GetItemData(list_index)
        if size_index is None or not (0 <= size_index < len(self.zone.sizes)): return

        size_data = self.zone.sizes[size_index]
        cost = size_data.price()
        can_afford = self.zone.city.currency >= cost
        is_visible = (size_index == 0 or (size_index > 0 and self.zone.sizes[size_index - 1].amount > 0))

        if can_afford and is_visible:
            if self.zone.buy(size_index):
                wx.CallAfter(wx.GetApp().GetTopWindow().update_ui) # Update after successful buy

    def on_item_selected(self, event):
        if not self.list_ctrl or not self.zone or not self.zone.sizes: return
        list_index = event.GetIndex()
        size_index = self.list_ctrl.GetItemData(list_index)
        if size_index is not None and (0 <= size_index < len(self.zone.sizes)):
             size_data = self.zone.sizes[size_index]
             if size_data and size_data.tooltip_provider:
                 tip_text = size_data.tooltip_provider()
                 self.list_ctrl.SetToolTip(tip_text)

    def on_item_deselected(self, event):
        if self.list_ctrl: self.list_ctrl.SetToolTip(None)

    def get_zone_size_tooltip(self, size_data):
        if not self.zone or not self.zone.city or not size_data: return "Zone info unavailable."
        city = self.zone.city; cost = size_data.price()
        lines = [
            f"--- Zone {size_data.label} ({self.zone.type_name}) ---",
            f"Action: Zone one level {size_data.label} area (Double-click/Enter)",
            f"Price: {format_currency(cost)}",
            f"Status: Built {size_data.built}, Zoned {size_data.amount}",
            f"Capacity/Zone: {format_generic(size_data.density, self.zone.symbol)}",
            f"Total Demand: {format_generic(self.zone.demand, self.zone.symbol)}",
            f"Total Built Cap: {format_generic(self.zone.total_capacity(), self.zone.symbol)}",
            f"Total Zoned Cap: {format_generic(self.zone.total_zoned_capacity(), self.zone.symbol)}",
            f"Income/sec: {format_currency(self.zone.income())}",
            f"Time to purchase: {format_time_needed(city, cost)}",
        ]
        return "\n".join(lines)

    def update_ui(self):
        if not self.list_ctrl or not self.zone or not self.zone.city or not self.zone.sizes: return
        city = self.zone.city; currency = city.currency

        for list_index in range(self.list_ctrl.GetItemCount()):
            size_index = self.list_ctrl.GetItemData(list_index)
            if size_index is None or not (0 <= size_index < len(self.zone.sizes)): continue
            size_data = self.zone.sizes[size_index]
            if not size_data: continue # Skip if size_data is invalid

            cost = size_data.price()
            can_afford = currency >= cost
            is_visible = (size_index == 0 or (size_index > 0 and self.zone.sizes[size_index - 1].amount > 0))

            self.list_ctrl.SetItem(list_index, 1, f"Zone ({format_currency(cost)})")
            self.list_ctrl.SetItem(list_index, 2, f"Built: {size_data.built} / Zoned: {size_data.amount}")

            if not is_visible: color = wx.Colour("grey")
            elif not can_afford: color = wx.Colour("orange red")
            else: color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
            self.list_ctrl.SetItemTextColour(list_index, color)


# --- CityFrame using ListCtrls ---

class CityFrame(wx.Frame):
    """Main application window using ListCtrls for interaction."""
    def __init__(self):
        try:
            super().__init__(None, title="CityClicker - List Accessible", size=(950, 850))
            loaded_data = City.load_from_file(SAVE_FILE)
            self.city = City(loaded_data)

            panel = wx.Panel(self)
            self.main_panel = panel
            main_sizer = wx.BoxSizer(wx.VERTICAL)
            self.main_sizer = main_sizer

            # Build UI sections
            self._build_status_area(panel, main_sizer)
            self._build_zones_area(panel, main_sizer)
            self._build_updates_list_area(panel, main_sizer)
            self._build_news_area(panel, main_sizer)

            panel.SetSizer(main_sizer)
            self.Layout()
            self.Centre()

            self.timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
            self.timer.Start(1000)
            self.Bind(wx.EVT_CLOSE, self.on_close)
            wx.CallAfter(self.update_ui) # Initial update after frame is shown

        except Exception as e:
            print(f"Critical error during CityFrame initialization: {e}\n{traceback.format_exc()}")
            try: wx.MessageBox(f"A critical error occurred during startup:\n{e}", "Startup Error", wx.OK | wx.ICON_ERROR)
            except: pass
            self.Destroy()

    def _build_status_area(self, parent_panel, parent_sizer):
        """Helper to build the status list area."""
        status_box = wx.StaticBox(parent_panel, label="City Status")
        status_box_sizer = wx.StaticBoxSizer(status_box, wx.VERTICAL)

        # --- CORRECTED LINE ---
        # Use the defined AccessibleListCtrl class, not the undefined StatusListCtrl
        self.status_list = AccessibleListCtrl(parent_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        # --- END CORRECTION ---

        self.status_list.InsertColumn(0, "Property", width=120)
        self.status_list.InsertColumn(1, "Value", wx.LIST_FORMAT_LEFT) # Let mixin handle width

        self.status_keys = ["City", "Date", "Population", "Treasury", "Income/sec"]
        for key in self.status_keys:
            idx = self.status_list.InsertItem(self.status_list.GetItemCount(), key)
            self.status_list.SetItem(idx, 1, "...") # Initial value

        status_box_sizer.Add(self.status_list, 0, wx.EXPAND | wx.ALL, 5) # Proportion 0 so it doesn't grow vertically
        parent_sizer.Add(status_box_sizer, 0, wx.EXPAND | wx.ALL, 5) # Add to the main vertical sizer

    def _build_zones_area(self, parent_panel, parent_sizer):
        # Builds the horizontal area containing the three ZonePanels (which now use lists)
        zone_area_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.res_panel = ZonePanel(parent_panel, self.city.resident) if self.city.resident else None
        self.com_panel = ZonePanel(parent_panel, self.city.commerce) if self.city.commerce else None
        self.ind_panel = ZonePanel(parent_panel, self.city.industry) if self.city.industry else None
        # Add panels if they were successfully created
        if self.res_panel: zone_area_sizer.Add(self.res_panel, 1, wx.EXPAND | wx.ALL, 5)
        if self.com_panel: zone_area_sizer.Add(self.com_panel, 1, wx.EXPAND | wx.ALL, 5)
        if self.ind_panel: zone_area_sizer.Add(self.ind_panel, 1, wx.EXPAND | wx.ALL, 5)
        parent_sizer.Add(zone_area_sizer, 3, wx.EXPAND | wx.ALL, 5) # Give zones more space

    def _build_updates_list_area(self, parent_panel, parent_sizer):
        # Builds the updates section using a ListCtrl
        updates_box = wx.StaticBox(parent_panel, label="City Improvements & Management")
        self.updates_box_sizer = wx.StaticBoxSizer(updates_box, wx.VERTICAL)
        self.updates_list_ctrl = AccessibleListCtrl(parent_panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.updates_list_ctrl.InsertColumn(0, "Upgrade", width=350)
        self.updates_list_ctrl.InsertColumn(1, "Action/Cost", width=150)
        self.updates_list_ctrl.setResizeColumn(0)

        # Populate list safely
        self.update_id_map = {}
        if self.city and self.city.items:
            list_idx = 0
            for item in self.city.items:
                if isinstance(item, Update):
                    message = item.get_current_message() or f"{item.id_name} (Max)"
                    idx = self.updates_list_ctrl.InsertItem(list_idx, message)
                    self.updates_list_ctrl.SetItem(idx, 1, "Purchase (...)")
                    self.updates_list_ctrl.SetItemData(idx, item.id_name)
                    self.update_id_map[list_idx] = item.id_name
                    item.tooltip_provider = lambda u=item: u.get_tooltip_text()
                    list_idx += 1

        self.updates_box_sizer.Add(self.updates_list_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        parent_sizer.Insert(2, self.updates_box_sizer, 2, wx.EXPAND | wx.ALL, 5) # Insert after zones

        self.updates_list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_buy_update)
        self.updates_list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_update_item_selected)
        self.updates_list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_update_item_deselected)

    def _build_news_area(self, parent_panel, parent_sizer):
        # Builds the news log area (unchanged logic)
        news_box = wx.StaticBox(parent_panel, label="City News Log")
        news_box_sizer = wx.StaticBoxSizer(news_box, wx.VERTICAL)
        self.news_display = wx.TextCtrl(parent_panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP | wx.BORDER_SUNKEN)
        news_font = self.news_display.GetFont(); news_font.SetFamily(wx.FONTFAMILY_TELETYPE); self.news_display.SetFont(news_font)
        self.news_display.SetValue("\n\n".join(self.city.news_log) if self.city and self.city.news_log else "News log is empty.")
        news_box_sizer.Add(self.news_display, 1, wx.EXPAND | wx.ALL, 5)
        parent_sizer.Insert(3, news_box_sizer, 1, wx.EXPAND | wx.ALL, 5) # Insert after updates

    # --- Event Handlers ---
    def on_timer(self, event):
        try:
            start_time = pytime.monotonic()
            if self.city: self.city.update(tick=True)
            self.update_ui()
            elapsed_ms = (pytime.monotonic() - start_time) * 1000
            delay = max(100, 1000 - elapsed_ms)
            self.timer.StartOnce(int(delay))
        except Exception as e: print(f"Error in timer event: {e}\n{traceback.format_exc()}")

    def on_update_item_selected(self, event):
        if not self.updates_list_ctrl: return
        list_index = event.GetIndex()
        update_id = self.updates_list_ctrl.GetItemData(list_index)
        if update_id and self.city:
            update_obj = next((item for item in self.city.items if isinstance(item, Update) and item.id_name == update_id), None)
            if update_obj and update_obj.tooltip_provider:
                 tip_text = update_obj.tooltip_provider()
                 self.updates_list_ctrl.SetToolTip(tip_text)

    def on_update_item_deselected(self, event):
        if self.updates_list_ctrl: self.updates_list_ctrl.SetToolTip(None)

    def on_buy_update(self, event):
        """Handle activation of an item in the updates list."""
        if not self.updates_list_ctrl or not self.city: return
        list_index = event.GetIndex()
        update_id = self.updates_list_ctrl.GetItemData(list_index)
        if not update_id: return
        update_obj = next((item for item in self.city.items if isinstance(item, Update) and item.id_name == update_id), None)
        if not update_obj: return

        try:
            cost = update_obj.price()
            can_afford = self.city.currency >= cost
            is_available = update_obj.get_current_message() is not None

            # --- Special Cases ---
            if update_id == 'rename':
                if can_afford:
                    dlg = wx.TextEntryDialog(self, f"Rename {self.city.name} to:", "Rename City", self.city.name)
                    if dlg.ShowModal() == wx.ID_OK:
                        new_name = dlg.GetValue().strip()
                        if new_name and update_obj.buy(): self.city.name = new_name; self.SetFocus()
                    dlg.Destroy()
                else: wx.MessageBox(f"Not enough currency! Cost: {format_currency(cost)}", "Cannot Rename", wx.OK | wx.ICON_WARNING)

            elif update_id == 'reset':
                 dlg = wx.MessageDialog(self, "Are you sure you want to reset?", "Confirm Reset", wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
                 if dlg.ShowModal() == wx.ID_YES: self.perform_reset()
                 dlg.Destroy()

            elif update_id == 'news':
                if can_afford:
                    if self.city.generate_news_report() is not None: # Buy happens inside
                        wx.CallAfter(self.update_ui)
                        if self.news_display: wx.CallAfter(self.news_display.SetFocus)
                else: wx.MessageBox(f"Not enough currency! Cost: {format_currency(cost)}", "Cannot Generate News", wx.OK | wx.ICON_WARNING)

            # --- Generic Purchase ---
            else:
                if can_afford and is_available:
                    if update_obj.buy(): wx.CallAfter(self.update_ui)
                # else: Provide feedback? Maybe color change is enough.

            # General UI update unless reset happened
            if update_id != 'reset': wx.CallAfter(self.update_ui)

        except Exception as e:
            print(f"Error processing update purchase ({update_id}): {e}\n{traceback.format_exc()}")
            wx.MessageBox(f"An error occurred processing the action:\n{e}", "Action Error", wx.OK | wx.ICON_ERROR)

    def perform_reset(self):
        """Helper function to handle the actual game reset steps."""
        print("Resetting game...")
        self.timer.Stop()
        if os.path.exists(SAVE_FILE):
            try: os.remove(SAVE_FILE)
            except OSError as e: print(f"Could not remove save file: {e}")

        # Re-initialize City
        self.city = City({})

        # Clear and Rebuild UI Areas
        self.main_sizer.Clear(delete_windows=True)
        self._build_status_area(self.main_panel, self.main_sizer)
        self._build_zones_area(self.main_panel, self.main_sizer)
        self._build_updates_list_area(self.main_panel, self.main_sizer)
        self._build_news_area(self.main_panel, self.main_sizer)

        # Refresh Layout and Restart
        self.main_panel.SetSizerAndFit(self.main_sizer) # Reset sizer and fit content
        self.main_panel.Layout() # Layout the panel
        self.Layout() # Layout the frame
        self.update_ui() # Update with new city state
        print("Game reset complete. Restarting timer.")
        self.timer.Start(1000)

    def update_ui(self):
        """Refreshes all UI elements with current game state."""
        if not self.city or not self.IsShown(): return

        try:
            # --- Update Status ListCtrl ---
            if self.status_list:
                status_values = {
                    "City": self.city.name, "Date": self.city.get_date_string(),
                    "Population": format_generic(self.city.population, '♥'),
                    "Treasury": format_currency(self.city.currency),
                    "Income/sec": format_currency(self.city.tax)
                }
                for i, key in enumerate(self.status_keys):
                    if i < self.status_list.GetItemCount():
                        self.status_list.SetItem(i, 1, status_values.get(key, "..."))

            # --- Update Zone Panels (which update their own lists) ---
            if self.res_panel: self.res_panel.update_ui()
            if self.com_panel: self.com_panel.update_ui()
            if self.ind_panel: self.ind_panel.update_ui()

            # --- Update Upgrades ListCtrl ---
            if self.updates_list_ctrl and self.city.items:
                currency = self.city.currency
                # Use Freeze/Thaw for potentially smoother updates on large lists
                self.updates_list_ctrl.Freeze()
                try:
                    for list_index in range(self.updates_list_ctrl.GetItemCount()):
                        update_id = self.updates_list_ctrl.GetItemData(list_index)
                        if not update_id: continue
                        update_obj = next((item for item in self.city.items if isinstance(item, Update) and item.id_name == update_id), None)
                        if not update_obj: continue

                        cost = update_obj.price()
                        message = update_obj.get_current_message()
                        can_afford = currency >= cost
                        is_available = message is not None

                        display_message = message if is_available else f"{update_obj.id_name} (Max)"
                        self.updates_list_ctrl.SetItem(list_index, 0, display_message)
                        cost_text = f"Purchase ({format_currency(cost)})" if is_available else "---"
                        if update_id == 'reset': cost_text = "Reset Game"
                        elif update_id == 'rename': cost_text = f"Rename ({format_currency(cost)})"
                        elif update_id == 'news': cost_text = f"Report ({format_currency(cost)})"
                        self.updates_list_ctrl.SetItem(list_index, 1, cost_text)

                        if not is_available: color = wx.Colour("grey")
                        elif not can_afford: color = wx.Colour("orange red")
                        else: color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
                        self.updates_list_ctrl.SetItemTextColour(list_index, color)
                finally:
                    self.updates_list_ctrl.Thaw()


            # --- Update News Display ---
            if self.news_display and self.city.news_log is not None:
                current_news_text = "\n\n".join(self.city.news_log)
                # Update only if changed, use CallAfter for safety
                if self.news_display.GetValue() != current_news_text:
                    wx.CallAfter(self.news_display.ChangeValue, current_news_text) # ChangeValue is better than SetValue here
                    wx.CallAfter(self.news_display.ShowPosition, self.news_display.GetLastPosition()) # Scroll to end


            # --- Final Layout Refresh ---
            # Layout might only be needed if sizers changed, which they don't often in update_ui
            # self.main_panel.Layout()
            pass

        except Exception as e:
            print(f"Error during UI update: {e}\n{traceback.format_exc()}")

    def on_close(self, event):
        print("Closing application...")
        if self.timer.IsRunning(): self.timer.Stop()
        if self.city: self.city.save_to_file(SAVE_FILE)
        # Allow the window to be destroyed
        event.Skip() # Important for proper closing


# --- Main Application ---
if __name__ == '__main__':
    # redirect=True, filename="error.log" might be useful for debugging release issues
    app = wx.App(redirect=False)
    frame = CityFrame()
    if frame: # Check if frame creation was successful
        frame.Show(True)
        app.MainLoop()
    else:
        print("Failed to create main application window.")