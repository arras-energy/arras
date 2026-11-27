# pylint: disable=line-too-long
"""Class `meter`: a node that meters the power through it

Syntax
------

    object meter {
        phases {A,B,C}[D|N];
        nominal_voltage <real> V;
        bill_mode {NONE,UNIFORM,TIERED,HOURLY,TIERED_RTP};
        price <real> $/kWh;
        monthly_fee <real> $;
        bill_day <integer>;
        first_tier_price <real> $/kWh;   // also second_, third_
        first_tier_energy <real> kWh;
        power_market <object>;           // HOURLY, TIERED_RTP
        measured_energy_delta_timestep <real> s;
        meter_power_consumption <complex> VA;
        // and the other properties of node
    }

Description
-----------

A `meter` is a `node` (gridlabd `PT_INHERIT "node"`). After each solution
it is expected to write, as gridlabd's `meter::postsync()` does:

- `measured_voltage_X` (the node's voltages) and `measured_voltage_XY`
  (line to line);
- `measured_current_X`: the current through the meter, which is the sum
  of the currents out of the links whose to node it is (its loads, its
  children's, and those of the network downstream, as gridlabd's
  `current_inj`), or, for a meter that no link feeds (a swing meter), the
  sum of the currents into the links whose from node it is;
- `measured_power_X = measured_voltage_X conj(measured_current_X)`, their
  sum `measured_power`, its real and reactive parts, and `measured_demand`,
  the largest real power;
- at each new time, `measured_real_energy` and `measured_reactive_energy`
  increased by the powers of the previous time times the time elapsed,
  and, every `measured_energy_delta_timestep` seconds when it is positive
  (a soft event), the energies over the interval and the voltages of
  largest and smallest magnitude (real and imaginary parts) and the
  average magnitude over the interval;
- the bill (`monthly_bill`, `monthly_energy`) of its `bill_mode`: the
  `monthly_fee` plus the month's energy at `price` (`UNIFORM`), at the
  tier prices (`TIERED`), or at the market price each hour (`HOURLY`; and
  the tiers above `price_base`, `TIERED_RTP`); at midnight on `bill_day`
  the bill and the energy move to `previous_monthly_bill` and
  `previous_monthly_energy` (the next bill day is a soft event).

`meter_power_consumption` is added to the node's power, shared between
its phases.

When it initializes, a meter is expected to check its prices (gridlabd's
`check_prices()`: missing second and third tiers take the previous tier's
values; tiers that decrease or are negative fail; real-time pricing
without a market fails; a market without the global
`powerflow::market_price_name` property fails), then initialize as a
`node`.

Caveats
-------

- The time is the model's clock in UTC for the bill day.
- Reliability (`customer_interrupted`), deltamode, and master/slave runs
  are not ported.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The interval voltage statistics are the voltages of largest and
   smallest magnitude and the time-weighted average magnitude over the
   interval's time steps; gridlabd's bookkeeping mixes line-to-neutral
   and line-to-line values and indexes (the reactive maximum line-to-
   neutral voltage takes the line-to-line one, the first sample is stored
   in phase A only).
2. The measured current of a meter that no link feeds leaves out its own
   loads (gridlabd's `current_inj` includes them).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/meter.cpp`, `meter.h`
"""

import datetime
from typing import Any

from ._base import prop, keywords
from ._common import (PHASE_A, PHASE_B, PHASE_C, ref, g, objects_of, object_state, get_int, get_double,
    get_complex, set_complex, set_double, PowerflowError)
from .node import Node, top_node

BM_NONE, BM_UNIFORM, BM_TIERED, BM_HOURLY, BM_TIERED_RTP = range(5)
"""`bill_mode` values"""

TIERS = ("first", "second", "third")

