# pylint: disable=line-too-long,too-many-lines,consider-using-min-builtin,consider-using-max-builtin,chained-comparison
# (the comparisons are kept as gridlabd writes them)
"""Class `house`: a single-family home with its HVAC system and panel

Syntax
------

    object house {
        parent <triplex_meter>;
        weather <climate>;
        floor_area <real> sf;
        thermal_integrity_level {VERY_LITTLE,LITTLE,BELOW_NORMAL,NORMAL,ABOVE_NORMAL,GOOD,VERY_GOOD,UNKNOWN};
        heating_system_type {NONE,GAS,HEAT_PUMP,RESISTANCE};
        cooling_system_type {NONE,ELECTRIC,HEAT_PUMP};
        auxiliary_system_type {NONE,ELECTRIC};
        auxiliary_strategy {NONE,DEADBAND,TIMER,LOCKOUT}[|...];
        fan_type {NONE,ONE_SPEED,TWO_SPEED};
        heating_setpoint <real> degF;
        cooling_setpoint <real> degF;
        thermostat_deadband <real> degF;
        air_temperature <real> degF;
        mass_temperature <real> degF;
        ...
    }

Description
-----------

A `house` (gridlabd's `house_e`) models the indoor air and mass
temperatures of a home with the equivalent thermal parameter (ETP)
model, the HVAC system and thermostat that control them, and a panel of
circuits that supplies the house's enduses (the HVAC load itself and the
`residential_enduse` objects whose parent is the house). It inherits the
properties of `residential_enduse`, whose enduse load is the HVAC
system's, and publishes `panel`, the enduse of the whole panel.

When it initializes, a house is expected to:

1. find its weather: the climate object named by `weather`, else the
   first `climate` object (with a warning when there are several and
   `weather` is set), whose `record.high` and `record.low` become the
   cooling and heating design temperatures; without a climate object, the
   `residential::default_outdoor_temperature`, `default_humidity`, and
   `default_solar` globals, after the warning "house_e: no climate data
   found, using static data"; it defers until the climate object has
   initialized;
2. attach to its parent `triplex_meter` or `triplex_node` (setting its
   `house_present`): the panel's 240 V circuits get the meter's
   `voltage_12`, and its 120 V circuits `voltage_1N` and `voltage_2N`; the
   meter's `service_status` switches the house off; without such a parent
   it warns and uses static voltages of 240 V and 120 V;
3. complete the property defaults as gridlabd's `house_e::init()` does:
   system types (including the legacy `system_type` flags), envelope
   R-values from `thermal_integrity_level`, window SHGC and R-value from the
   glazing properties, geometry, UA, thermal masses, the heating, cooling,
   and auxiliary capacities sized from the design conditions and rounded
   to standard sizes, fan airflow and power, motor efficiency, and a
   random initial air temperature between the setpoints when none is
   given;
4. attach the HVAC load to a 240 V circuit of the panel.

At each time step, the house is expected to:

1. (top-down) advance the air and mass temperatures over the time since
   its last update with the ETP solution, update the window opening model
   when it is active, and set the voltage factor of every circuit's
   enduse from the circuit voltage;
2. (bottom-up) run the thermostat (gridlabd's `plc_house()`), which
   switches the system between `OFF`, `HEAT`, `AUX`, and `COOL` from the
   air temperature, setpoints, deadband, override, and cycle-time limits;
   then update the HVAC power and heat output from the outdoor
   conditions (capacity and COP curves, latent heat, fan, motor losses),
   the sump pump, and the panel: each closed circuit's current is
   checked against its breaker (which may trip, reclose about five
   minutes later, or fail), and the circuit loads are added to the
   parent meter's `power_1`, `power_2`, `power_12` (constant power),
   `residential_nominal_current_1`, ... (constant current, which
   `powerflow` turns with the voltage angle), and `shunt_1`, ...
   (constant admittance), at the nominal 120 V and 240 V; then compute
   the ETP coefficients and the time at which the air temperature reaches
   the next thermostat event, rounded to `residential::system_dwell_time`;
3. (post-top-down) remove the loads it added from the parent meter.

The `panel` enduse sums the circuit loads; its `energy` and that of the
HVAC load accumulate at each time step as gridlabd's core does.

Caveats
-------

- Implicit enduses (`residential::implicit_enduses` other than `NONE`)
  need gridlabd's loadshapes and schedules, which `arras` does not model;
  a house fails to initialize unless `implicit_enduses` is `NONE`.
- The panel dump (`residential::paneldump_interval`), the smart breaker
  method `circuit`, curved and linear capacity curves (errors, as in
  gridlabd), the `FULL` motor model (a warning, as in gridlabd),
  thermal storage objects, and deltamode are not implemented; their
  properties and globals are published.
- Random values (initial air temperature, sump level, window openings,
  breaker trips) use a Python `random.Random` per object seeded with the
  `randomseed` global and the object id, so they differ from gridlabd's.
- `residential::default_line_voltage`, `default_line_current`, and
  `default_solar` are arrays in gridlabd; `arras` publishes the first
  element (see the package's Differences).

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. A house does not defer its initialization until its parent meter is
   initialized (`arras` initializes objects in creation order, and a
   parent is created before its children).
2. gridlabd's `include_solar_quadrant` keywords `H`, `N`, `E`, `S`, `W` are
   the bits 1, 2, 4, 8, 16 (`house_e.h` defines them as macros that
   replace the `ORIENTATION` names of `residential.h`); `arras` publishes
   the same values.

References
----------

- `arras-energy/gridlabd`: `module/residential/house_e.cpp`, `house_e.h`,
  `residential.h`, `solvers.cpp`, `source/solvers/etp.cpp`,
  `source/enduse.cpp`, `source/object.cpp` (`_object_sync()`)
- [House](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Residential/House.md)
  (`docs/Module/Residential/House.md`)
"""

import math
from typing import Any

from ._base import prop, keywords, enduse_properties
from ._common import (TS_NEVER, TS_INVALID, INIT_DEFER, TRL_PROVEN, KWPBTUPH, BTUPHPKW, BRK_OPEN, BRK_CLOSED, BRK_FAULT,
    X12, X23, X13, EUC_IS220, OV_NORMAL, OV_ON, OV_OFF, PS_OFF, PS_ON,
    Enduse, enduse_map, msg, g, isa, parent_of, ref, label, module_state, object_state, object_rng,
    get_double, get_complex, get_int, set_complex, set_int, gl_error, clip, sqrt, exp, fdiv, cdiv)
from .residential_enduse import ResidentialEnduse, EnduseMembers

#
# house_e.h enumerations
#
IEU_TYPICAL = 0x03170303
"""`residential::implicit_enduses` value `TYPICAL`"""

NO_SOLAR, HORIZONTAL, NORTH, EAST, SOUTH, WEST, ALLWALLS, ALL = 0x0, 0x1, 0x2, 0x4, 0x8, 0x10, 0x1e, 0x1f
"""`include_solar_quadrant` bits"""

HC_DEFAULT, HC_FLAT, HC_LINEAR, HC_CURVED = range(4)
"""Curve types (heating COP; the same values for the other curves)"""

SS_NONE, SS_OFF, SS_ON = range(3)
"""`sump_status` values"""

CS_NONE, CS_CURTAILED, CS_RECOVERING = range(3)
"""`curtailment` values"""

ST_NONE, ST_GAS, ST_AC, ST_AIR, ST_VAR, ST_RST = 0x00, 0x01, 0x02, 0x04, 0x08, 0x10
"""`system_type` bits"""

AX_NONE, AX_DEADBAND, AX_TIMER, AX_LOCKOUT = 0x0, 0x1, 0x2, 0x4
"""`auxiliary_strategy` bits"""

AT_UNKNOWN, AT_NONE, AT_ELECTRIC = range(3)
"""`auxiliary_system_type` values"""

HT_UNKNOWN, HT_NONE, HT_GAS, HT_HEAT_PUMP, HT_RESISTANCE = range(5)
"""`heating_system_type` values"""

CT_UNKNOWN, CT_NONE, CT_ELECTRIC = range(3)
"""`cooling_system_type` values"""

FT_UNKNOWN, FT_NONE, FT_ONE_SPEED, FT_TWO_SPEED = range(4)
"""`fan_type` values"""

GM_OTHER, GM_GLASS, GM_LOW_E_GLASS = range(3)
"""`glass_type` values"""

WF_NONE, WF_ALUMINUM, WF_THERMAL_BREAK, WF_WOOD, WF_INSULATED = range(5)
"""`window_frame` values"""

GT_OTHER, GT_CLEAR, GT_ABS, GT_REFL, GT_LOW_S, GT_HIGH_S = range(6)
"""`glazing_treatment` values"""

GL_ONE, GL_TWO, GL_THREE, GL_OTHER = 1, 2, 3, 4
"""`glazing_layers` values"""

TI_VERY_LITTLE, TI_LITTLE, TI_BELOW_NORMAL, TI_NORMAL, TI_ABOVE_NORMAL, TI_GOOD, TI_VERY_GOOD, TI_UNKNOWN = range(8)
"""`thermal_integrity_level` values"""

MM_NONE, MM_BASIC, MM_FULL = range(3)
"""`motor_model` values"""

ME_VERY_POOR, ME_POOR, ME_AVERAGE, ME_GOOD, ME_VERY_GOOD = range(5)
"""`motor_efficiency` values"""

SM_UNKNOWN, SM_OFF, SM_HEAT, SM_AUX, SM_COOL = range(5)
"""`system_mode` values"""

TM_OFF, TM_AUTO, TM_HEAT, TM_COOL = range(4)
"""`thermostat_mode` values"""

TC_FULL, TC_BAND, TC_NONE = range(3)
"""`thermostat_control` values"""

THERMAL_INTEGRITY = {
    TI_VERY_LITTLE: (11, 4, 4, 3, 1/1.27, 1.5),
    TI_LITTLE: (19, 11, 4, 3, 1/0.81, 1.5),
    TI_BELOW_NORMAL: (19, 11, 11, 3, 1/0.81, 1.0),
    TI_NORMAL: (30, 11, 11, 3, 1/0.6, 1.0),
    TI_ABOVE_NORMAL: (30, 19, 19, 3, 1/0.6, 1.0),
    TI_GOOD: (30, 19, 22, 5, 1/0.47, 0.5),
    TI_VERY_GOOD: (48, 22, 30, 11, 1/0.31, 0.5),
}
"""`set_thermal_integrity()`: Rroof, Rwall, Rfloor, Rdoors, Rwindows, and
air changes per hour of each level"""

SHGC = {
    GL_ONE: {GT_CLEAR: (0.86, 0.75, 0.64), GT_ABS: (0.73, 0.64, 0.54), GT_REFL: (0.31, 0.28, 0.24)},
    GL_TWO: {GT_CLEAR: (0.76, 0.67, 0.57), GT_ABS: (0.62, 0.55, 0.46), GT_REFL: (0.29, 0.27, 0.22),
        GT_LOW_S: (0.41, 0.37, 0.31), GT_HIGH_S: (0.70, 0.62, 0.52)},
    GL_THREE: {GT_CLEAR: (0.68, 0.60, 0.51), GT_ABS: (0.34, 0.31, 0.26), GT_REFL: (0.34, 0.31, 0.26),
        GT_LOW_S: (0.27, 0.25, 0.21), GT_HIGH_S: (0.62, 0.55, 0.46)},
}
"""`set_window_shgc()`: SHGC by glazing layers and treatment, for frames
none, aluminum or thermal break, wood or insulated"""

RWINDOWS = {
    GM_LOW_E_GLASS: {GL_TWO: (1.0/0.30, 1.0/0.67, 1.0/0.47, 1.0/0.41, 1.0/0.33),
        GL_THREE: (1/0.27, 1/0.64, 1/0.43, 1/0.37, 1/0.31)},
    GM_GLASS: {GL_ONE: (1/1.04, 1/1.27, 1/1.08, 1/0.90, 1/0.81), GL_TWO: (1/0.48, 1/0.81, 1/0.60, 1/0.53, 1/0.44),
        GL_THREE: (1/0.31, 1/0.67, 1/0.46, 1/0.40, 1/0.34)},
}
"""`set_window_Rvalue()`: window R-value by glass type and layers, for
each frame"""

MOTOR_EFFICIENCY = {ME_VERY_POOR: 0.8236, ME_POOR: 0.8488, ME_AVERAGE: 0.8740, ME_GOOD: 0.9020, ME_VERY_GOOD: 0.9244}
"""HVAC motor efficiency of each `motor_efficiency` level"""

STATIC_VOLTAGES = (complex(240, 0), complex(120, 0), complex(120, 0))
"""`default_line_voltage`: circuit voltages without a parent meter"""

METER_VOLTAGES = ("voltage_12", "voltage_1N", "voltage_2N")
"""Parent voltages of circuit types 0, 1, 2 (gridlabd maps `voltage_12`
and assumes `voltage_1N` and `voltage_2N` follow it in memory)"""

def _uniform(rng:Any, lo:float, hi:float) -> float:
    """`gl_random_uniform()`"""
    return lo + (hi - lo)*rng.random()

