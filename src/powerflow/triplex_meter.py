# pylint: disable=line-too-long
"""Class `triplex_meter`: a triplex node that meters the power through it

Syntax
------

    object triplex_meter {
        phases {A,B,C}S;
        nominal_voltage <real> V;
        bill_mode {NONE,UNIFORM,TIERED,HOURLY,TIERED_RTP};
        // and the other billing properties of meter, and those of triplex_node
    }

Description
-----------

A `triplex_meter` is a `triplex_node` (gridlabd `PT_INHERIT
"triplex_node"`) that meters as `meter` does, with gridlabd's triplex
conventions (`triplex_meter::postsync()`):

- `measured_voltage_1`, `measured_voltage_2`, `measured_voltage_12`, and
  `measured_voltage_N` (0) are the node's voltages;
- `measured_current_1` is the current of line 1 through the meter and
  `measured_current_2` that of line 2 in the physical direction (the
  negative of the line 2 current in the voltages' convention), and
  `measured_current_N = -(measured_current_1 + measured_current_2)`;
- `indiv_measured_power_1 = measured_voltage_1 conj(measured_current_1)`,
  `indiv_measured_power_2 = -measured_voltage_2 conj(measured_current_2)`,
  `indiv_measured_power_N = 0`, and their sum `measured_power`;
- energies, demand, interval statistics (of `voltage_1`, `voltage_2`,
  `voltage_12`), and the bill as `meter`.

`meter_power_consumption` is added half to line 1 and half to line 2.
The class creates the global `powerflow::market_price_name` (the market
property the real-time bill modes read, `current_market.clearing_price`
by default).

When it initializes, a triplex meter is expected to check its prices as
`meter` does (messages naming `triplex_meter`), then initialize as a
`triplex_node`.

Caveats
-------

- As for `meter`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. The interval voltage statistics as for `meter` (gridlabd's triplex
   average starts from `voltage_1` for all three).

References
----------

- `arras-energy/gridlabd`: `module/powerflow/triplex_meter.cpp`,
  `triplex_meter.h`
"""

from typing import Any

from ._base import prop, keywords
from ._common import get_complex, set_complex
from .meter import Metering, link_currents
from .triplex_node import TriplexNode

TRIPLEX_METER_PROPERTIES = (
    ('measured_real_energy[Wh]', 'double', prop('metered real energy consumption')),
    ('measured_real_energy_delta[Wh]', 'double', prop('delta in metered real energy consumption from last specified measured_energy_delta_timestep')),
    ('measured_reactive_energy[VAh]', 'double', prop('metered reactive energy consumption')),
    ('measured_reactive_energy_delta[VAh]', 'double', prop('delta in metered reactive energy consumption from last specified measured_energy_delta_timestep')),
    ('measured_energy_delta_timestep[s]', 'double', prop('Period of timestep for real and reactive delta energy calculation', '-1 s')),
    ('measured_power[VA]', 'complex', prop('metered power')),
    ('indiv_measured_power_1[VA]', 'complex', prop('metered power, phase 1')),
    ('indiv_measured_power_2[VA]', 'complex', prop('metered power, phase 2')),
    ('indiv_measured_power_N[VA]', 'complex', prop('metered power, phase N')),
    ('measured_demand[W]', 'double', prop('metered demand (peak of power)')),
    ('measured_real_power[W]', 'double', prop('metered real power')),
    ('measured_reactive_power[VAr]', 'double', prop('metered reactive power')),
    ('meter_power_consumption[VA]', 'complex', prop('power consumed by meter operation')),
    ('measured_voltage_1[V]', 'complex', prop('measured voltage, phase 1 to ground')),
    ('measured_voltage_2[V]', 'complex', prop('measured voltage, phase 2 to ground')),
    ('measured_voltage_12[V]', 'complex', prop('measured voltage, phase 1 to phase 2')),
    ('measured_voltage_N[V]', 'complex', prop('measured voltage, phase N to ground')),
    ('measured_real_max_voltage_1_in_interval', 'double', prop('measured real max line-to-ground voltage on phase 1 over a specified interval')),
    ('measured_real_max_voltage_2_in_interval', 'double', prop('measured real max line-to-ground voltage on phase 2 over a specified interval')),
    ('measured_real_max_voltage_12_in_interval', 'double', prop('measured real max line-to-ground voltage on phase 12 over a specified interval')),
    ('measured_imag_max_voltage_1_in_interval', 'double', prop('measured imaginary max line-to-ground voltage on phase 1 over a specified interval')),
    ('measured_imag_max_voltage_2_in_interval', 'double', prop('measured imaginary max line-to-ground voltage on phase 2 over a specified interval')),
    ('measured_imag_max_voltage_12_in_interval', 'double', prop('measured imaginary max line-to-ground voltage on phase 12 over a specified interval')),
    ('measured_real_min_voltage_1_in_interval', 'double', prop('measured real min line-to-ground voltage on phase 1 over a specified interval')),
    ('measured_real_min_voltage_2_in_interval', 'double', prop('measured real min line-to-ground voltage on phase 2 over a specified interval')),
    ('measured_real_min_voltage_12_in_interval', 'double', prop('measured real min line-to-ground voltage on phase 12 over a specified interval')),
    ('measured_imag_min_voltage_1_in_interval', 'double', prop('measured imaginary min line-to-ground voltage on phase 1 over a specified interval')),
    ('measured_imag_min_voltage_2_in_interval', 'double', prop('measured imaginary min line-to-ground voltage on phase 2 over a specified interval')),
    ('measured_imag_min_voltage_12_in_interval', 'double', prop('measured imaginary min line-to-ground voltage on phase 12 over a specified interval')),
    ('measured_avg_voltage_mag_1_in_interval', 'double', prop('measured average line-to-ground voltage magnitude on phase 1 over a specified interval')),
    ('measured_avg_voltage_mag_2_in_interval', 'double', prop('measured average line-to-ground voltage magnitude on phase 2 over a specified interval')),
    ('measured_avg_voltage_mag_12_in_interval', 'double', prop('measured average line-to-ground voltage magnitude on phase 12 over a specified interval')),
    ('measured_current_1[A]', 'complex', prop('measured current, phase 1')),
    ('measured_current_2[A]', 'complex', prop('measured current, phase 2')),
    ('measured_current_N[A]', 'complex', prop('measured current, phase N')),
    ('customer_interrupted', 'bool', prop('Reliability flag - goes active if the customer is in an interrupted state')),
    ('customer_interrupted_secondary', 'bool', prop('Reliability flag - goes active if the customer is in a secondary interrupted state - i.e., momentary')),
    ('monthly_bill[$]', 'double', prop("Accumulator for the current month's bill")),
    ('previous_monthly_bill[$]', 'double', prop('Total monthly bill for the previous month')),
    ('previous_monthly_energy[kWh]', 'double', prop('')),
    ('monthly_fee[$]', 'double', prop('Total monthly energy for the previous month')),
    ('monthly_energy[kWh]', 'double', prop("Accumulator for the current month's energy")),
    ('bill_mode', 'enumeration', prop('Designates the bill mode to be used', 'NONE', keywords=keywords(('NONE', 0), ('UNIFORM', 1), ('TIERED', 2), ('HOURLY', 3), ('TIERED_RTP', 4)))),
    ('power_market', 'object', prop('Designates the auction object where prices are read from for bill mode')),
    ('bill_day', 'int32', prop('Day bill is to be processed (assumed to occur at midnight of that day)', '15')),
    ('price[$/kWh]', 'double', prop('Standard uniform pricing')),
    ('price_base[$/kWh]', 'double', prop('Used only in TIERED_RTP mode to describe the price before the first tier')),
    ('first_tier_price[$/kWh]', 'double', prop('first tier price of energy between first and second tier energy')),
    ('first_tier_energy[kWh]', 'double', prop('price of energy on tier above price or price base')),
    ('second_tier_price[$/kWh]', 'double', prop('first tier price of energy between second and third tier energy')),
    ('second_tier_energy[kWh]', 'double', prop('price of energy on tier above first tier')),
    ('third_tier_price[$/kWh]', 'double', prop('first tier price of energy greater than third tier energy')),
    ('third_tier_energy[kWh]', 'double', prop('price of energy on tier above second tier')),
    ('service_level', 'enumeration', prop('indicates the level of service required for the customer served by this meter', 'NORMAL', keywords=keywords(('LOW', 0), ('NORMAL', 1), ('HIGH', 2), ('CRITICAL', 3)))),
)
"""Properties of class `triplex_meter` (gridlabd's descriptions)"""