METER_PROPERTIES = (
    ('measured_real_energy[Wh]', 'double', prop('metered real energy consumption, cummalitive', flags="OUTPUT")),
    ('measured_real_energy_delta[Wh]', 'double', prop('delta in metered real energy consumption from last specified measured_energy_delta_timestep', flags="OUTPUT")),
    ('measured_reactive_energy[VAh]', 'double', prop('metered reactive energy consumption, cummalitive', flags="OUTPUT")),
    ('measured_reactive_energy_delta[VAh]', 'double', prop('delta in metered reactive energy consumption from last specified measured_energy_delta_timestep', flags="OUTPUT")),
    ('measured_energy_delta_timestep[s]', 'double', prop('Period of timestep for real and reactive delta energy calculation', '-1 s', flags="OUTPUT")),
    ('measured_power[VA]', 'complex', prop('metered complex power', flags="OUTPUT")),
    ('measured_power_A[VA]', 'complex', prop('metered complex power on phase A', flags="OUTPUT")),
    ('measured_power_B[VA]', 'complex', prop('metered complex power on phase B', flags="OUTPUT")),
    ('measured_power_C[VA]', 'complex', prop('metered complex power on phase C', flags="OUTPUT")),
    ('measured_demand[W]', 'double', prop('greatest metered real power during simulation', flags="OUTPUT")),
    ('measured_real_power[W]', 'double', prop('metered real power', flags="OUTPUT")),
    ('measured_reactive_power[VAr]', 'double', prop('metered reactive power', flags="OUTPUT")),
    ('meter_power_consumption[VA]', 'complex', prop('metered power used for operating the meter; standby and communication losses', flags="OUTPUT")),
    ('measured_voltage_A[V]', 'complex', prop('measured line-to-neutral voltage on phase A', flags="OUTPUT")),
    ('measured_voltage_B[V]', 'complex', prop('measured line-to-neutral voltage on phase B', flags="OUTPUT")),
    ('measured_voltage_C[V]', 'complex', prop('measured line-to-neutral voltage on phase C', flags="OUTPUT")),
    ('measured_voltage_AB[V]', 'complex', prop('measured line-to-line voltage on phase AB', flags="OUTPUT")),
    ('measured_voltage_BC[V]', 'complex', prop('measured line-to-line voltage on phase BC', flags="OUTPUT")),
    ('measured_voltage_CA[V]', 'complex', prop('measured line-to-line voltage on phase CA', flags="OUTPUT")),
    ('measured_real_max_voltage_in_interval_A', 'double', prop('measured real max line-to-neutral voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_real_max_voltage_in_interval_B', 'double', prop('measured real max line-to-neutral voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_real_max_voltage_in_interval_C', 'double', prop('measured real max line-to-neutral voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_reactive_max_voltage_in_interval_A', 'double', prop('measured reactive max line-to-neutral voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_reactive_max_voltage_in_interval_B', 'double', prop('measured reactive max line-to-neutral voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_reactive_max_voltage_in_interval_C', 'double', prop('measured reactive max line-to-neutral voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_real_max_voltage_in_interval_AB', 'double', prop('measured real max line-to-line voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_real_max_voltage_in_interval_BC', 'double', prop('measured real max line-to-line voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_real_max_voltage_in_interval_CA', 'double', prop('measured real max line-to-line voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_reactive_max_voltage_in_interval_AB', 'double', prop('measured reactive max line-to-line voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_reactive_max_voltage_in_interval_BC', 'double', prop('measured reactive max line-to-line voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_reactive_max_voltage_in_interval_CA', 'double', prop('measured reactive max line-to-line voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_real_min_voltage_in_interval_A', 'double', prop('measured real min line-to-neutral voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_real_min_voltage_in_interval_B', 'double', prop('measured real min line-to-neutral voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_real_min_voltage_in_interval_C', 'double', prop('measured real min line-to-neutral voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_reactive_min_voltage_in_interval_A', 'double', prop('measured reactive min line-to-neutral voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_reactive_min_voltage_in_interval_B', 'double', prop('measured reactive min line-to-neutral voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_reactive_min_voltage_in_interval_C', 'double', prop('measured reactive min line-to-neutral voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_real_min_voltage_in_interval_AB', 'double', prop('measured real min line-to-line voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_real_min_voltage_in_interval_BC', 'double', prop('measured real min line-to-line voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_real_min_voltage_in_interval_CA', 'double', prop('measured real min line-to-line voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_reactive_min_voltage_in_interval_AB', 'double', prop('measured reactive min line-to-line voltage on phase A over a specified interval', flags="OUTPUT")),
    ('measured_reactive_min_voltage_in_interval_BC', 'double', prop('measured reactive min line-to-line voltage on phase B over a specified interval', flags="OUTPUT")),
    ('measured_reactive_min_voltage_in_interval_CA', 'double', prop('measured reactive min line-to-line voltage on phase C over a specified interval', flags="OUTPUT")),
    ('measured_avg_voltage_mag_in_interval_A', 'double', prop('measured avg line-to-neutral voltage magnitude on phase A over a specified interval', flags="OUTPUT")),
    ('measured_avg_voltage_mag_in_interval_B', 'double', prop('measured avg line-to-neutral voltage magnitude on phase B over a specified interval', flags="OUTPUT")),
    ('measured_avg_voltage_mag_in_interval_C', 'double', prop('measured avg line-to-neutral voltage magnitude on phase C over a specified interval', flags="OUTPUT")),
    ('measured_avg_voltage_mag_in_interval_AB', 'double', prop('measured avg line-to-line voltage magnitude on phase A over a specified interval', flags="OUTPUT")),
    ('measured_avg_voltage_mag_in_interval_BC', 'double', prop('measured avg line-to-line voltage magnitude on phase B over a specified interval', flags="OUTPUT")),
    ('measured_avg_voltage_mag_in_interval_CA', 'double', prop('measured avg line-to-line voltage magnitude on phase C over a specified interval', flags="OUTPUT")),
    ('measured_current_A[A]', 'complex', prop('measured current on phase A', flags="OUTPUT")),
    ('measured_current_B[A]', 'complex', prop('measured current on phase B', flags="OUTPUT")),
    ('measured_current_C[A]', 'complex', prop('measured current on phase C', flags="OUTPUT")),
    ('customer_interrupted', 'bool', prop("Reliability flag - goes active if the customer is in an 'interrupted' state", flags="OUTPUT")),
    ('customer_interrupted_secondary', 'bool', prop("Reliability flag - goes active if the customer is in an 'secondary interrupted' state - i.e., momentary", flags="OUTPUT")),
    ('monthly_bill[$]', 'double', prop("Accumulator for the current month's bill", flags="OUTPUT")),
    ('previous_monthly_bill[$]', 'double', prop('Total monthly bill for the previous month', flags="OUTPUT")),
    ('previous_monthly_energy[kWh]', 'double', prop('Total monthly energy for the previous month', flags="OUTPUT")),
    ('monthly_fee[$]', 'double', prop('Once a month flat fee for customer hook-up', flags="OUTPUT")),
    ('monthly_energy[kWh]', 'double', prop("Accumulator for the current month's energy consumption", flags="OUTPUT")),
    ('bill_mode', 'enumeration', prop('Billing structure desired', 'NONE', keywords=keywords(('NONE', 0), ('UNIFORM', 1), ('TIERED', 2), ('HOURLY', 3), ('TIERED_RTP', 4)))),
    ('power_market', 'object', prop('Market (auction object) where the price is being received from')),
    ('bill_day', 'int32', prop('day of month bill is to be processed (currently limited to days 1-28)', '15')),
    ('price[$/kWh]', 'double', prop('current price of electricity')),
    ('price_base[$/kWh]', 'double', prop('Used only in TIERED_RTP mode to describe the price before the first tier')),
    ('first_tier_price[$/kWh]', 'double', prop('price of electricity between first tier and second tier energy usage')),
    ('first_tier_energy[kWh]', 'double', prop('switching point between base price and first tier price')),
    ('second_tier_price[$/kWh]', 'double', prop('price of electricity between second tier and third tier energy usage')),
    ('second_tier_energy[kWh]', 'double', prop('switching point between first tier price and second tier price')),
    ('third_tier_price[$/kWh]', 'double', prop('price of electricity when energy usage exceeds third tier energy usage')),
    ('third_tier_energy[kWh]', 'double', prop('switching point between second tier price and third tier price')),
    ('service_level', 'enumeration', prop('indicates the level of service required for the customer served by this meter', 'NORMAL', keywords=keywords(('LOW', 0), ('NORMAL', 1), ('HIGH', 2), ('CRITICAL', 3)))),
)
"""Properties of class `meter` (gridlabd's descriptions)"""

def link_currents(model:Any, name:str, slots:int) -> list[complex]:
    """Current through a node: the currents out of the links that feed it,
    or into the links it feeds when none does (by slot)"""
    top = top_node(model, name)
    inflow = [0j]*slots
    outflow = [0j]*slots
    fed = False
    for link in objects_of(model, "link"):
        if top_node(model, ref(model, link, "to")) == top:
            fed = True
            for k in range(slots):
                inflow[k] += get_complex(model, link, f"current_out_{'ABC'[k]}")
        elif top_node(model, ref(model, link, "from")) == top:
            for k in range(slots):
                outflow[k] += get_complex(model, link, f"current_in_{'ABC'[k]}")
    return inflow if fed else outflow

class Metering: # pylint: disable=too-few-public-methods
    """Energy, interval, and billing logic of `meter` and `triplex_meter`
    (mixed into their behavior classes)"""

    INTERVAL = ()
    """Interval statistics: `(voltage property, real max, imag max, real
    min, imag min, average)` property names"""

    @classmethod
    def check_prices(cls, model:Any, name:str, label:str) -> None:
        """gridlabd's `check_prices()` and the market check"""
        mode = get_int(model, name, "bill_mode")
        market = ref(model, name, "power_market")
        if market is not None:
            price_name = str(g(model, "market_price_name") or "current_market.clearing_price")
            if not model.objects[market].oclass.find_property(price_name):
                raise PowerflowError(f"triplex_meter::power_market object '{market}' does not publish '{price_name}'")
        if mode in (BM_TIERED, BM_TIERED_RTP):
            prices = [get_double(model, name, f"{t}_tier_price") for t in TIERS]
            energies = [get_double(model, name, f"{t}_tier_energy") for t in TIERS]
            for k in (1, 2):
                if prices[k] == 0:
                    prices[k], energies[k] = prices[k-1], energies[k-1]
            if energies[2] < energies[1] or energies[1] < energies[0]:
                raise PowerflowError(f"{label} energy tiers quantity trend improperly")
            if any(x < 0 for x in prices + energies):
                raise PowerflowError(f"{label} tiers cannot have negative values")
            for t, price, energy in zip(TIERS, prices, energies):
                set_double(model, name, f"{t}_tier_price", price)
                set_double(model, name, f"{t}_tier_energy", energy)
        if mode in (BM_HOURLY, BM_TIERED_RTP) and market is None:
            raise PowerflowError(f"{label} cannot use real time energy prices without a power market that publishes the next price")
        state = object_state(model, name)
        state.update(last_t=None, last_price=get_double(model, name, "price"), last_price_base=get_double(model, name, "price_base"),
            last_tier=[get_double(model, name, f"{t}_tier_price") for t in TIERS], previous_total=0.0, last_bill_month=-1,
            hourly=0.0, last_power=0.0, interval=None, delta_start=None, last_energy=(0.0, 0.0), step=None)

    @classmethod
    def meter_update(cls, model:Any, name:str, t0:int, voltages:list[complex], powers:list[complex]) -> None:
        """Energy, demand, intervals, and bill after a solution with the
        measured voltages and powers"""
        state = object_state(model, name)
        if "last_t" not in state:
            return
        dt = 0
        if state["last_t"] is None:
            state["last_t"] = t0
            state["delta_start"] = t0
        elif t0 > state["last_t"]:
            dt = t0 - state["last_t"]
            state["last_t"] = t0
        if dt > 0:
            set_double(model, name, "measured_real_energy", get_double(model, name, "measured_real_energy") + get_double(model, name, "measured_real_power")*dt/3600)
            set_double(model, name, "measured_reactive_energy", get_double(model, name, "measured_reactive_energy") + get_double(model, name, "measured_reactive_power")*dt/3600)
        total = sum(powers, 0j)
        set_complex(model, name, "measured_power", total)
        set_double(model, name, "measured_real_power", total.real)
        set_double(model, name, "measured_reactive_power", total.imag)
        if total.real > get_double(model, name, "measured_demand"):
            set_double(model, name, "measured_demand", total.real)
        cls.interval_update(model, name, t0, dt, voltages)
        cls.bill_update(model, name, t0, dt)

    @classmethod
    def interval_update(cls, model:Any, name:str, t0:int, dt:int, voltages:list[complex]) -> None:
        """Interval energies and voltage statistics"""
        # pylint: disable=too-many-locals
        state = object_state(model, name)
        step = get_double(model, name, "measured_energy_delta_timestep")
        if step <= 0:
            return
        interval = state["interval"]
        if interval is None:
            interval = state["interval"] = {"max": list(voltages), "min": list(voltages), "sum": [0.0]*len(voltages), "time": 0, "last": list(voltages)}
        else:
            for k, v in enumerate(voltages):
                if abs(v) > abs(interval["max"][k]):
                    interval["max"][k] = v
                if abs(v) < abs(interval["min"][k]):
                    interval["min"][k] = v
            if dt > 0:
                interval["sum"] = [s + abs(v)*dt for s, v in zip(interval["sum"], interval["last"])]
                interval["time"] += dt
            interval["last"] = list(voltages)
        if dt > 0 and t0 >= state["delta_start"] + step:
            real = get_double(model, name, "measured_real_energy")
            reactive = get_double(model, name, "measured_reactive_energy")
            set_double(model, name, "measured_real_energy_delta", real - state["last_energy"][0])
            set_double(model, name, "measured_reactive_energy_delta", reactive - state["last_energy"][1])
            state["last_energy"] = (real, reactive)
            state["delta_start"] = t0
            for k, names in enumerate(cls.INTERVAL):
                if k >= len(voltages):
                    break
                vmax, vmin = interval["max"][k], interval["min"][k]
                avg = interval["sum"][k]/interval["time"] if interval["time"] else abs(voltages[k])
                for prop_, value in zip(names[1:], (vmax.real, vmax.imag, vmin.real, vmin.imag, avg)):
                    set_double(model, name, prop_, value)
            state["interval"] = {"max": list(voltages), "min": list(voltages), "sum": [0.0]*len(voltages), "time": 0, "last": list(voltages)}

    @classmethod
    def bill_update(cls, model:Any, name:str, t0:int, dt:int) -> None:
        """`postsync()` billing"""
        state = object_state(model, name)
        mode = get_int(model, name, "bill_mode")
        if mode in (BM_UNIFORM, BM_TIERED) and dt > 0:
            cls.process_bill(model, name, t0)
        if mode in (BM_HOURLY, BM_TIERED_RTP) and ref(model, name, "power_market") is not None:
            if dt > 0:
                state["hourly"] += dt/3600*get_double(model, name, "price")*state["last_power"]/1000
                cls.process_bill(model, name, t0)
            market = ref(model, name, "power_market")
            price = get_double(model, market, str(g(model, "market_price_name") or "current_market.clearing_price"))
            set_double(model, name, "price", price)
            state["last_price"] = price
            state["last_power"] = get_double(model, name, "measured_real_power")

    @classmethod
    def process_bill(cls, model:Any, name:str, t1:int) -> float:
        """gridlabd's `process_bill()`"""
        state = object_state(model, name)
        when = datetime.datetime.fromtimestamp(t1, datetime.timezone.utc)
        energy = get_double(model, name, "measured_real_energy")/1000 - state["previous_total"]
        bill = get_double(model, name, "monthly_fee")
        mode = get_int(model, name, "bill_mode")
        tiers = [get_double(model, name, f"{t}_tier_energy") for t in TIERS]
        prices = state["last_tier"]
        def tiered(base:float) -> float:
            if energy < tiers[0]:
                return base*energy
            if energy < tiers[1]:
                return base*tiers[0] + prices[0]*(energy - tiers[0])
            if energy < tiers[2]:
                return base*tiers[0] + prices[0]*(tiers[1] - tiers[0]) + prices[1]*(energy - tiers[1])
            return base*tiers[0] + prices[0]*(tiers[1] - tiers[0]) + prices[1]*(tiers[2] - tiers[1]) + prices[2]*(energy - tiers[2])
        if mode == BM_UNIFORM:
            bill += energy*get_double(model, name, "price")
        elif mode == BM_TIERED:
            bill += tiered(state["last_price"])
        elif mode == BM_HOURLY:
            bill += state["hourly"]
        elif mode == BM_TIERED_RTP:
            bill += state["hourly"] + tiered(state["last_price_base"])
        set_double(model, name, "monthly_energy", energy)
        set_double(model, name, "monthly_bill", bill)
        if when.day == get_int(model, name, "bill_day") and when.hour == 0 and when.month != state["last_bill_month"]:
            set_double(model, name, "previous_monthly_bill", bill)
            set_double(model, name, "previous_monthly_energy", energy)
            state["previous_total"] = get_double(model, name, "measured_real_energy")/1000
            state["last_bill_month"] = when.month
            state["hourly"] = 0.0
        state["last_price"] = get_double(model, name, "price")
        state["last_price_base"] = get_double(model, name, "price_base")
        state["last_tier"] = [get_double(model, name, f"{t}_tier_price") for t in TIERS]
        return bill

    @classmethod
    def meter_event(cls, model:Any, name:str) -> int|None:
        """The next interval end or bill day (soft events)"""
        state = object_state(model, name)
        if state.get("last_t") is None:
            return None
        events = []
        step = get_double(model, name, "measured_energy_delta_timestep")
        if step > 0:
            events.append(state["delta_start"] + int(step))
        if get_int(model, name, "bill_mode") != BM_NONE:
            now = datetime.datetime.fromtimestamp(state["last_t"], datetime.timezone.utc)
            day = max(1, min(28, get_int(model, name, "bill_day")))
            year, month = (now.year, now.month + 1) if now.month < 12 else (now.year + 1, 1)
            candidate = datetime.datetime(now.year, now.month, day, tzinfo=datetime.timezone.utc)
            if candidate <= now:
                candidate = datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)
            events.append(int(candidate.timestamp()))
        return min(events) if events else None

class Meter(Metering, Node):
    """Behavior of class `meter`"""

    NAME = "meter"
    PARENT = "node"
    PROPERTIES = METER_PROPERTIES
    INTERVAL = tuple(("", f"measured_real_max_voltage_in_interval_{x}", f"measured_reactive_max_voltage_in_interval_{x}",
        f"measured_real_min_voltage_in_interval_{x}", f"measured_reactive_min_voltage_in_interval_{x}", f"measured_avg_voltage_mag_in_interval_{x}")
        for x in ("A", "B", "C", "AB", "BC", "CA"))

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`meter::init()`"""
        cls.check_prices(model, name, "meter")
        super().init_node(model, name)

    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]:
        """`meter_power_consumption`, shared between the phases"""
        consumption = get_complex(model, name, "meter_power_consumption")
        if consumption == 0:
            return {}
        phases = get_int(model, name, "phases")
        present = [x for x, bit in zip("ABC", (PHASE_A, PHASE_B, PHASE_C)) if phases & bit]
        return {("power", x): consumption/len(present) for x in present} if present else {}

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """`meter::postsync()`"""
        volts = [get_complex(model, name, f"voltage_{x}") for x in "ABC"]
        line = [volts[0] - volts[1], volts[1] - volts[2], volts[2] - volts[0]]
        for x, v in zip(("A", "B", "C", "AB", "BC", "CA"), volts + line):
            set_complex(model, name, f"measured_voltage_{x}", v)
        currents = link_currents(model, name, 3)
        powers = [v*i.conjugate() for v, i in zip(volts, currents)]
        for k, x in enumerate("ABC"):
            set_complex(model, name, f"measured_current_{x}", currents[k])
            set_complex(model, name, f"measured_power_{x}", powers[k])
        cls.meter_update(model, name, t0, volts + line, powers)
        return False

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        return cls.meter_event(model, name)

__all__ = ["Meter", "Metering", "link_currents"]