def e2solve(a:float, n:float, b:float, m:float, c:float, p:float, iterations:int=100) -> float: # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-return-statements,too-many-branches,too-many-locals,arguments-out-of-order
    """`e2solve()` with gridlabd's `etp` solver: the smallest positive `t`
    of `a e^(n t) + b e^(m t) + c = 0` found by Newton's method from the
    point the solver picks, or `nan` (`source/solvers/etp.cpp`)"""
    def ev(t:float, a:float, n:float, b:float, m:float, c:float) -> float: # pylint: disable=too-many-arguments,too-many-positional-arguments
        return a*exp(n*t) + b*exp(m*t) + c
    nan = math.nan
    t = 0.0
    f = ev(t, a, n, b, m, c)
    if abs(fdiv(a, b)) < p:
        return math.log(-c/b)/m if c*b < 0 and abs(c) < abs(b) else nan
    if abs(fdiv(b, a)) < p: # pylint: disable=arguments-out-of-order
        return math.log(-c/a)/n if c*a < 0 and abs(c) < abs(a) else nan
    if a*b < 0:
        an_bm = -a*n/(b*m)
        tm = math.log(an_bm)/(m - n) if an_bm > 0 else nan
        fm = ev(tm, a, n, b, m, c)
        ti = math.log(an_bm*n/m)/(m - n) if an_bm*n/m > 0 else nan
        fi = ev(ti, a, n, b, m, c)
        if tm > 0:
            if f*fm < 0:
                t = 0.0
            elif c*fm < 0:
                t = ti
            else:
                return nan
        elif tm < 0 and ti > 0:
            if fm*c < 0:
                t = ti
            else:
                return nan
        elif ti < 0:
            if fi*c < 0:
                t = ti
            else:
                return nan
        else:
            return nan
    elif f*c > 0:
        return nan
    itr = iterations
    if t != 0:
        f = ev(t, a, n, b, m, c)
    dfdt = ev(t, a*n, n, b*m, m, 0)
    while abs(f) > p and math.isfinite(t):
        itr, ok = (itr - 1) & 0xffffffff, itr > 0 # unsigned int iter-->0
        if not ok:
            break
        t -= fdiv(f, dfdt)
        f = ev(t, a, n, b, m, c)
        dfdt = ev(t, a*n, n, b*m, m, 0)
    if itr == 0:
        gl_error(f"etp::solve(a={a:.4f},n={n:.4f},b={b:.4f},m={m:.4f},c={c:.4f},prec={p:g}) failed to converge")
        return nan
    if t <= 0 or math.isnan(t):
        return nan
    return t

class Circuit: # pylint: disable=too-few-public-methods,too-many-instance-attributes
    """gridlabd's `CIRCUIT`: a circuit of a house panel"""

    def __init__(self, cid:int, ctype:int, load:Enduse, max_amps:float, owner:str|None):
        self.id = cid
        self.type = ctype
        self.load = load
        """The circuit's enduse"""
        self.owner = owner
        """Name of the object whose enduse it is (`None` for the house's own
        HVAC load)"""
        self.max_amps = max_amps
        self.status = BRK_CLOSED
        self.reclose = 0
        self.tripsleft = 100
        self.smartfuse = {"powerRef": 0.0, "vFactor": 1.0, "vMin": 0.95, "vMax": 1.05}
        self.measurement = [{"t": 0, "power": 0j, "energy": 0j}, {"t": 0, "power": 0j, "energy": 0j}]
        self.view: Any = None
        """The panel's view of the owner's enduse members (`None` for the
        HVAC load)"""

def _members_map() -> tuple[tuple[str,str,str],...]:
    names = """weather:weather:s floor_area:floor_area:d gross_wall_area:gross_wall_area:d ceiling_height:ceiling_height:d aspect_ratio:aspect_ratio:d
        envelope_UA:envelope_UA:d window_wall_ratio:window_wall_ratio:d number_of_doors:number_of_doors:d exterior_wall_fraction:exterior_wall_fraction:d
        interior_exterior_wall_ratio:interior_exterior_wall_ratio:d exterior_ceiling_fraction:exterior_ceiling_fraction:d exterior_floor_fraction:exterior_floor_fraction:d
        glazing_shgc:window_shading:d window_exterior_transmission_coefficient:window_exterior_transmission_coefficient:d solar_heatgain_factor:solar_heatgain_factor:d
        airchange_per_hour:airchange_per_hour:d airchange_UA:airchange_UA:d UA:UA:d solar_load:solar_gain:d incident_solar_radiation:incident_solar_radiation:d
        include_solar_quadrant:include_solar_quadrant:i horizontal_diffuse_solar_radiation:horizontal_diffuse_solar_radiation:d
        north_incident_solar_radiation:north_incident_solar_radiation:d north_west_incident_solar_radiation:northwest_incident_solar_radiation:d
        west_incident_solar_radiation:west_incident_solar_radiation:d south_west_incident_solar_radiation:southwest_incident_solar_radiation:d
        south_incident_solar_radiation:south_incident_solar_radiation:d south_east_incident_solar_radiation:southeast_incident_solar_radiation:d
        east_incident_solar_radiation:east_incident_solar_radiation:d north_east_incident_solar_radiation:northeast_incident_solar_radiation:d
        heating_cop_curve:heating_cop_curve:i heating_cap_curve:heating_cap_curve:i cooling_cop_curve:cooling_cop_curve:i cooling_cap_curve:cooling_cap_curve:i
        use_latent_heat:use_latent_heat:i include_fan_heatgain:include_fan_heatgain:i thermostat_deadband:thermostat_deadband:d dlc_offset:dlc_offset:d
        thermostat_cycle_time:thermostat_cycle_time:i thermostat_off_cycle_time:thermostat_off_cycle_time:i thermostat_on_cycle_time:thermostat_on_cycle_time:i
        thermostat_last_cycle_time:thermostat_last_cycle_time:t heating_setpoint:heating_setpoint:d cooling_setpoint:cooling_setpoint:d
        design_heating_setpoint:design_heating_setpoint:d design_cooling_setpoint:design_cooling_setpoint:d over_sizing_factor:over_sizing_factor:d
        window_openings:simulate_window_openings:i window_open:is_window_open:d window_low_temp:window_low_temperature_cutoff:d
        window_high_temp:window_high_temperature_cutoff:d window_a:window_quadratic_coefficient:d window_b:window_linear_coefficient:d
        window_c:window_constant_coefficient:d window_temp_delta:window_temperature_delta:d design_heating_capacity:design_heating_capacity:d
        design_cooling_capacity:design_cooling_capacity:d cooling_design_temperature:cooling_design_temperature:d heating_design_temperature:heating_design_temperature:d
        design_peak_solar:design_peak_solar:d design_internal_gains:design_internal_gains:d air_heat_fraction:air_heat_fraction:d
        mass_solar_gain_fraction:mass_solar_gain_fraction:d mass_internal_gain_fraction:mass_internal_gain_fraction:d aux_heat_capacity:auxiliary_heat_capacity:d
        aux_heat_deadband:aux_heat_deadband:d aux_heat_temp_lockout:aux_heat_temperature_lockout:d aux_heat_time_delay:aux_heat_time_delay:d
        cooling_supply_air_temp:cooling_supply_air_temp:d heating_supply_air_temp:heating_supply_air_temp:d duct_pressure_drop:duct_pressure_drop:d
        fan_design_power:fan_design_power:d fan_low_power_fraction:fan_low_power_fraction:d fan_power:fan_power:d fan_design_airflow:fan_design_airflow:d
        fan_impedance_fraction:fan_impedance_fraction:d fan_power_fraction:fan_power_fraction:d fan_current_fraction:fan_current_fraction:d
        fan_power_factor:fan_power_factor:d heating_demand:heating_demand:d cooling_demand:cooling_demand:d heating_COP:heating_COP:d cooling_COP:cooling_COP:d
        Tair:air_temperature:d outside_temperature:outdoor_temperature:d outdoor_rh:outdoor_rh:d house_content_thermal_mass:mass_heat_capacity:d
        house_content_heat_transfer_coeff:mass_heat_coeff:d Tmaterials:mass_temperature:d volume:air_volume:d air_mass:air_mass:d
        air_thermal_mass:air_heat_capacity:d latent_load_fraction:latent_load_fraction:d total_thermal_mass_per_floor_area:total_thermal_mass_per_floor_area:d
        interior_surface_heat_transfer_coeff:interior_surface_heat_transfer_coeff:d number_of_stories:number_of_stories:d is_AUX_on:is_AUX_on:d
        is_HEAT_on:is_HEAT_on:d is_COOL_on:is_COOL_on:d thermal_storage_present:thermal_storage_present:d thermal_storage_inuse:thermal_storage_in_use:d
        thermostat_mode:thermostat_mode:i system_type:system_type:i auxiliary_strategy:auxiliary_strategy:i system_mode:system_mode:i
        last_system_mode:last_system_mode:i heating_system_type:heating_system_type:i cooling_system_type:cooling_system_type:i
        auxiliary_system_type:auxiliary_system_type:i fan_type:fan_type:i thermal_integrity_level:thermal_integrity_level:i glass_type:glass_type:i
        window_frame:window_frame:i glazing_treatment:glazing_treatment:i glazing_layers:glazing_layers:i motor_model:motor_model:i
        motor_efficiency:motor_efficiency:i last_mode_timer:last_mode_timer:i hvac_motor_efficiency:hvac_motor_efficiency:d
        hvac_motor_loss_power_factor:hvac_motor_loss_power_factor:d Rroof:Rroof:d Rwall:Rwall:d Rfloor:Rfloor:d Rwindows:Rwindows:d Rdoors:Rdoors:d
        hvac_breaker_rating:hvac_breaker_rating:d hvac_power_factor:hvac_power_factor:d hvac_load:hvac_load:d last_heating_load:last_heating_load:d
        last_cooling_load:last_cooling_load:d hvac_power:hvac_power:c total_load:total_load:d design_internal_gain_density:design_internal_gain_density:d
        compressor_on:compressor_on:i compressor_count:compressor_count:i hvac_last_on:hvac_last_on:t hvac_last_off:hvac_last_off:t
        hvac_period_length:hvac_period_length:d hvac_duty_cycle:hvac_duty_cycle:d sump_state:sump_state:d sump_power:sump_power:d sump_rate:sump_rate:d
        sump_status:sump_status:i curtailment_status:curtailment:i a:a:d b:b:d c:c:d d:d:d c1:c1:d c2:c2:d A3:A3:d A4:A4:d k1:k1:d k2:k2:d r1:r1:d r2:r2:d
        Teq:Teq:d Tevent:Tevent:d Qi:Qi:d Qa:Qa:d Qm:Qm:d Qlatent:Qlatent:d dTair:dTair:d adj_cooling_cap:adj_cooling_cap:d
        adj_heating_cap:adj_heating_cap:d adj_cooling_cop:adj_cooling_cop:d adj_heating_cop:adj_heating_cop:d thermostat_control:thermostat_control:i
        gas_enduses:gas_enduses:s""".split()
    return tuple(tuple(item.split(":")) for item in names) # type: ignore[misc]

class HouseMembers(EnduseMembers): # pylint: disable=too-many-instance-attributes
    """The members of a house (`house_e`): published, then internal"""

    MAP = (
        *EnduseMembers.MAP,
        *enduse_map("total", "panel"),
        *_members_map(),
        # aliases: gridlabd publishes these at the addresses of members above
        ("total.heatgain", "internal_gain", "d"),
        ("load.heatgain", "heat_cool_gain", "d"),
        ("load.heatgain", "Qh", "d"),
        ("load.power_fraction", "load_power_fraction", "d"),
        ("load.impedance_fraction", "load_impedance_fraction", "d"),
        ("load.current_fraction", "load_current_fraction", "d"),
    )

    def __init__(self, model:Any, name:str):
        super().__init__(model, name)
        # house_e::create(): the object memory is zeroed, then
        self.load = Enduse("HVAC")
        self.total = Enduse("panel")
        for member, _, kind in _members_map():
            setattr(self, member, {"d": 0.0, "c": 0j, "i": 0, "t": 0, "s": ""}[kind])
        self.last_temperature = 75.0
        self.default_frequency = 60.0
        self.error_flag = 0
        # unpublished members (zero)
        self.panel_max_amps = 0.0
        self.circuits: list[Circuit] = []
        self.voltage_source: str|None = None # parent meter whose voltages the circuits use
        self.window_roof_ratio = 0.0
        self.window_first_time_through = 0
        self.thermostat_last_off_cycle_time = 0
        self.thermostat_last_on_cycle_time = 0
        self.TcoolOn = self.TcoolOff = self.TheatOn = self.TheatOff = self.TauxOn = 0.0 # pylint: disable=invalid-name
        self.rated_heating_capacity = self.rated_cooling_capacity = 0.0
        self.system_rated_power = self.system_rated_capacity = 0.0
        self.hvac_motor_real_loss = self.hvac_motor_reactive_loss = 0.0
        self.sump_load = 0.0
        self.fan_heatgain_fraction = 0.0
        self.hvac_period_on = self.hvac_period_off = 0.0
        self.air_density = self.air_heat_capacity = 0.0
        self.simulation_beginning_time = 0
        self.heat_start = False
        self.load_values = [[0j]*3 for _ in range(3)]
        self.posted = [[0j]*3 for _ in range(3)]
        self.weather_values: dict[str,Any] = {}

_OUT = "OUTPUT"
_HID = {"flags": "OUTPUT", "access": "HIDDEN"}