class TriplexMeter(Metering, TriplexNode):
    """Behavior of class `triplex_meter`"""

    NAME = "triplex_meter"
    PARENT = "triplex_node"
    PROPERTIES = TRIPLEX_METER_PROPERTIES
    INTERVAL = tuple(("", f"measured_real_max_voltage_{x}_in_interval", f"measured_imag_max_voltage_{x}_in_interval",
        f"measured_real_min_voltage_{x}_in_interval", f"measured_imag_min_voltage_{x}_in_interval", f"measured_avg_voltage_mag_{x}_in_interval")
        for x in ("1", "2", "12"))

    @classmethod
    def init_node(cls, model:Any, name:str) -> None:
        """`triplex_meter::init()`"""
        cls.check_prices(model, name, "triplex_meter")
        super().init_node(model, name)

    @classmethod
    def load_terms(cls, model:Any, name:str) -> dict[tuple[str,str],complex]:
        """Half of `meter_power_consumption` on each line"""
        consumption = get_complex(model, name, "meter_power_consumption")
        return {("power", "1"): consumption/2, ("power", "2"): consumption/2} if consumption != 0 else {}

    @classmethod
    def after_solve(cls, model:Any, name:str, t0:int) -> bool:
        """`triplex_meter::postsync()`"""
        v1, v2 = get_complex(model, name, "voltage_1"), get_complex(model, name, "voltage_2")
        for x, v in (("1", v1), ("2", v2), ("12", v1 + v2), ("N", 0j)):
            set_complex(model, name, f"measured_voltage_{x}", v)
        i1, i2 = link_currents(model, name, 2)
        i2 = -i2 # the physical direction
        currents = (i1, i2, -(i1 + i2))
        powers = [v1*i1.conjugate(), -v2*i2.conjugate(), 0j]
        for x, i, s in zip(("1", "2", "N"), currents, powers):
            set_complex(model, name, f"measured_current_{x}", i)
            set_complex(model, name, f"indiv_measured_power_{x}", s)
        cls.meter_update(model, name, t0, [v1, v2, v1 + v2], powers)
        return False

    @classmethod
    def next_event(cls, model:Any, name:str) -> int|None:
        return cls.meter_event(model, name)

__all__ = ["TriplexMeter"]