class House(ResidentialEnduse): # pylint: disable=too-many-public-methods
    """Behavior of class `house`"""

    NAME = "house"
    PARENT = "residential_enduse"
    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|AUTOLOCK"
    TRL = TRL_PROVEN
    EVENTS = ("init", "presync", "sync", "postsync")
    MEMBERS = HouseMembers

    PROPERTIES = (
        ("weather", "object", prop("reference to the climate object")),
        ("floor_area[sf]", "double", prop("home conditioned floor area", "+0")),
        ("gross_wall_area[sf]", "double", prop("gross outdoor wall area", "+0")),
        ("ceiling_height[ft]", "double", prop("average ceiling height", "+0")),
        ("aspect_ratio", "double", prop("aspect ratio of the home's footprint", "+0")),
        ("envelope_UA[Btu/degF/h]", "double", prop("overall UA of the home's envelope", "+0")),
        ("window_wall_ratio", "double", prop("ratio of window area to wall area", "+0")),
        ("number_of_doors", "double", prop("ratio of door area to wall area", "+0")),
        ("exterior_wall_fraction", "double", prop("ratio of exterior wall area to total wall area", "+0")),
        ("interior_exterior_wall_ratio", "double", prop("ratio of interior to exterior walls", "+0")),
        ("exterior_ceiling_fraction", "double", prop("ratio of external ceiling sf to floor area", "+0")),
        ("exterior_floor_fraction", "double", prop("ratio of floor area used in UA calculation", "+0")),
        ("window_shading", "double", prop("transmission coefficient through window due to glazing", "+0")),
        ("window_exterior_transmission_coefficient", "double", prop("coefficient for the amount of energy that passes through window", "+0")),
        ("solar_heatgain_factor", "double", prop("product of the window area, window transmitivity, and the window exterior transmission coefficient", "+0", access="REFERENCE")),
        ("airchange_per_hour[unit/h]", "double", prop("number of air-changes per hour", "-1")),
        ("airchange_UA[Btu/degF/h]", "double", prop("additional UA due to air infiltration", "+0")),
        ("UA[Btu/degF/h]", "double", prop("the total UA", "-1")),
        ("internal_gain[Btu/h]", "double", prop("internal heat gains", "+0")),
        ("solar_gain[Btu/h]", "double", prop("solar heat gains", "+0")),
        ("incident_solar_radiation[Btu/h/sf]", "double", prop("average incident solar radiation hitting the house", "+0")),
        ("heat_cool_gain[Btu/h]", "double", prop("system heat gains(losses)", "+0")),
        ("include_solar_quadrant", "set", prop("bit set for determining which solar incidence quadrants should be included in the solar heatgain", "ALLWALLS",
            keywords=keywords(("NONE", NO_SOLAR), ("H", HORIZONTAL), ("N", NORTH), ("E", EAST), ("S", SOUTH), ("W", WEST), ("ALLWALLS", ALLWALLS), ("ALL", ALL)))),
        ("horizontal_diffuse_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the top of the house", "+0")),
        ("north_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the north side of the house", "+0")),
        ("northwest_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the northwest side of the house", "+0")),
        ("west_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the west side of the house", "+0")),
        ("southwest_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the southwest side of the house", "+0")),
        ("south_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the south side of the house", "+0")),
        ("southeast_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the southeast side of the house", "+0")),
        ("east_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the east side of the house", "+0")),
        ("northeast_incident_solar_radiation[Btu/h/sf]", "double", prop("incident solar radiation hitting the northeast side of the house", "+0")),
        ("heating_cop_curve", "enumeration", prop("Defines the function type to use for the adjusted heating COP as a function of outside air temperature.", "DEFAULT", keywords=keywords(("DEFAULT", 0), ("FLAT", 1), ("LINEAR", 2), ("CURVED", 3)))),
        ("heating_cap_curve", "enumeration", prop("Defines the function type to use for the adjusted heating capacity as a function of outside air temperature.", "DEFAULT", keywords=keywords(("DEFAULT", 0), ("FLAT", 1), ("LINEAR", 2), ("CURVED", 3)))),
        ("cooling_cop_curve", "enumeration", prop("Defines the function type to use for the adjusted cooling COP as a function of outside air temperature.", "DEFAULT", keywords=keywords(("DEFAULT", 0), ("FLAT", 1), ("LINEAR", 2), ("CURVED", 3)))),
        ("cooling_cap_curve", "enumeration", prop("Defines the function type to use for the adjusted cooling capacity as a function of outside air temperature.", "DEFAULT", keywords=keywords(("DEFAULT", 0), ("FLAT", 1), ("LINEAR", 2), ("CURVED", 3)))),
        ("use_latent_heat", "bool", prop("Boolean for using the heat latency of the air to the humidity when cooling.", "TRUE")),
        ("include_fan_heatgain", "bool", prop("Boolean to choose whether to include the heat generated by the fan in the ETP model.", "TRUE")),
        ("thermostat_deadband[degF]", "double", prop("deadband of thermostat control", "+0")),
        ("dlc_offset[degF]", "double", prop("used as a cap to offset the thermostat deadband for direct load control applications", "+0")),
        ("thermostat_cycle_time", "int16", prop("minimum time in seconds between thermostat updates", "0")),
        ("thermostat_off_cycle_time", "int16", prop("the minimum amount of time the thermostat cycle must stay in the off state", "-1")),
        ("thermostat_on_cycle_time", "int16", prop("the minimum amount of time the thermostat cycle must stay in the on state", "-1")),
        ("thermostat_last_cycle_time", "timestamp", prop("last time the thermostat changed state", "0")),
        ("heating_setpoint[degF]", "double", prop("thermostat heating setpoint", "+0")),
        ("cooling_setpoint[degF]", "double", prop("thermostat cooling setpoint", "+0")),
        ("design_heating_setpoint[degF]", "double", prop("system design heating setpoint", "+0")),
        ("design_cooling_setpoint[degF]", "double", prop("system design cooling setpoint", "+0")),
        ("over_sizing_factor", "double", prop("over sizes the heating and cooling system from standard specifications (0.2 ='s 120% sizing)", "+0")),
        ("simulate_window_openings", "bool", prop("activates a representation of an occupant opening a window and de-activating the HVAC system", "FALSE")),
        ("is_window_open", "double", prop("defines the state of the window opening, 1=open, 2=closed", "+0")),
        ("window_low_temperature_cutoff[degF]", "double", prop("lowest temperature at which the window opening might occur", "+60")),
        ("window_high_temperature_cutoff[degF]", "double", prop("highest temperature at which the window opening might occur", "+80")),
        ("window_quadratic_coefficient", "double", prop("quadratic coefficient for describing function between low and high temperature cutoffs", "+0")),
        ("window_linear_coefficient", "double", prop("linear coefficient for describing function between low and high temperature cutoffs", "+0")),
        ("window_constant_coefficient", "double", prop("constant coefficient for describing function between low and high temperature cutoffs", "+1")),
        ("window_temperature_delta", "double", prop("change in outdoor temperature required to update the window opening model", "+5")),
        ("design_heating_capacity[Btu/h]", "double", prop("system heating capacity", "+0")),
        ("design_cooling_capacity[Btu/h]", "double", prop("system cooling capacity", "+0")),
        ("cooling_design_temperature[degF]", "double", prop("system cooling design temperature", "+0")),
        ("heating_design_temperature[degF]", "double", prop("system heating design temperature", "+0")),
        ("design_peak_solar[Btu/h/sf]", "double", prop("system design solar load", "+0")),
        ("design_internal_gains[Btu/h]", "double", prop("system design internal gains", "+0")),
        ("air_heat_fraction[pu]", "double", prop("fraction of heat gain/loss that goes to air (as opposed to mass)", "+0")),
        ("mass_solar_gain_fraction[pu]", "double", prop("fraction of the heat gain/loss from the solar gains that goes to the mass", "+0")),
        ("mass_internal_gain_fraction[pu]", "double", prop("fraction of heat gain/loss from the internal gains that goes to the mass", "+0")),
        ("auxiliary_heat_capacity[Btu/h]", "double", prop("installed auxiliary heating capacity", "+0")),
        ("aux_heat_deadband[degF]", "double", prop("temperature offset from standard heat activation to auxiliary heat activation", "+0")),
        ("aux_heat_temperature_lockout[degF]", "double", prop("temperature at which auxiliary heat will not engage above", "+0")),
        ("aux_heat_time_delay[s]", "double", prop("time required for heater to run until auxiliary heating engages", "+0")),
        ("cooling_supply_air_temp[degF]", "double", prop("temperature of air blown out of the cooling system", "+50")),
        ("heating_supply_air_temp[degF]", "double", prop("temperature of air blown out of the heating system", "+150")),
        ("duct_pressure_drop[inH2O]", "double", prop("end-to-end pressure drop for the ventilation ducts, in inches of water", "+0")),
        ("fan_design_power[W]", "double", prop("designed maximum power draw of the ventilation fan", "-1")),
        ("fan_low_power_fraction[pu]", "double", prop("fraction of ventilation fan power draw during low-power mode (two-speed only)", "+0")),
        ("fan_power[kW]", "double", prop("current ventilation fan power draw", "+0", access="REFERENCE")),
        ("fan_design_airflow[cfm]", "double", prop("designed airflow for the ventilation system", "+0")),
        ("fan_impedance_fraction[pu]", "double", prop("Impedance component of fan ZIP load", "+0.2534")),
        ("fan_power_fraction[pu]", "double", prop("Power component of fan ZIP load", "+0.0135")),
        ("fan_current_fraction[pu]", "double", prop("Current component of fan ZIP load", "+0.7332")),
        ("fan_power_factor[pu]", "double", prop("Power factor of the fan load", "+0.96")),
        ("heating_demand[kW]", "double", prop("the current power draw to run the heating system", "+0", access="REFERENCE")),
        ("cooling_demand[kW]", "double", prop("the current power draw to run the cooling system", "+0", access="REFERENCE")),
        ("heating_COP[pu]", "double", prop("system heating performance coefficient", "+0")),
        ("cooling_COP[pu]", "double", prop("system cooling performance coefficient", "+0")),
        ("air_temperature[degF]", "double", prop("indoor air temperature", "+0", flags="DYNAMIC")),
        ("outdoor_temperature[degF]", "double", prop("outdoor air temperature", "+0")),
        ("outdoor_rh[%]", "double", prop("outdoor relative humidity", "+0")),
        ("mass_heat_capacity[Btu/degF]", "double", prop("interior mass heat capacity", "+0")),
        ("mass_heat_coeff[Btu/degF/h]", "double", prop("interior mass heat exchange coefficient", "+0")),
        ("mass_temperature[degF]", "double", prop("interior mass temperature", "+0", flags="DYNAMIC")),
        ("air_volume[cf]", "double", prop("air volume", "+0")),
        ("air_mass[lb]", "double", prop("air mass", "+0")),
        ("air_heat_capacity[Btu/degF]", "double", prop("air thermal mass", "+0")),
        ("latent_load_fraction[pu]", "double", prop("fractional increase in cooling load due to latent heat", "+0")),
        ("total_thermal_mass_per_floor_area[Btu/degF/sf]", "double", prop(None, "+0")),
        ("interior_surface_heat_transfer_coeff[Btu/h/degF/sf]", "double", prop(None, "+0")),
        ("number_of_stories", "double", prop("number of stories within the structure", "+0")),
        ("is_AUX_on", "double", prop("logic statement to determine population statistics - is the AUX on? 0 no, 1 yes", "+0", flags=_OUT)),
        ("is_HEAT_on", "double", prop("logic statement to determine population statistics - is the HEAT on? 0 no, 1 yes", "+0", flags=_OUT)),
        ("is_COOL_on", "double", prop("logic statement to determine population statistics - is the COOL on? 0 no, 1 yes", "+0", flags=_OUT)),
        ("thermal_storage_present", "double", prop("logic statement for determining if energy storage is present", "+0")),
        ("thermal_storage_in_use", "double", prop("logic statement for determining if energy storage is being utilized", "+0")),
        ("thermostat_mode", "enumeration", prop("tells the thermostat whether it is even allowed to heat or cool the house.", "AUTO", keywords=keywords(("OFF", TM_OFF), ("AUTO", TM_AUTO), ("HEAT", TM_HEAT), ("COOL", TM_COOL)))),
        ("system_type", "set", prop("heating/cooling system type/options", "NONE", keywords=keywords(("NONE", ST_NONE), ("GAS", ST_GAS), ("AIRCONDITIONING", ST_AC), ("FORCEDAIR", ST_AIR), ("TWOSTAGE", ST_VAR), ("RESISTIVE", ST_RST)))),
        ("auxiliary_strategy", "set", prop("auxiliary heating activation strategies", "NONE", keywords=keywords(("NONE", AX_NONE), ("DEADBAND", AX_DEADBAND), ("TIMER", AX_TIMER), ("LOCKOUT", AX_LOCKOUT)))),
        ("system_mode", "enumeration", prop("heating/cooling system operation state", "UNKNOWN", keywords=keywords(("UNKNOWN", SM_UNKNOWN), ("HEAT", SM_HEAT), ("OFF", SM_OFF), ("COOL", SM_COOL), ("AUX", SM_AUX)))),
        ("last_system_mode", "enumeration", prop("heating/cooling system operation state", "UNKNOWN", keywords=keywords(("UNKNOWN", SM_UNKNOWN), ("HEAT", SM_HEAT), ("OFF", SM_OFF), ("COOL", SM_COOL), ("AUX", SM_AUX)))),
        ("heating_system_type", "enumeration", prop("heating system type", "HEAT_PUMP", keywords=keywords(("UNKNOWN", HT_UNKNOWN), ("NONE", HT_NONE), ("GAS", HT_GAS), ("HEAT_PUMP", HT_HEAT_PUMP), ("RESISTANCE", HT_RESISTANCE)))),
        ("cooling_system_type", "enumeration", prop("cooling system type", "UNKNOWN", keywords=keywords(("UNKNOWN", CT_UNKNOWN), ("NONE", CT_NONE), ("ELECTRIC", CT_ELECTRIC), ("HEAT_PUMP", CT_ELECTRIC)))),
        ("auxiliary_system_type", "enumeration", prop("auxiliary heating type", "UNKNOWN", keywords=keywords(("UNKNOWN", AT_UNKNOWN), ("NONE", AT_NONE), ("ELECTRIC", AT_ELECTRIC)))),
        ("fan_type", "enumeration", prop("fan type", "UNKNOWN", keywords=keywords(("UNKNOWN", FT_UNKNOWN), ("NONE", FT_NONE), ("ONE_SPEED", FT_ONE_SPEED), ("TWO_SPEED", FT_TWO_SPEED)))),
        ("thermal_integrity_level", "enumeration", prop("default envelope UA settings", "UNKNOWN", keywords=keywords(("VERY_LITTLE", TI_VERY_LITTLE), ("LITTLE", TI_LITTLE), ("BELOW_NORMAL", TI_BELOW_NORMAL), ("NORMAL", TI_NORMAL), ("ABOVE_NORMAL", TI_ABOVE_NORMAL), ("GOOD", TI_GOOD), ("VERY_GOOD", TI_VERY_GOOD), ("UNKNOWN", TI_UNKNOWN)))),
        ("glass_type", "enumeration", prop("glass used in the windows", "LOW_E_GLASS", keywords=keywords(("OTHER", GM_OTHER), ("GLASS", GM_GLASS), ("LOW_E_GLASS", GM_LOW_E_GLASS)))),
        ("window_frame", "enumeration", prop("type of window frame", "THERMAL_BREAK", keywords=keywords(("NONE", WF_NONE), ("ALUMINUM", WF_ALUMINUM), ("ALUMINIUM", WF_ALUMINUM), ("THERMAL_BREAK", WF_THERMAL_BREAK), ("WOOD", WF_WOOD), ("INSULATED", WF_INSULATED)))),
        ("glazing_treatment", "enumeration", prop("the treatment to increase the reflectivity of the exterior windows", "CLEAR", keywords=keywords(("OTHER", GT_OTHER), ("CLEAR", GT_CLEAR), ("ABS", GT_ABS), ("REFL", GT_REFL), ("LOW_S", GT_LOW_S), ("HIGH_S", GT_HIGH_S)))),
        ("glazing_layers", "enumeration", prop("number of layers of glass in each window", "TWO", keywords=keywords(("ONE", GL_ONE), ("TWO", GL_TWO), ("THREE", GL_THREE), ("OTHER", GL_OTHER)))),
        ("motor_model", "enumeration", prop("indicates the level of detail used in modelling the hvac motor parameters", "NONE", keywords=keywords(("NONE", MM_NONE), ("BASIC", MM_BASIC), ("FULL", MM_FULL)))),
        ("motor_efficiency", "enumeration", prop("when using motor model, describes the efficiency of the motor", "AVERAGE", keywords=keywords(("VERY_POOR", ME_VERY_POOR), ("POOR", ME_POOR), ("AVERAGE", ME_AVERAGE), ("GOOD", ME_GOOD), ("VERY_GOOD", ME_VERY_GOOD)))),
        ("last_mode_timer", "int64", prop(flags=_OUT)),
        ("hvac_motor_efficiency[unit]", "double", prop("when using motor model, percent efficiency of hvac motor", "+1")),
        ("hvac_motor_loss_power_factor[unit]", "double", prop("when using motor model, power factor of motor losses", "+0.125")),
        ("Rroof[degF*sf*h/Btu]", "double", prop("roof R-value", "+0")),
        ("Rwall[degF*sf*h/Btu]", "double", prop("wall R-value", "+0")),
        ("Rfloor[degF*sf*h/Btu]", "double", prop("floor R-value", "+0")),
        ("Rwindows[degF*sf*h/Btu]", "double", prop("window R-value", "+0")),
        ("Rdoors[degF*sf*h/Btu]", "double", prop("door R-value", "+0")),
        ("hvac_breaker_rating[A]", "double", prop("determines the amount of current the HVAC circuit breaker can handle", "+0")),
        ("hvac_power_factor[unit]", "double", prop("power factor of hvac", "+0")),
        ("hvac_load[kW]", "double", prop("heating/cooling system load", flags=_OUT)),
        ("last_heating_load[kW]", "double", prop("stores the previous heating/cooling system load", flags=_OUT)),
        ("last_cooling_load[kW]", "double", prop("stores the previous heating/cooling system load", flags=_OUT)),
        ("hvac_power[kVA]", "complex", prop("describes hvac load complex power consumption", flags=_OUT)),
        ("total_load[kW]", "double", prop(flags=_OUT)),
        *enduse_properties("panel", flags=_OUT, description="total panel enduse load", defaults={"power_factor": "1", "heatgain_fraction": "1"}),
        ("design_internal_gain_density[W/sf]", "double", prop("average density of heat generating devices in the house", "+0.6")),
        ("compressor_on", "bool", prop(flags=_OUT)),
        ("compressor_count", "int64", prop(flags=_OUT)),
        ("hvac_last_on", "timestamp", prop(flags=_OUT)),
        ("hvac_last_off", "timestamp", prop(flags=_OUT)),
        ("hvac_period_length[s]", "double", prop(flags=_OUT)),
        ("hvac_duty_cycle", "double", prop(flags=_OUT)),
        ("sump_state[pu]", "double", prop("sump pit fill state")),
        ("sump_power[W]", "double", prop("sump pump rated power", "+800 W")),
        ("sump_rate[pu/min]", "double", prop("sump pump pit drainage rate", "2.0 pu/min")),
        ("sump_status", "enumeration", prop("sump pump running status", "NONE", keywords=keywords(("NONE", SS_NONE), ("ON", SS_ON), ("OFF", SS_OFF)))),
        ("curtailment", "enumeration", prop("curtailment status", "NONE", keywords=keywords(("NONE", CS_NONE), ("CURTAILED", CS_CURTAILED), ("RECOVERING", CS_RECOVERING)))),
        *((x, "double", prop(**_HID)) for x in ("a", "b", "c", "d", "c1", "c2", "A3", "A4", "k1", "k2", "r1", "r2", "Teq", "Tevent",
            "Qi", "Qa", "Qm", "Qh", "Qlatent", "dTair", "adj_cooling_cap", "adj_heating_cap", "adj_cooling_cop", "adj_heating_cop")),
        ("thermostat_control", "enumeration", prop("determine level of internal thermostatic control", "FULL", keywords=keywords(("FULL", TC_FULL), ("BAND", TC_BAND), ("NONE", TC_NONE)))),
        ("gas_enduses", "char1024", prop("list of implicit enduses that use gas instead of electricity", "")),
        ("circuit", "method", prop("smart breaker message handlers", access="PROTECTED")),
        ("load_power_fraction", "double", prop("fraction of total load that is constant power", "+0.8")),
        ("load_impedance_fraction", "double", prop("fraction of total load that is constant impedance", "+0.2")),
        ("load_current_fraction", "double", prop("fraction of total load that is constant current", "+0")),
    )

    #
    # Panel
    #
    @classmethod
    def attach(cls, model:Any, name:str, owner:str|None, load:Any, breaker_amps:float, is220:bool) -> Circuit: # pylint: disable=too-many-arguments,too-many-positional-arguments
        """`attach_enduse_house_e()` and `house_e::attach()`: a new circuit
        of the panel for an enduse (`load`: an `Enduse`, or the view of an
        enduse object's members); 240 V loads take two circuit numbers

        Exceptions
        ----------
        - `ResidentialError`: the breaker rating is below 0 or above 1000 A
        """
        from ._common import ResidentialError # pylint: disable=import-outside-toplevel
        if breaker_amps < 0 or breaker_amps > 1000:
            raise ResidentialError(f"attach_house_a: breaker amps of {int(breaker_amps)} unrealistic")
        m = cls.members(model, name)
        circuits = m.circuits
        cid = circuits[0].id + 1 if circuits else 1
        if is220:
            ctype = X12
            cid += 1
        elif cid & 0x01:
            ctype = X13
        else:
            ctype = X23
        enduse = load.load if hasattr(load, "MAP") else load
        circuit = Circuit(cid, ctype, enduse, breaker_amps, owner)
        circuit.view = load if hasattr(load, "MAP") else None
        circuits.insert(0, circuit)
        return circuit

    @classmethod
    def circuit_voltage(cls, model:Any, m:HouseMembers, circuit:Circuit) -> complex:
        """Voltage of a circuit (`*c->pV`): the parent meter's voltage of
        the circuit type, or the static voltage"""
        if m.voltage_source is None:
            return STATIC_VOLTAGES[circuit.type]
        return get_complex(model, m.voltage_source, METER_VOLTAGES[circuit.type])

    @classmethod
    def meter_status(cls, model:Any, m:HouseMembers) -> int:
        """`*pMeterStatus`: the parent's `service_status` (1 in service), or
        1 without a parent meter"""
        if m.voltage_source is None:
            return 1
        return get_int(model, m.voltage_source, "service_status")

    @classmethod
    def _views_load(cls, m:HouseMembers) -> None:
        for circuit in m.circuits:
            if circuit.view is not None:
                circuit.view.read()

    @classmethod
    def _views_save(cls, m:HouseMembers) -> None:
        for circuit in m.circuits:
            if circuit.view is not None:
                circuit.view.write()

    #
    # Weather
    #
    @classmethod
    def init_climate(cls, model:Any, name:str, m:HouseMembers) -> int:
        """`house_e::init_climate()`: 0 defers"""
        from climate._common import get_state # pylint: disable=import-outside-toplevel
        climates = [x for x in model.objects if isa(model, x, "climate", "climate")]
        mstate = module_state(model)
        if not climates:
            msg(model, name).warning("house_e: no climate data found, using static data")
            m.weather_values = {"source": None}
            return 1
        if len(climates) > 1 and m.weather and not mstate.climate_warned:
            msg(model, name).warning(f"house_e: {len(climates)} climates found, using first one defined")
        mstate.climate_warned = True
        obj = ref(model, name, "weather") if m.weather else None
        if obj is None:
            obj = climates[0]
            m.weather = obj
        m.weather_values = {"source": obj}
        for prop_, member in (("record.high", "cooling_design_temperature"), ("record.low", "heating_design_temperature")):
            if model.objects[obj].oclass.find_property(prop_) is not None:
                setattr(m, member, get_double(model, obj, prop_))
        if get_state(model, obj) is None:
            msg(model, name).verbose(f"house::init(): deferring initialization on {obj}")
            return 0
        return 1

    @classmethod
    def weather(cls, model:Any, m:HouseMembers) -> tuple[float,float,list[float],float,float]:
        """Outdoor temperature (degF), humidity, the nine solar fluxes
        (W/sf), rainfall, and snow depth (`*pTout`, `*pRhout`, `pSolar`,
        `*pRainfall`, `*pSnowdepth`)"""
        source = m.weather_values.get("source")
        if source is None:
            return (float(g(model, "default_outdoor_temperature")), float(g(model, "default_humidity")),
                [float(g(model, "default_solar"))] + [0.0]*8, 0.0, 0.0)
        import climate # pylint: disable=import-outside-toplevel
        def value(prop_:str) -> float:
            if model.objects[source].oclass.find_property(prop_) is None:
                return 0.0
            return get_double(model, source, prop_)
        try:
            solar = list(climate.solar_flux(model, source))
        except Exception: # pylint: disable=broad-exception-caught
            solar = [value("solar_flux")] + [0.0]*8
        return value("temperature"), value("humidity"), solar, value("rainfall"), value("snowdepth")

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int:
        """`init_house()`: `init_climate()`, then `house_e::init()`"""
        m = cls.members(model, name)
        m.read()
        if g(model, "implicit_enduses") != 0:
            msg(model, name).error("implicit enduses are not implemented; set residential::implicit_enduses to NONE")
            return False
        from ._common import init_failed # pylint: disable=import-outside-toplevel
        try:
            if cls.init_climate(model, name, m) == 0:
                m.write()
                return INIT_DEFER
            result = cls.init_object(model, name, m, t)
        except Exception as err: # pylint: disable=broad-exception-caught
            init_failed(model, name, err)
            return False
        m.write()
        if result is True or result == 1:
            module_state(model).initialized.add(name)
            return True
        return result

    @classmethod
    def init_object(cls, model:Any, name:str, m:HouseMembers, t:int) -> bool|int: # pylint: disable=arguments-differ,arguments-renamed,too-many-statements,too-many-branches,too-many-locals
        """`house_e::init()`"""
        from ._common import ResidentialError # pylint: disable=import-outside-toplevel
        obj = model.objects[name]
        parent = parent_of(model, name)
        m.heat_start = False
        if parent is not None and (isa(model, parent, "triplex_meter", "powerflow") or isa(model, parent, "triplex_node", "powerflow")):
            pclass = model.objects[parent].oclass
            for prop_ in (*METER_VOLTAGES[:1], "residential_nominal_current_1", "shunt_1", "power_1"):
                spec = pclass.find_property(prop_)
                if spec is None or spec.ptype != "complex":
                    pname = parent if parent != f"{pclass.name}:{model.objects[parent].id}" else "unnamed object"
                    raise ResidentialError(f"{pname} ({pclass.name}:{model.objects[parent].id}) does not implement triplex_meter variable {prop_} for {label(model, name)} (house_e:{obj.id})")
            if pclass.find_property("measured_frequency") is None:
                raise ResidentialError(f"{parent} ({pclass.name}:{model.objects[parent].id}) does not implement triplex_meter variable measured_frequency for {label(model, name)} (house_e:{obj.id})")
            spec = pclass.find_property("house_present")
            if spec is None or spec.ptype != "bool":
                msg(model, name).error(f"Failure to map powerflow variable from house:{label(model, name)}")
                return False
            set_int(model, parent, "house_present", 1)
            spec = pclass.find_property("service_status")
            if spec is None or spec.ptype != "enumeration":
                msg(model, name).error(f"Failure to map powerflow variable from house:{label(model, name)}")
                return False
            m.voltage_source = parent
        else:
            msg(model, name).warning(f"house_e:{obj.id} {'has no parent triplex_meter defined' if parent is None else 'parent is not a triplex_meter'}; using static voltages")
            m.voltage_source = None
        m.simulation_beginning_time = t
        if m.panel_max_amps == 0:
            m.panel_max_amps = 200
        m.load.power = 0j
        # old-style HVAC system variable mapping
        if m.system_type & ST_GAS:
            m.heating_system_type = HT_GAS
        elif m.system_type & ST_RST:
            m.heating_system_type = HT_RESISTANCE
        if m.system_type & ST_AC:
            m.cooling_system_type = CT_ELECTRIC
        if m.system_type & ST_AIR:
            m.fan_type = FT_ONE_SPEED
        if m.system_type & ST_VAR:
            m.fan_type = FT_TWO_SPEED
        if m.heating_system_type == HT_HEAT_PUMP and m.fan_type == FT_NONE:
            m.fan_type = FT_ONE_SPEED
        if m.system_type != 0:
            if m.heating_system_type == HT_UNKNOWN:
                m.heating_system_type = HT_NONE
            if m.cooling_system_type == CT_UNKNOWN:
                m.cooling_system_type = CT_NONE
            if m.fan_type == FT_UNKNOWN:
                m.fan_type = FT_NONE
            if m.auxiliary_system_type == AT_UNKNOWN:
                m.auxiliary_system_type = AT_NONE
                m.auxiliary_strategy = 0
        if m.system_type == 0:
            if m.heating_system_type == HT_UNKNOWN:
                m.heating_system_type = HT_HEAT_PUMP
            if m.cooling_system_type == CT_UNKNOWN:
                m.cooling_system_type = CT_ELECTRIC
            if m.fan_type == FT_UNKNOWN:
                m.fan_type = FT_ONE_SPEED
            if m.auxiliary_system_type == AT_UNKNOWN and m.heating_system_type == HT_HEAT_PUMP:
                m.auxiliary_system_type = AT_ELECTRIC
                m.auxiliary_strategy = AX_DEADBAND
        elif not m.system_type & ST_GAS and not m.system_type & ST_RST:
            m.auxiliary_system_type = AT_ELECTRIC
            m.auxiliary_strategy = AX_DEADBAND
        if m.heating_system_type == HT_HEAT_PUMP:
            if m.cooling_system_type == CT_NONE:
                msg(model, name).warning(f"A HEAT_PUMP heating_system_type with no air conditioning does not make a lot of sense. You may encounter odd behavior with house {label(model, name)}")
            elif m.cooling_system_type == CT_UNKNOWN:
                msg(model, name).warning("A HEAT_PUMP heating_system_type with no air conditioning does not make a lot of sense. Setting cooling_system_type to ELECTRIC.")
                m.cooling_system_type = CT_ELECTRIC
        cls.set_thermal_integrity(m)
        if m.heating_COP == 0.0:
            m.heating_COP = 2.5
        if m.heating_COP < 0.0:
            m.heating_COP = -m.heating_COP
        if m.cooling_COP == 0.0:
            m.cooling_COP = 3.5
        if m.cooling_COP < 0.0:
            m.cooling_COP = -m.cooling_COP
        if m.number_of_stories < 1.0:
            m.number_of_stories = 1.0
        if math.fmod(m.number_of_stories, 1.0) != 0.0:
            m.number_of_stories = math.floor(m.number_of_stories)
        if m.aspect_ratio == 0.0:
            m.aspect_ratio = 1.5
        if m.floor_area == 0:
            m.floor_area = 2500.0
        if m.ceiling_height == 0:
            m.ceiling_height = 8.0
        if m.gross_wall_area == 0:
            m.gross_wall_area = 2.0 * m.number_of_stories * (m.aspect_ratio + 1.0) * m.ceiling_height * sqrt(m.floor_area/m.aspect_ratio/m.number_of_stories)
        if m.window_wall_ratio == 0:
            m.window_wall_ratio = 0.15
        if m.window_roof_ratio == 0:
            m.window_roof_ratio = 0.0
        if m.number_of_doors == 0:
            m.number_of_doors = 4.0
        else:
            m.number_of_doors = math.floor(m.number_of_doors)
        if m.interior_exterior_wall_ratio == 0:
            m.interior_exterior_wall_ratio = 1.5
        if m.exterior_wall_fraction == 0:
            m.exterior_wall_fraction = 1.0
        if m.exterior_ceiling_fraction == 0:
            m.exterior_ceiling_fraction = 1.0
        if m.exterior_floor_fraction == 0:
            m.exterior_floor_fraction = 1.0
        if m.window_exterior_transmission_coefficient <= 0:
            m.window_exterior_transmission_coefficient = 0.60
        if m.glazing_shgc <= 0.0:
            cls.set_window_shgc(m)
        if m.Rroof <= 0:
            m.Rroof = 30.0
        if m.Rwall <= 0:
            m.Rwall = 19.0
        if m.Rfloor <= 0:
            m.Rfloor = 22.0
        if m.Rwindows <= 0:
            cls.set_window_Rvalue(model, name, m)
        if m.Rdoors <= 0:
            m.Rdoors = 5.0
        m.air_density = 0.0735
        m.air_heat_capacity = 0.2402
        if m.volume == 0:
            m.volume = m.ceiling_height*m.floor_area
        if m.air_mass == 0:
            m.air_mass = m.air_density*m.volume
        if m.air_thermal_mass == 0:
            m.air_thermal_mass = 3*m.air_heat_capacity*m.air_mass
        if m.air_heat_fraction != 0:
            msg(model, name).warning(f"The air_heat_fraction is no longer used to determine heat gain/loss to the air. Setting mass_solar_gain_fraction and mass_internal_gain_fraction to 1-air_heat_fraction specified for house {label(model, name)}.")
            m.mass_solar_gain_fraction = 1 - m.air_heat_fraction
            m.mass_internal_gain_fraction = 1 - m.air_heat_fraction
        if m.mass_solar_gain_fraction == 0:
            m.mass_solar_gain_fraction = 0.5
        if m.mass_internal_gain_fraction == 0:
            m.mass_internal_gain_fraction = 0.5
        if m.air_heat_fraction < 0.0 or m.air_heat_fraction > 1.0:
            raise ResidentialError("air heat fraction is not between 0 and 1")
        if m.mass_solar_gain_fraction < 0.0 or m.mass_solar_gain_fraction > 1.0:
            raise ResidentialError("the solar gain fraction to mass is not between 0 and 1")
        if m.mass_internal_gain_fraction < 0.0 or m.mass_internal_gain_fraction > 1.0:
            raise ResidentialError("the internal gain fraction to mass is not between 0 and 1")
        if m.total_thermal_mass_per_floor_area <= 0.0:
            m.total_thermal_mass_per_floor_area = 2.0
        if m.interior_surface_heat_transfer_coeff <= 0.0:
            m.interior_surface_heat_transfer_coeff = 1.46
        if m.airchange_per_hour < 0:
            m.airchange_per_hour = 0.5
        if m.airchange_UA <= 0:
            m.airchange_UA = m.airchange_per_hour * m.volume * m.air_density * m.air_heat_capacity
        door_area = m.number_of_doors * 3.0 * 78.0 / 12.0
        window_area = m.gross_wall_area * m.window_wall_ratio * m.exterior_wall_fraction
        net_exterior_wall_area = m.exterior_wall_fraction * m.gross_wall_area - window_area - door_area
        exterior_ceiling_area = m.floor_area * m.exterior_ceiling_fraction / m.number_of_stories
        exterior_floor_area = m.floor_area * m.exterior_floor_fraction / m.number_of_stories
        if m.envelope_UA == 0:
            m.envelope_UA = (fdiv(exterior_ceiling_area, m.Rroof) + fdiv(exterior_floor_area, m.Rfloor) + fdiv(net_exterior_wall_area, m.Rwall)
                + fdiv(window_area, m.Rwindows) + fdiv(door_area, m.Rdoors))
        if m.UA < 0:
            m.UA = m.envelope_UA + m.airchange_UA
        m.solar_heatgain_factor = window_area * m.glazing_shgc * m.window_exterior_transmission_coefficient
        if m.heating_setpoint == 0.0:
            m.heating_setpoint = 70.0
        if m.cooling_setpoint == 0.0:
            m.cooling_setpoint = 75.0
        if m.design_cooling_setpoint == 0.0:
            m.design_cooling_setpoint = 75.0
        if m.design_heating_setpoint == 0.0:
            m.design_heating_setpoint = 70.0
        if m.design_peak_solar <= 0.0:
            m.design_peak_solar = 195.0
        if m.thermostat_deadband <= 0.0:
            m.thermostat_deadband = 2.0
        if m.thermostat_cycle_time <= 0.0:
            m.thermostat_cycle_time = 120
        rng = object_state(model, name).setdefault("rng", object_rng(model, name))
        if m.Tair == 0.0:
            thigh = clip(m.cooling_setpoint + m.thermostat_deadband/2.0, 60.0, 140.0)
            tlow = clip(m.heating_setpoint - m.thermostat_deadband/2.0, 60.0, 140.0)
            m.Tair = _uniform(rng, tlow, thigh)
        if m.over_sizing_factor <= 0.0:
            m.over_sizing_factor = 0.0
        if m.cooling_design_temperature == 0.0:
            m.cooling_design_temperature = 95.0
        if m.design_internal_gains <= 0.0:
            m.design_internal_gains = 167.09 * m.floor_area**0.442
        if m.latent_load_fraction <= 0.0:
            m.latent_load_fraction = 0.30
        if m.design_cooling_capacity <= 0.0 and m.cooling_system_type != CT_NONE:
            m.design_cooling_capacity = (1.0 + m.over_sizing_factor) * (1.0 + m.latent_load_fraction) * (m.UA * (m.cooling_design_temperature - m.design_cooling_setpoint)
                + m.design_internal_gains + (m.design_peak_solar * m.solar_heatgain_factor))
            m.design_cooling_capacity = math.ceil(m.design_cooling_capacity / 6000.0) * 6000.0
        if m.auxiliary_system_type != AT_NONE and m.heating_system_type == HT_NONE:
            mstate = module_state(model)
            if not getattr(mstate, "aux_for_rst", False):
                msg(model, name).warning(f"house_e heating strategies with auxiliary heat but without normal heating modes are convertedto resistively heated houses, see house {label(model, name)}")
                mstate.aux_for_rst = True # type: ignore[attr-defined]
            m.heating_system_type = HT_RESISTANCE
        if m.design_heating_capacity <= 0 and m.heating_system_type != HT_NONE:
            if m.heating_system_type == HT_HEAT_PUMP:
                m.design_heating_capacity = m.design_cooling_capacity
            else:
                m.design_heating_capacity = (1.0 + m.over_sizing_factor) * m.UA * (m.design_heating_setpoint - m.heating_design_temperature)
                m.design_heating_capacity = math.ceil(m.design_heating_capacity / 10000.0) * 10000.0
        if m.system_mode == SM_UNKNOWN:
            m.system_mode = SM_OFF
        if m.last_system_mode == SM_UNKNOWN:
            m.last_system_mode = SM_OFF
        if m.last_mode_timer == 0:
            m.last_mode_timer = 3600*6
        if m.aux_heat_capacity <= 0.0 and m.auxiliary_system_type != AT_NONE:
            m.aux_heat_capacity = (1.0 + m.over_sizing_factor) * m.UA * (m.design_heating_setpoint - m.heating_design_temperature)
            m.aux_heat_capacity = math.ceil(m.aux_heat_capacity / 10000.0) * 10000.0
        if m.aux_heat_deadband <= 0.0:
            m.aux_heat_deadband = m.thermostat_deadband
        if m.aux_heat_temp_lockout <= 0.0:
            m.aux_heat_temp_lockout = 10
        if m.aux_heat_time_delay <= 0.0:
            m.aux_heat_time_delay = 300.0
        if m.duct_pressure_drop <= 0.0:
            m.duct_pressure_drop = 0.5
        if m.fan_design_airflow <= 0.0:
            design_heating_cfm = fdiv(m.design_heating_capacity if m.design_heating_capacity > m.aux_heat_capacity else m.aux_heat_capacity,
                m.air_density * m.air_heat_capacity * (m.heating_supply_air_temp - m.design_heating_setpoint)) / 60.0
            design_cooling_cfm = fdiv(m.design_cooling_capacity / (1.0 + m.latent_load_fraction),
                m.air_density * m.air_heat_capacity * (m.design_cooling_setpoint - m.cooling_supply_air_temp)) / 60.0
            m.fan_design_airflow = design_heating_cfm if design_heating_cfm > design_cooling_cfm else design_cooling_cfm
        if m.fan_design_power < 0.0:
            roundval = math.ceil((0.117 * m.duct_pressure_drop * m.fan_design_airflow / 0.42 / 745.7)*8)
            m.fan_design_power = roundval / 8.0 * 745.7 / 0.88
        if m.fan_low_power_fraction <= 0.0 and m.fan_type == FT_TWO_SPEED:
            m.fan_low_power_fraction = 0.5
        if m.fan_power <= 0.0:
            m.fan_power = 0.0
        if m.house_content_thermal_mass == 0:
            m.house_content_thermal_mass = m.total_thermal_mass_per_floor_area*m.floor_area - 2 * m.air_heat_capacity*m.air_mass
        if m.house_content_heat_transfer_coeff == 0:
            m.house_content_heat_transfer_coeff = m.interior_surface_heat_transfer_coeff * (
                (m.gross_wall_area - window_area - door_area)
                + m.gross_wall_area * m.interior_exterior_wall_ratio + m.number_of_stories * exterior_ceiling_area / m.exterior_ceiling_fraction)
        if m.Tair == 0:
            if m.system_mode == SM_OFF:
                m.Tair = _uniform(rng, m.heating_setpoint, m.cooling_setpoint)
            elif m.system_mode in (SM_HEAT, SM_AUX):
                m.Tair = _uniform(rng, m.heating_setpoint - m.thermostat_deadband/2, m.heating_setpoint + m.thermostat_deadband/2)
            elif m.system_mode == SM_COOL:
                m.Tair = _uniform(rng, m.cooling_setpoint - m.thermostat_deadband/2, m.cooling_setpoint + m.thermostat_deadband/2)
        if m.Tmaterials == 0.0:
            m.Tmaterials = m.Tair
        if m.motor_model != MM_NONE:
            if m.hvac_motor_loss_power_factor > 1 or m.hvac_motor_loss_power_factor < -1:
                raise ResidentialError("hvac_motor_power_factor must have a value between -1 and 1")
            if m.hvac_motor_efficiency > 1 or m.hvac_motor_efficiency < 0:
                raise ResidentialError("hvac_motor_efficiency must have a value between 0 and 1")
            if m.motor_efficiency in MOTOR_EFFICIENCY:
                m.hvac_motor_efficiency = MOTOR_EFFICIENCY[m.motor_efficiency]
            else:
                msg(model, name).warning("Unknown motor_efficiency setting.  Setting to AVERAGE.")
                m.hvac_motor_efficiency = 0.8740
                m.motor_efficiency = ME_AVERAGE
        if m.sump_rate <= 0:
            msg(model, name).error("sump rate must be positive")
        if m.sump_state == 0:
            m.sump_state = _uniform(rng, 0.0, 1.0)
        elif m.sump_state < 0:
            m.sump_state = _uniform(rng, 0.0, -m.sump_state)
        if m.sump_power <= 0:
            msg(model, name).error("sump power must be positive")
        cls.check_thermal(m)
        cls.etp_constants(m, False)
        m.outside_temperature = float(g(model, "default_outdoor_temperature"))
        m.load.power_factor = 0.97 if m.hvac_power_factor == 0 else m.hvac_power_factor
        # attach_implicit_enduses(): none (implicit enduses refused above)
        cls.update_system(model, name, m)
        if m.error_flag == 1:
            return False
        cls.update_model(model, name, m)
        cls.update_sump(model, m)
        if m.hvac_breaker_rating == 0:
            m.load.breaker_amps = 200
            m.hvac_breaker_rating = 200
        else:
            m.load.breaker_amps = m.hvac_breaker_rating
        m.load.config = EUC_IS220
        cls.attach(model, name, None, m.load, m.hvac_breaker_rating, True)
        m.fan_heatgain_fraction = 1 if m.include_fan_heatgain else 0
        if g(model, "all_house_delta") and g(model, "enable_subsecond_models"):
            pass # deltamode is not modeled
        if g(model, "enable_subsecond_models"):
            msg(model, name).warning(f"house_e:{obj.id} {name} - Deltamode is enabled for the module, but not this house!")
        curtailment = str(g(model, "curtailment_enduses") or "")
        for circuit in m.circuits:
            if circuit.load.name:
                circuit.load.gas_fraction = 1.0 if circuit.load.name in m.gas_enduses else 0.0
                circuit.load.curtailment_fraction = 0.0 if circuit.load.name in curtailment else 1.0
        return True

    @classmethod
    def set_thermal_integrity(cls, m:HouseMembers) -> None:
        """`house_e::set_thermal_integrity()`"""
        values = THERMAL_INTEGRITY.get(m.thermal_integrity_level)
        if values is None:
            return
        rroof, rwall, rfloor, rdoors, rwindows, ach = values
        if m.Rroof <= 0.0:
            m.Rroof = rroof
        if m.Rwall <= 0.0:
            m.Rwall = rwall
        if m.Rfloor <= 0.0:
            m.Rfloor = rfloor
        if m.Rdoors <= 0.0:
            m.Rdoors = rdoors
        if m.Rwindows <= 0.0:
            m.Rwindows = rwindows
        if m.airchange_per_hour < 0.0:
            m.airchange_per_hour = ach

    @classmethod
    def set_window_shgc(cls, m:HouseMembers) -> None:
        """`house_e::set_window_shgc()` (combinations without a value leave
        the SHGC unchanged)"""
        values = SHGC.get(m.glazing_layers, {}).get(m.glazing_treatment)
        frame = {WF_NONE: 0, WF_ALUMINUM: 1, WF_THERMAL_BREAK: 1, WF_WOOD: 2, WF_INSULATED: 2}.get(m.window_frame)
        if values is not None and frame is not None:
            m.glazing_shgc = values[frame]

    @classmethod
    def set_window_Rvalue(cls, model:Any, name:str, m:HouseMembers) -> None: # pylint: disable=invalid-name
        """`house_e::set_window_Rvalue()`"""
        if m.glass_type == GM_LOW_E_GLASS and m.glazing_layers == GL_ONE:
            msg(model, name).error("no value for one pane of low-e glass")
            return
        if m.glass_type in (GM_LOW_E_GLASS, GM_GLASS):
            values = RWINDOWS[m.glass_type].get(m.glazing_layers)
            if values is not None and 0 <= m.window_frame < len(values):
                m.Rwindows = values[m.window_frame]
        else:
            m.Rwindows = 2.0

    @classmethod
    def check_thermal(cls, m:HouseMembers) -> None:
        """The thermal parameter checks (`throw`)"""
        from ._common import ResidentialError # pylint: disable=import-outside-toplevel
        if m.air_thermal_mass <= 0:
            raise ResidentialError("air_thermal_mass must be positive")
        if m.house_content_thermal_mass <= 0:
            raise ResidentialError("house_content_thermal_mass must be positive")
        if m.house_content_heat_transfer_coeff <= 0:
            raise ResidentialError("house_content_heat_transfer_coeff must be positive")
        if m.UA < 0:
            raise ResidentialError("UA must be positive")

    @classmethod
    def etp_constants(cls, m:HouseMembers, window_open:bool) -> None:
        """The ETP constants `a`, `b`, `c`, `c1`, `c2`, `r1`, `r2`, `A3`,
        `A4`"""
        ca, cm, hm, ua = m.air_thermal_mass, m.house_content_thermal_mass, m.house_content_heat_transfer_coeff, m.UA
        uaw = 10*ua if window_open else ua
        m.a = cm*ca/hm
        m.b = cm*(uaw + hm)/hm + ca
        m.c = uaw
        m.c1 = -(uaw + hm)/ca
        m.c2 = hm/ca
        rr = sqrt(m.b*m.b - 4*m.a*m.c)/(2*m.a)
        r = -m.b/(2*m.a)
        m.r1 = r + rr
        m.r2 = r - rr
        m.A3 = ca/hm * m.r1 + (uaw + hm)/hm
        m.A4 = ca/hm * m.r2 + (uaw + hm)/hm

    #
    # Models
    #
    @classmethod
    def update_model(cls, model:Any, name:str, m:HouseMembers) -> None: # pylint: disable=unused-argument
        """`house_e::update_model()`: solar gains, ETP constants, and the
        initial condition of the next interval"""
        from ._common import ResidentialError # pylint: disable=import-outside-toplevel
        _, _, solar, _, _ = cls.weather(model, m)
        m.incident_solar_radiation = 0.0
        cls.check_thermal(m)
        cls.etp_constants(m, m.window_open == 1)
        (m.horizontal_diffuse_solar_radiation, m.north_incident_solar_radiation, m.north_east_incident_solar_radiation,
            m.east_incident_solar_radiation, m.south_east_incident_solar_radiation, m.south_incident_solar_radiation,
            m.south_west_incident_solar_radiation, m.west_incident_solar_radiation, m.north_west_incident_solar_radiation) = (3.412*x for x in solar[:9])
        quadrant = m.include_solar_quadrant
        incident = 0.0
        for bit, (side, left, right) in ((0x2, (1, 2, 8)), (0x4, (3, 2, 4)), (0x8, (5, 4, 6)), (0x10, (7, 6, 8))):
            if quadrant & bit == bit:
                incident += solar[side]
                incident += solar[left]/2
                incident += solar[right]/2
                if quadrant & 0x1 == 0x1:
                    incident += 2*solar[0]
        m.incident_solar_radiation = incident * 3.412/8
        m.solar_load = m.incident_solar_radiation*m.solar_heatgain_factor
        if m.solar_load < 0:
            raise ResidentialError("solar gain is negative")
        m.Qi = m.total.heatgain - m.load.heatgain
        m.Qa = m.load.heatgain + (1 - m.mass_internal_gain_fraction)*m.Qi + (1 - m.mass_solar_gain_fraction)*m.solar_load
        m.Qm = m.mass_internal_gain_fraction*m.Qi + m.mass_solar_gain_fraction*m.solar_load
        ua = 10*m.UA if m.window_open == 1 else m.UA
        m.d = m.Qa + m.Qm + ua*m.outside_temperature
        m.Teq = fdiv(m.d, m.c)
        m.dTair = m.c2*m.Tmaterials + m.c1*m.Tair - (m.c1 + m.c2)*m.outside_temperature + m.Qa/m.air_thermal_mass
        m.k1 = fdiv(m.r2*m.Tair - m.r2*m.Teq - m.dTair, m.r2 - m.r1)
        m.k2 = m.Tair - m.Teq - m.k1

    @classmethod
    def update_system(cls, model:Any, name:str, m:HouseMembers) -> None: # pylint: disable=too-many-statements,too-many-branches,too-many-locals
        """`house_e::update_system()`: HVAC demand, heat output, and load"""
        tout, rhout, _, _, _ = cls.weather(model, m)
        error = msg(model, name).error
        heating_cop_adj = cooling_cop_adj = heating_capacity_adj = cooling_capacity_adj = 0.0
        temp_c = 5*(tout - 32)/9
        if m.heating_cop_curve == HC_DEFAULT:
            x = 80 if tout > 80 else tout
            heating_cop_adj = fdiv(m.heating_COP, 2.03914613 - 0.03906753*x + 0.00045617*x*x - 0.00000203*x*x*x)
        if m.heating_cop_curve == HC_FLAT:
            heating_cop_adj = m.heating_COP
        if m.heating_cop_curve == HC_LINEAR:
            heating_cop_adj = m.heating_COP if tout >= 47 else m.heating_COP*(tout/47)
        if m.heating_cop_curve == HC_CURVED:
            error("CURVED heating_cop_curve is not supported yet.")
            m.error_flag = 1
        if m.cooling_cop_curve == HC_DEFAULT:
            x = 40 if tout < 40 else tout
            cooling_cop_adj = fdiv(m.cooling_COP, -0.01363961 + 0.01066989*x)
        if m.cooling_cop_curve == HC_FLAT:
            cooling_cop_adj = m.cooling_COP
        if m.cooling_cop_curve == HC_LINEAR:
            cooling_cop_adj = m.cooling_COP if temp_c <= 35 else m.cooling_COP*35/temp_c
        if m.cooling_cop_curve == HC_CURVED:
            error("CURVE cooling_cop_curve is not supported yet.")
            m.error_flag = 1
        m.adj_cooling_cop = cooling_cop_adj
        m.adj_heating_cop = heating_cop_adj
        if m.heating_cap_curve == HC_DEFAULT:
            heating_capacity_adj = m.design_heating_capacity*(0.34148808 + 0.00894102*tout + 0.00010787*tout*tout)
        if m.heating_cap_curve == HC_FLAT:
            heating_capacity_adj = m.design_heating_capacity
        if m.heating_cap_curve == HC_LINEAR:
            error("LINEAR heating_cap_curve is not supported at this time")
            m.error_flag = 1
        if m.heating_cap_curve == HC_CURVED:
            error("CURVED heating _cap_curve is not supported at this time")
            m.error_flag = 1
        if m.cooling_cap_curve == HC_DEFAULT:
            cooling_capacity_adj = m.design_cooling_capacity*(1.48924533 - 0.00514995*tout)
        if m.cooling_cap_curve == HC_FLAT:
            cooling_capacity_adj = m.design_cooling_capacity
        if m.cooling_cap_curve == HC_LINEAR:
            error("LINEAR cooling_cap_curve is not supported at this time")
            m.error_flag = 1
        if m.cooling_cap_curve == HC_CURVED:
            error("CURVED cooling_cap_curve is not supported at this time")
            m.error_flag = 1
        m.adj_cooling_cap = cooling_capacity_adj
        m.adj_heating_cap = heating_capacity_adj
        v12 = abs(STATIC_VOLTAGES[0] if m.voltage_source is None else get_complex(model, m.voltage_source, "voltage_12"))
        load = m.load
        voltage_adj = (v12*v12) / (240.0*240.0) * load.impedance_fraction + (v12 / 240.0) * load.current_fraction + load.power_fraction
        voltage_adj_resistive = (v12*v12) / (240.0*240.0)
        if cls.meter_status(model, m) != 0:
            m.Qlatent = 0
            if m.heating_system_type in (HT_NONE, HT_GAS):
                m.heating_demand = 0.0
            elif m.heating_system_type == HT_RESISTANCE:
                m.heating_demand = m.design_heating_capacity*KWPBTUPH
            elif m.heating_system_type == HT_HEAT_PUMP:
                if m.system_mode == SM_AUX:
                    m.heating_demand = m.aux_heat_capacity*KWPBTUPH
                else:
                    m.heating_demand = fdiv(heating_capacity_adj, heating_cop_adj) * KWPBTUPH
            if m.cooling_system_type == CT_NONE:
                m.cooling_demand = 0.0
            elif m.cooling_system_type == CT_ELECTRIC:
                m.cooling_demand = fdiv(cooling_capacity_adj, cooling_cop_adj) * KWPBTUPH if m.thermal_storage_present < 1 else 0.0
            fan_on = m.fan_design_power/1000.0 if m.fan_type != FT_NONE else 0.0
            fan_gain = BTUPHPKW*m.fan_heatgain_fraction
            if m.system_mode == SM_HEAT:
                m.fan_power = fan_on
                m.thermal_storage_inuse = 0
                if m.heating_system_type == HT_NONE:
                    m.system_rated_capacity = 0.0
                    m.system_rated_power = 0.0
                    m.fan_power = 0.0
                elif m.heating_system_type == HT_RESISTANCE:
                    m.system_rated_capacity = m.design_heating_capacity*voltage_adj_resistive + m.fan_power*fan_gain
                    m.system_rated_power = m.heating_demand
                elif m.heating_system_type == HT_HEAT_PUMP:
                    m.system_rated_capacity = heating_capacity_adj*voltage_adj + m.fan_power*fan_gain
                    m.system_rated_power = m.heating_demand
                elif m.heating_system_type == HT_GAS:
                    m.heating_demand = 0.0
                    m.system_rated_capacity = m.design_heating_capacity + m.fan_power*fan_gain
                    m.system_rated_power = m.heating_demand
            elif m.system_mode == SM_AUX:
                m.fan_power = fan_on
                m.thermal_storage_inuse = 0
                if m.auxiliary_system_type == AT_NONE:
                    m.system_rated_capacity = 0.0
                    m.system_rated_power = 0.0
                elif m.auxiliary_system_type == AT_ELECTRIC:
                    m.system_rated_capacity = m.aux_heat_capacity*voltage_adj_resistive + m.fan_power*fan_gain
                    m.system_rated_power = m.heating_demand
            elif m.system_mode == SM_COOL:
                m.fan_power = fan_on
                if m.cooling_system_type == CT_NONE:
                    m.system_rated_capacity = 0.0
                    m.system_rated_power = 0.0
                    m.fan_power = 0.0
                    m.thermal_storage_inuse = 0
                elif m.cooling_system_type == CT_ELECTRIC:
                    if m.thermal_storage_present < 1:
                        if m.use_latent_heat:
                            latent = 1 + 0.1 + m.latent_load_fraction/(1 + exp(4 - 10*rhout))
                            m.system_rated_capacity = -cooling_capacity_adj / latent * voltage_adj + m.fan_power*fan_gain
                            m.Qlatent = -cooling_capacity_adj*voltage_adj*((1/latent) - 1)
                        else:
                            m.system_rated_capacity = -cooling_capacity_adj*voltage_adj + m.fan_power*fan_gain
                            m.Qlatent = 0
                        m.system_rated_power = m.cooling_demand
                        m.thermal_storage_inuse = 0
                    else:
                        m.system_rated_capacity = m.fan_power*fan_gain
                        m.system_rated_power = m.cooling_demand
                        m.thermal_storage_inuse = 1
            else:
                m.fan_power = m.fan_design_power * m.fan_low_power_fraction / 1000.0 if m.fan_type == FT_TWO_SPEED else 0.0
                m.system_rated_capacity = m.fan_power*fan_gain
                m.system_rated_power = 0.0
                m.thermal_storage_inuse = 0
            load.total = complex(m.system_rated_power + m.fan_power if m.include_fan_heatgain else m.system_rated_power, 0)
            load.heatgain = m.system_rated_capacity
            if (m.cooling_system_type == CT_ELECTRIC and m.system_mode == SM_COOL) or (m.heating_system_type == HT_HEAT_PUMP and m.system_mode == SM_HEAT):
                q = sqrt(1/(load.power_factor*load.power_factor) - 1)
                p = load.total.real
                load.power = complex(load.power_fraction*p, load.power_fraction*p*q)
                load.admittance = complex(load.impedance_fraction*p, load.impedance_fraction*p*q)
                load.current = complex(load.current_fraction*p, load.current_fraction*p*q)
                if m.motor_model == MM_BASIC:
                    pf = m.hvac_motor_loss_power_factor
                    if m.system_mode == SM_HEAT:
                        cap, cop = m.design_heating_capacity, m.heating_COP
                    else:
                        cap, cop = m.design_cooling_capacity, m.cooling_COP
                    m.hvac_motor_real_loss = pf*(1 - m.hvac_motor_efficiency) * sqrt(cap*KWPBTUPH*cap*KWPBTUPH / (load.power_factor*load.power_factor*cop*cop))
                    m.hvac_motor_reactive_loss = sqrt(1/(pf*pf) - 1) * m.hvac_motor_real_loss
                    load.admittance += complex(m.hvac_motor_real_loss, m.hvac_motor_reactive_loss)
                elif m.motor_model == MM_FULL:
                    msg(model, name).warning("FULL motor model is not yet supported. No losses are assumed.")
            else:
                q = sqrt(1/(m.fan_power_factor*m.fan_power_factor) - 1)
                fan = m.fan_power
                load.power = complex(fan*m.fan_power_fraction, fan*m.fan_power_fraction*q)
                load.admittance = complex(m.system_rated_power + fan*m.fan_impedance_fraction, fan*m.fan_impedance_fraction*q)
                load.current = complex(fan*m.fan_current_fraction, fan*m.fan_current_fraction*q)
        else:
            load.total = 0j
            load.power = 0j
            load.admittance = 0j
            load.current = 0j
            load.heatgain = 0.0
        vf = load.voltage_factor
        m.hvac_load = load.total.real * (load.power_fraction + vf*(load.current_fraction + load.impedance_fraction*vf))
        if m.system_mode == SM_COOL:
            m.last_cooling_load = m.hvac_load
        elif m.system_mode in (SM_AUX, SM_HEAT):
            m.last_heating_load = m.hvac_load
        m.hvac_power = load.power + load.admittance*vf*vf + load.current*vf
        if m.compressor_on:
            if m.system_mode in (SM_AUX, SM_OFF):
                m.compressor_on = 0
        elif (m.system_mode == SM_HEAT and m.heating_system_type == HT_HEAT_PUMP) or (m.system_mode == SM_COOL and m.cooling_system_type == CT_ELECTRIC):
            m.compressor_on = 1
            m.compressor_count += 1

    @classmethod
    def update_sump(cls, model:Any, m:HouseMembers, dt:float=0) -> None:
        """`house_e::update_sump()`"""
        if m.sump_status == SS_NONE:
            return
        if dt > 0:
            _, humidity, _, rainfall, _ = cls.weather(model, m)
            snowmelt = 0.0
            dstate = humidity*float(g(model, "sump_humidity_factor")) + rainfall*float(g(model, "sump_rainfall_factor"))/24 + snowmelt*float(g(model, "sump_snowmelt_factor"))/24
            m.sump_state += dstate * dt/3600
            if m.sump_status == SS_ON:
                m.sump_state -= dt*m.sump_rate/60
        if m.sump_status == SS_ON:
            if m.sump_state <= 0:
                m.sump_state = 0.0
                m.sump_status = SS_OFF
                m.sump_load = 0.0
        elif m.sump_status == SS_OFF and m.sump_state > 1.0:
            m.sump_status = SS_ON
            m.sump_load = m.sump_power

    #
    # Event handlers
    #
    @classmethod
    def _run(cls, model:Any, name:str, call:Any) -> int:
        from ._common import sync_failed # pylint: disable=import-outside-toplevel
        m = cls.members(model, name)
        m.read()
        cls._views_load(m)
        try:
            result = call(m)
        except Exception as err: # pylint: disable=broad-exception-caught
            sync_failed(model, name, err)
            return TS_INVALID
        cls._views_save(m)
        m.write()
        return result

    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int:
        """`sync_house(PC_PRETOPDOWN)`: `presync(obj->clock, t)`"""
        return cls._run(model, name, lambda m: cls.presync_object(model, name, m, cls.clock(model, name, t), t))

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int:
        """`_object_sync(PC_BOTTOMUP)`: `plc_house()` (the thermostat), then
        `sync_house(PC_BOTTOMUP)`; the earlier result by absolute value"""
        def call(m:HouseMembers) -> int:
            t0 = cls.clock(model, name, t)
            plc_time = cls.sync_thermostat(model, name, m, t0, t)
            sync_time = cls.sync_object(model, name, m, t0, t)
            cls.set_clock(model, name, t)
            return plc_time if abs(plc_time) < abs(sync_time) else sync_time
        return cls._run(model, name, call)

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int:
        """`sync_house(PC_POSTTOPDOWN)`: `postsync()`"""
        def call(m:HouseMembers) -> int:
            result = cls.postsync_object(model, name, m)
            cls.set_clock(model, name, t)
            return result
        return cls._run(model, name, call)

    @classmethod
    def presync_object(cls, model:Any, name:str, m:HouseMembers, t0:int, t1:int) -> int: # pylint: disable=too-many-branches
        """`house_e::presync()`"""
        dt = (t1 - t0)/3600
        m.load_values = [[0j]*3 for _ in range(3)]
        if t0 > 0 and dt > 0 and m.c2 != 0:
            e1 = m.k1*exp(m.r1*dt)
            e2 = m.k2*exp(m.r2*dt)
            m.Tair = e1 + e2 + m.Teq
            ua = 10*m.UA if m.window_open == 1 else m.UA
            m.Tmaterials = m.A3*e1 + m.A4*e2 + m.Qm/m.house_content_heat_transfer_coeff + fdiv(m.Qm + m.Qa, ua) + m.outside_temperature
        if m.window_openings:
            cls.update_window(model, name, m)
        ansi = g(model, "ANSI_voltage_check")
        for circuit in m.circuits:
            cls.update_smartfuse(circuit)
            if circuit.type < 0 or circuit.type > 2:
                from ._common import ResidentialError # pylint: disable=import-outside-toplevel
                raise ResidentialError(f"house:{model.objects[name].id} circuit {circuit.id} has an invalid circuit type ({circuit.type})")
            v = abs(cls.circuit_voltage(model, m, circuit))
            load = circuit.load
            load.voltage_factor = v / (240 if load.config & EUC_IS220 else 120) * circuit.smartfuse["vFactor"]
            if (load.voltage_factor > 1.06 or load.voltage_factor < 0.88) and ansi:
                msg(model, name).warning(f"{label(model, name)} - house:{model.objects[name].id} is outside of ANSI standards (voltage = {load.voltage_factor*100:.0f} percent of nominal 120/240)")
        return TS_NEVER

    @classmethod
    def update_window(cls, model:Any, name:str, m:HouseMembers) -> None:
        """The window opening model of `house_e::presync()`"""
        rng = object_state(model, name).setdefault("rng", object_rng(model, name))
        tout = m.outside_temperature
        if m.window_high_temp <= m.window_low_temp:
            msg(model, name).error("The high window temperature cutoff must be greater than the low window temperature cutoff.")
        if m.window_low_temp <= tout <= m.window_high_temp:
            def draw(what:str) -> bool:
                random_val = _uniform(rng, 0, 1)
                calc_val = m.window_a * tout * tout + m.window_b * tout + m.window_c
                if calc_val > 1.0:
                    msg(model, name).verbose(what.format(calc_val))
                    calc_val = 1.01
                elif calc_val < 0.:
                    msg(model, name).verbose(what.format(calc_val))
                    calc_val = -0.01
                return random_val <= calc_val
            if m.window_first_time_through == 1:
                m.window_first_time_through = 0
                if draw("Function value for window_opening calculation was outside 0..1 ({:.2f}). Capping value."):
                    m.window_open = 1
                    m.last_temperature = tout
                else:
                    m.window_open = 0
            elif abs(m.last_temperature - tout) > m.window_temp_delta:
                m.window_open = 1 if draw("Function value for window_opening calculation was greater than 1 or less than 0 ({:.2f}). Limiting to that range") else 0
                m.last_temperature = tout
        else:
            m.window_open = 0
            m.last_temperature = tout
            m.window_first_time_through = 1

    @classmethod
    def update_smartfuse(cls, circuit:Circuit) -> None:
        """`house_e::update_smartfuse()`"""
        fuse = circuit.smartfuse
        r = fuse["powerRef"]
        if r <= 0:
            return
        load = circuit.load
        z, i, p = abs(load.admittance), abs(load.current), abs(load.power)
        v = 1.0
        if z <= 0.0:
            if i > 0.0:
                v = (r - p)/i
        else:
            v = (sqrt(i*i - 4*(p - r)*z) - i)/(2*z)
        fuse["vFactor"] = fuse["vMin"] if v < fuse["vMin"] else (fuse["vMax"] if v > fuse["vMax"] else v)

    @classmethod
    def sync_object(cls, model:Any, name:str, m:HouseMembers, t0:int, t1:int) -> int: # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        """`house_e::sync()`"""
        dt1 = float(t1 - t0)
        if not m.heat_start or t0 == m.simulation_beginning_time or t1 > t0:
            tout, rhout, _, _, _ = cls.weather(model, m)
            m.outside_temperature = tout
            m.outdoor_rh = rhout*100
        if t0 == m.simulation_beginning_time or t1 > t0:
            cls.update_system(model, name, m)
            cls.update_sump(model, m, dt1)
            if m.error_flag == 1:
                return TS_INVALID
        t2 = TS_NEVER # sync_enduses(): no implicit enduses
        t = cls.sync_panel(model, name, m, t0, t1)
        if t < t2:
            t2 = t
        if (t0 == m.simulation_beginning_time or t1 > t0) or not m.heat_start:
            cls.update_model(model, name, m)
            m.heat_start = True
        cls.update_Tevent(model, m)
        if m.re_override == OV_NORMAL:
            def solve() -> float:
                return e2solve(m.k1, m.r1, m.k2, m.r2, m.Teq - m.Tevent, 0.01/3600, int(g(model, "default_etp_iterations") or 100))*3600.0
            if m.thermostat_off_cycle_time == -1 and m.thermostat_on_cycle_time == -1:
                if t < m.thermostat_last_cycle_time + m.thermostat_cycle_time:
                    dt2 = float(m.thermostat_last_cycle_time + m.thermostat_cycle_time)
                else:
                    dt2 = solve()
            elif m.thermostat_off_cycle_time >= 0 and m.thermostat_on_cycle_time >= 0:
                if m.thermostat_last_off_cycle_time > m.thermostat_last_on_cycle_time:
                    limit = m.thermostat_last_off_cycle_time + m.thermostat_off_cycle_time
                elif m.thermostat_last_off_cycle_time < m.thermostat_last_on_cycle_time:
                    limit = m.thermostat_last_on_cycle_time + m.thermostat_on_cycle_time
                else:
                    limit = m.thermostat_last_cycle_time + m.thermostat_cycle_time
                dt2 = float(limit) if t < limit else solve()
            else:
                msg(model, name).error("Both the thermostat_off_cycle_time and the thermostat_on_cycle_time must be greater than zero.")
                return TS_INVALID
        else:
            dt2 = float(TS_NEVER)
        if math.isnan(dt2) or not math.isfinite(dt2) or dt2 < 0:
            pass
        elif dt2 < 1:
            t = t1 + 1
            if t < t2:
                t2 = t
        else:
            t = t1 + int(math.ceil(dt2))
            if t < t2:
                t2 = t
        if t2 != TS_NEVER:
            dwell = float(g(model, "system_dwell_time"))
            tt = int(math.ceil((-t2 if t2 < 0 else t2)/dwell)*dwell)
            t2 = tt if t2 < 0 else -tt
        return t2

    @classmethod
    def postsync_object(cls, model:Any, name:str, m:HouseMembers) -> int: # pylint: disable=unused-argument
        """`house_e::postsync()`: remove the loads posted to the parent"""
        cls.post(model, m, -1)
        return TS_NEVER

    @classmethod
    def post(cls, model:Any, m:HouseMembers, sign:int) -> None:
        """Add (`sign` 1) or remove (-1) the load accumulators to or from
        the parent meter's `power_X`, `residential_nominal_current_X`, and
        `shunt_X`"""
        if m.voltage_source is None:
            return
        for k, kind in enumerate(("power", "residential_nominal_current", "shunt")):
            for j, suffix in enumerate(("1", "2", "12")):
                value = m.load_values[k][j]
                if value != 0:
                    prop_ = f"{kind}_{suffix}"
                    set_complex(model, m.voltage_source, prop_, get_complex(model, m.voltage_source, prop_) + sign*value)

    @classmethod
    def update_Tevent(cls, model:Any, m:HouseMembers) -> None: # pylint: disable=invalid-name
        """`house_e::update_Tevent()`"""
        if m.system_mode == SM_HEAT:
            if m.dTair > 0:
                m.Tevent = m.TheatOff
            elif m.auxiliary_strategy == AX_DEADBAND:
                m.Tevent = m.TauxOn
        elif m.system_mode == SM_AUX:
            m.Tevent = m.TheatOff
        elif m.system_mode == SM_COOL:
            m.Tevent = m.TcoolOff
        else:
            if m.dTair < 0:
                m.Tevent = m.TheatOn
            elif m.dTair > 0:
                m.Tevent = m.TcoolOn if m.cooling_system_type != CT_NONE else float(g(model, "house_high_temperature_warning"))
            else:
                m.Tevent = m.Tair

    @classmethod
    def sync_thermostat(cls, model:Any, name:str, m:HouseMembers, t0:int, t1:int) -> int: # pylint: disable=too-many-branches,too-many-statements,too-many-boolean-expressions
        """`house_e::sync_thermostat()` (gridlabd's `plc_house()`)"""
        terr = m.dTair/3600
        turned_on = turned_off = False
        if m.thermostat_control == TC_FULL:
            tdead = m.thermostat_deadband/2
            m.TcoolOn = m.cooling_setpoint + tdead
            m.TcoolOff = m.cooling_setpoint - tdead
            m.TheatOn = m.heating_setpoint - tdead
            m.TheatOff = m.heating_setpoint + tdead
            m.TauxOn = m.TheatOn - m.aux_heat_deadband
        if m.thermostat_off_cycle_time == -1 and m.thermostat_on_cycle_time == -1:
            if t1 < m.thermostat_last_cycle_time + m.thermostat_cycle_time:
                return m.thermostat_last_cycle_time + m.thermostat_cycle_time
        elif m.thermostat_off_cycle_time >= 0 and m.thermostat_on_cycle_time >= 0:
            if m.thermostat_last_off_cycle_time > m.thermostat_last_on_cycle_time:
                limit = m.thermostat_last_off_cycle_time + m.thermostat_off_cycle_time
            elif m.thermostat_last_off_cycle_time < m.thermostat_last_on_cycle_time:
                limit = m.thermostat_last_on_cycle_time + m.thermostat_on_cycle_time
            else:
                limit = m.thermostat_last_cycle_time + m.thermostat_cycle_time
            if t1 < limit:
                return limit
        if m.window_openings:
            if m.window_open == 1:
                m.re_override = OV_OFF
                m.dlc_offset = 20
            else:
                m.dlc_offset = 0
        if m.re_override == OV_ON:
            if m.dlc_offset == 0.0:
                m.TcoolOn = m.TcoolOff
                m.TheatOn = m.TheatOff
                m.re_override = OV_NORMAL
            elif m.last_system_mode in (SM_HEAT, SM_AUX):
                m.TcoolOn = m.TcoolOn + m.dlc_offset
                m.TcoolOff = m.TcoolOff + m.dlc_offset
                m.TheatOn = m.TheatOff + m.dlc_offset
                m.TheatOff = m.TheatOff + m.dlc_offset
            elif m.last_system_mode in (SM_OFF, SM_COOL):
                m.TcoolOn = m.TcoolOff - m.dlc_offset
                m.TcoolOff = m.TcoolOff - m.dlc_offset
                m.TheatOn = m.TheatOn - m.dlc_offset
                m.TheatOff = m.TheatOff - m.dlc_offset
        elif m.re_override == OV_OFF:
            if m.dlc_offset == 0.0:
                m.TcoolOff = m.TcoolOn
                m.TheatOff = m.TheatOn
                m.re_override = OV_NORMAL
            else:
                m.TcoolOn = m.TcoolOn + m.dlc_offset
                m.TcoolOff = m.TcoolOn + m.dlc_offset
                m.TheatOn = m.TheatOff - m.dlc_offset
                m.TheatOff = m.TheatOn - m.dlc_offset
        if t0 < m.thermostat_last_cycle_time + m.last_mode_timer:
            m.last_system_mode = SM_OFF
        if m.last_system_mode in (SM_HEAT, SM_AUX):
            if m.TcoolOff < m.TheatOff:
                m.TcoolOff = m.TheatOff
            if m.TcoolOn < m.TcoolOff + m.thermostat_deadband:
                m.TcoolOn = m.TcoolOff + m.thermostat_deadband
        elif m.last_system_mode in (SM_OFF, SM_COOL):
            if m.TcoolOff < m.TheatOff:
                m.TheatOff = m.TcoolOff
            if m.TheatOff < m.TheatOn - m.thermostat_deadband:
                m.TheatOff = m.TheatOn - m.thermostat_deadband
            if m.TauxOn < m.TheatOn - m.aux_heat_deadband:
                m.TauxOn = m.TheatOn - m.aux_heat_deadband
        if m.TcoolOff < m.TheatOff and m.cooling_system_type != CT_NONE:
            msg(model, name).error(f"{name}: thermostat setpoints deadbands overlap (TcoolOff={m.TcoolOff:.1f} < TheatOff={m.TheatOff:.1f})")
            return TS_INVALID
        if m.system_mode == SM_UNKNOWN:
            msg(model, name).warning(f"{name}: system_mode was unknown, changed to off")
            m.system_mode = SM_OFF
        tout = cls.weather(model, m)[0]
        def off() -> None:
            nonlocal turned_off
            m.system_mode = SM_OFF
            m.power_state = PS_OFF
            m.thermostat_last_cycle_time = t1
            m.thermostat_last_off_cycle_time = t1
            turned_off = True
        heat_ok = m.thermostat_mode in (TM_HEAT, TM_AUTO)
        if m.thermostat_control != TC_NONE:
            if m.system_mode == SM_HEAT:
                if heat_ok:
                    if m.re_override == OV_NORMAL:
                        if ((m.auxiliary_system_type != AT_NONE # pylint: disable=too-many-boolean-expressions
                                and ((m.auxiliary_strategy & AX_DEADBAND and m.Tair < m.TauxOn)
                                    or (m.auxiliary_strategy & AX_TIMER and t0 >= m.thermostat_last_cycle_time + m.aux_heat_time_delay)))
                                or (m.auxiliary_strategy & AX_LOCKOUT and tout <= m.aux_heat_temp_lockout)):
                            m.last_system_mode = m.system_mode = SM_AUX
                            m.power_state = PS_ON
                            m.thermostat_last_cycle_time = t1
                        elif m.Tair > m.TheatOff - terr/2:
                            off()
                    elif m.re_override == OV_OFF:
                        off()
                else:
                    off()
            elif m.system_mode == SM_AUX:
                if heat_ok:
                    if (m.Tair > m.TheatOff - terr/2 and m.re_override == OV_NORMAL) or m.re_override == OV_OFF:
                        off()
                else:
                    off()
            elif m.system_mode == SM_COOL:
                if m.thermostat_mode in (TM_COOL, TM_AUTO):
                    if (m.Tair < m.TcoolOff - terr/2 and m.re_override == OV_NORMAL) or m.re_override == OV_OFF:
                        off()
                else:
                    off()
            elif m.system_mode == SM_OFF:
                if m.Tair > m.TcoolOn - terr/2 and m.cooling_system_type != CT_NONE and m.thermostat_mode in (TM_AUTO, TM_COOL):
                    m.last_system_mode = m.system_mode = SM_COOL
                    m.power_state = PS_ON
                    m.thermostat_last_cycle_time = t1
                    m.thermostat_last_on_cycle_time = t1
                    turned_on = True
                elif m.Tair < m.TheatOn - terr/2 and heat_ok:
                    if (m.Tair < m.TauxOn and m.auxiliary_system_type != AT_NONE
                            and (m.auxiliary_strategy & AX_DEADBAND or (m.auxiliary_strategy & AX_LOCKOUT and tout <= m.aux_heat_temp_lockout))):
                        m.last_system_mode = m.system_mode = SM_AUX
                        m.thermostat_last_on_cycle_time = t1
                    else:
                        m.last_system_mode = m.system_mode = SM_HEAT
                        m.thermostat_last_off_cycle_time = t1
                    m.power_state = PS_ON
                    m.thermostat_last_cycle_time = t1
                    turned_on = True
        if turned_on:
            if m.hvac_last_off != 0:
                m.hvac_period_off = (t1 - m.hvac_last_off)/60.0
            m.hvac_last_on = t1
        if turned_off:
            if m.hvac_last_on != 0:
                m.hvac_period_on = (t1 - m.hvac_last_on)/60.0
            m.hvac_last_off = t1
        if m.hvac_period_on != 0.0 and m.hvac_period_off != 0:
            m.hvac_period_length = m.hvac_period_on + m.hvac_period_off
            m.hvac_duty_cycle = m.hvac_period_on / m.hvac_period_length
        m.is_AUX_on = m.is_HEAT_on = m.is_COOL_on = 0
        if m.system_mode == SM_HEAT and m.heating_system_type in (HT_HEAT_PUMP, HT_RESISTANCE, HT_GAS):
            m.is_HEAT_on = 1
        elif m.system_mode == SM_COOL and m.cooling_system_type == CT_ELECTRIC:
            m.is_COOL_on = 1
        elif m.system_mode == SM_AUX and m.auxiliary_system_type == AT_ELECTRIC:
            m.is_AUX_on = 1
        return TS_NEVER

    @classmethod
    def sync_panel(cls, model:Any, name:str, m:HouseMembers, t0:int, t1:int) -> int: # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        """`house_e::sync_panel()`: circuit loads, breakers, and the loads
        posted to the parent meter"""
        t2 = TS_NEVER
        obj = model.objects[name]
        total = m.total
        if (t0 >= m.simulation_beginning_time and t1 > t0) or not m.heat_start:
            total.heatgain = 0
        total.total = total.power = total.current = total.admittance = 0j
        status = cls.meter_status(model, m)
        rng = object_state(model, name).setdefault("rng", object_rng(model, name))
        curtailment_active = bool(g(model, "curtailment_active"))
        for c in m.circuits:
            load = c.load
            if load.gas_fraction == 1.0:
                if (t0 != 0 and t1 > t0) or not m.heat_start:
                    total.heatgain += load.heatgain
                c.status = BRK_CLOSED
                c.reclose = TS_NEVER
                t2 = TS_NEVER
            elif c.status == BRK_OPEN and t1 >= c.reclose:
                c.status = BRK_CLOSED
                c.reclose = TS_NEVER
                t2 = t1
            elif c.status == BRK_CLOSED:
                v = cls.circuit_voltage(model, m, c)
                if abs(v) == 0 or status == 0:
                    if status == 0 and ((t0 >= m.simulation_beginning_time and t1 > t0) or not m.heat_start):
                        total.heatgain += load.heatgain
                    continue
                actual_power = load.power + (load.current + load.admittance * load.voltage_factor) * load.voltage_factor * (1.0 - load.gas_fraction)
                current = cdiv(actual_power*1000, v).conjugate()
                if abs(current) > c.max_amps:
                    opens = False
                    if c.tripsleft > 0:
                        p = 1 // c.tripsleft # integer division of unsigned short
                        c.tripsleft -= 1
                        opens = not rng.random() < p # gl_random_bernoulli() == 0
                    if opens:
                        c.status = BRK_OPEN
                        c.reclose = t1 + int(rng.expovariate(1/300.0))
                    else:
                        c.status = BRK_FAULT
                        c.reclose = TS_NEVER
                        msg(model, name).warning(f"house_e:{obj.id}, {label(model, name)} circuit breaker {c.id} failed - enduse {load.name} is no longer running")
                    t2 = t1
                else:
                    curtailment = load.curtailment_fraction if curtailment_active or m.curtailment_status == CS_CURTAILED else 1.0
                    scale = (1.0 - load.gas_fraction) * curtailment
                    j, volts = {X12: (2, 240.0), X23: (1, 120.0), X13: (0, 120.0)}[c.type]
                    m.load_values[0][j] += load.power * 1000.0 * scale
                    m.load_values[1][j] += (load.current * 1000.0 / volts).conjugate() * scale
                    m.load_values[2][j] += (load.admittance * 1000.0 / (volts * volts)).conjugate() * scale
                    total.total += load.total * curtailment
                    total.power += load.power * curtailment
                    total.current += load.current * curtailment
                    total.admittance += load.admittance * curtailment
                    if (t0 != 0 and t1 > t0) or not m.heat_start:
                        total.heatgain += load.heatgain
                    c.reclose = TS_NEVER
                    c.measurement[0]["t"] = t1
                    c.measurement[0]["power"] = actual_power * curtailment
                    if c.measurement[1]["t"] == 0:
                        c.measurement[0]["energy"] = 0j
                    else:
                        c.measurement[0]["energy"] += actual_power * (t1 - c.measurement[1]["t"])
                    c.measurement[1]["t"] = t1
            if t2 > c.reclose:
                t2 = c.reclose
        m.total_load = abs(total.total)
        if m.sump_status == SS_ON:
            m.load_values[0][0] += m.sump_power
        cls.post(model, m, 1)
        return t2

__all__ = ["House", "e2solve"]
