# pylint: disable=line-too-long
"""Class `solar`: a photovoltaic array

Syntax
------

    object solar {
        parent <inverter>;              // optional; else static voltages
        weather <climate>;              // optional; else the first climate object
        panel_type SINGLE_CRYSTAL_SILICON|MULTI_CRYSTAL_SILICON|AMORPHOUS_SILICON|THIN_FILM_GA_AS|CONCENTRATOR;
        rated_power <real> W;           // or area and efficiency
        area <real> sf;
        efficiency <real>;
        orientation DEFAULT|FIXED_AXIS;
        SOLAR_TILT_MODEL DEFAULT|SOLPOS|PLAYERVALUE;
        SOLAR_POWER_MODEL DEFAULT|FLATPLATE;
        tilt_angle <real> deg;          // default 45 deg
        orientation_azimuth <real> deg; // default 180 deg (south)
        latitude_angle_fix TRUE|FALSE;
        shading_factor <real> pu;
        soiling <real> pu;
        derating <real> pu;
    }

Arguments
---------

See the published properties (`Solar.PROPERTIES`); the main inputs are
listed above.

Description
-----------

Given a `solar` object, the class is expected to satisfy:

1. At init, `generator_mode` `UNKNOWN` becomes `SUPPLY_DRIVEN`, an unset
   `generator_status` becomes `ONLINE`, and an unset `panel_type` becomes
   `SINGLE_CRYSTAL_SILICON`, each with gridlabd's warning; `CONSTANT_V`,
   `CONSTANT_PQ`, and `CONSTANT_PF` fail.
2. The panel type gives the default `efficiency`, `Pmax_temp_coeff`, and
   `Voc_temp_coeff` (per degF). `rated_power` is `Rated_Insolation *
   efficiency * area` when it is 0, and is replaced by that product when
   all three are given and it differs by more than 1%.
3. The parent, if any, is an inverter: the array writes its output voltage
   and current to the inverter's `V_In` and `I_In`.
4. Unless `SOLAR_TILT_MODEL` is `PLAYERVALUE`, the weather comes from the
   `weather` object, else the first `climate` object (written to
   `weather`), else static values (59 degF, 92.902 W/sf direct, diffuse,
   and global, albedo 0.2); `FIXED_AXIS` needs a climate object.
5. Each bottom-up pass, `Insolation` (W/sf) comes from the climate class
   function of the orientation and tilt model: `DEFAULT` orientation
   `calc_solar_ideal_shading_position_radians`; `FIXED_AXIS` with the
   default (Liu-Jordan) model
   `calculate_solar_radiation_shading_position_radians` (azimuth measured
   from the equator), with `SOLPOS`
   `calculate_solpos_radiation_shading_position_radians`. In player mode it
   is the value set in the model. Negative values are 0.
6. The `DEFAULT` power model gives `VA_Out = rated_power * Insolation /
   Rated_Insolation * (1 + Pmax_temp_coeff*(Tmodule-77)) * derating *
   soiling` with `Tmodule = ambient + (NOCT-68)/74.32 * Insolation`
   (degF). The `FLATPLATE` model (NREL SAM flat plate) computes the cell
   temperature from the insolation, the wind speed, and the average of
   the last two ambient temperatures, and `P_Out = VA_Out = Insolation *
   soiling * derating * rated_power/Rated_Insolation * (1 +
   T_coeff*(Tcell-25)/100)`.
7. `Voc = Voc_Max*(1 + Voc_temp_coeff*(Tmodule-77))`, `V_Out =
   V_Max*Voc/Voc_Max`, and `I_Out = VA_Out/V_Out`.

Examples
--------

    >>> from arras import Model, Runner, Class
    >>> Class.reset()
    >>> m = Model()
    >>> m.read_glm('''
    ... clock { starttime "2020-06-01 12:00:00 UTC"; stoptime "2020-06-01 12:00:00 UTC"; }
    ... module generators;
    ... object solar {
    ...     name pv;
    ...     SOLAR_TILT_MODEL PLAYERVALUE;
    ...     panel_type SINGLE_CRYSTAL_SILICON;
    ...     generator_mode SUPPLY_DRIVEN;
    ...     generator_status ONLINE;
    ...     rated_power 1000 W;
    ...     Insolation 92.902 W/sf;
    ...     ambient_temperature 77 degF;
    ... }
    ... ''')
    >>> r = Runner(model=m)
    >>> r.returncode
    0
    >>> round(float(m.get_property("pv", "VA_Out").split("+")[0]), 3)
    895.149
    >>> Class.reset()

Caveats
-------

- The `ONE_AXIS`, `TWO_AXIS`, and `AZIMUTH_AXIS` orientations are not
  published by gridlabd either.
- `power_type` and `INSTALLATION_TYPE` are published but not used, as in
  gridlabd.
- Deltamode is not ported: an array with the `DELTAMODE` flag gets
  gridlabd's warnings and checks, and runs in event mode.
- A parent or weather object of another package counts as initialized; a
  climate object counts as initialized once its `init` handler has run.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None known. gridlabd's quirks are kept: the static-weather insolation
takes the cosine of the tilt angle in degrees as radians; `wind_speed`
(mph) holds the climate's wind speed in m/s, which `FLATPLATE` then
converts from mph; `P_Out` (kW) holds watts; and the object's clock is
updated after each bottom-up pass, so with more than one pass in a time
step `FLATPLATE` uses the current ambient temperature instead of the
average of the last two.

References
----------

- `arras-energy/gridlabd`: `module/generators/solar.cpp`, `solar.h`, and
  the autotests in `module/generators/autotest/`
- [Solar](https://docs.gridlabd.us/index.html?owner=arras-energy&project=gridlabd&doc=/Module/Generators/Solar.md)
"""

import math
from typing import Any

from ._common import (register, MODULE, TS_NEVER, INIT_DEFER, PI, UNKNOWN, ONLINE,
    CONSTANT_V, CONSTANT_PQ, CONSTANT_PF, SUPPLY_DRIVEN, OF_DELTAMODE, Throw,
    keywords, prop, msg, object_state, has_state, object_flags, isa, ref, class_name,
    get_double, get_complex, get_int, set_double, set_complex, set_int, header_double,
    label, object_id)

PANEL_TYPES = keywords(("SINGLE_CRYSTAL_SILICON", 1), ("MULTI_CRYSTAL_SILICON", 2),
    ("AMORPHOUS_SILICON", 3), ("THIN_FILM_GA_AS", 4), ("CONCENTRATOR", 5))
"""`panel_type` keywords"""

SINGLE_CRYSTAL_SILICON, MULTI_CRYSTAL_SILICON, AMORPHOUS_SILICON, THIN_FILM_GA_AS, CONCENTRATOR = 1, 2, 3, 4, 5

LIUJORDAN, SOLPOS, PLAYERVAL = 0, 1, 2
"""`SOLAR_TILT_MODEL` values"""

BASEEFFICIENT, FLATPLATE = 0, 1
"""`SOLAR_POWER_MODEL` values"""

DEFAULT, FIXED_AXIS = 0, 1
"""`orientation` values"""

def rad(x:float) -> float:
    """gridlabd `RAD(x)` in `solar.cpp`"""
    return (x*PI)/180

def _out(description:str|None=None, default:str|None=None) -> dict[str,Any]:
    return prop(description, default)

class Solar:
    """Class `solar`; see the module documentation"""

    NAME = "solar"
    """gridlabd class name"""

    PASSCONFIG = "PRETOPDOWN|BOTTOMUP|POSTTOPDOWN|AUTOLOCK"
    """Pass configuration"""

    EVENTS = ("init", "presync", "sync", "postsync")
    """Event handlers of the class"""

    PROPERTIES: tuple[tuple[str,str,dict[str,Any]],...] = (
        ("generator_mode", "enumeration", prop(keywords=keywords(("UNKNOWN", UNKNOWN), ("CONSTANT_V", CONSTANT_V),
            ("CONSTANT_PQ", CONSTANT_PQ), ("CONSTANT_PF", CONSTANT_PF), ("SUPPLY_DRIVEN", SUPPLY_DRIVEN)))),
        ("generator_status", "enumeration", prop(keywords=keywords(("OFFLINE", 1), ("ONLINE", 2)))),
        ("panel_type", "enumeration", prop(keywords=PANEL_TYPES)),
        ("power_type", "enumeration", prop(keywords=keywords(("AC", 2), ("DC", 1)))),
        ("INSTALLATION_TYPE", "enumeration", prop(keywords=keywords(("ROOF_MOUNTED", 1), ("GROUND_MOUNTED", 2)))),
        ("SOLAR_TILT_MODEL", "enumeration", prop("solar tilt model used to compute insolation values", "DEFAULT",
            keywords=keywords(("DEFAULT", LIUJORDAN), ("SOLPOS", SOLPOS), ("PLAYERVALUE", PLAYERVAL)))),
        ("SOLAR_POWER_MODEL", "enumeration", prop(default="DEFAULT", keywords=keywords(("DEFAULT", BASEEFFICIENT), ("FLATPLATE", FLATPLATE)))),
        ("a_coeff", "double", prop("a coefficient for module temperature correction formula", "-2.81")),
        ("b_coeff[s/m]", "double", prop("b coefficient for module temperature correction formula", "-0.0455 s/m")),
        ("dT_coeff[m^2*degC/kW]", "double", prop("Temperature difference coefficient for module temperature correction formula", "0 m^2*degC/kW")),
        ("T_coeff[%/degC]", "double", prop("Maximum power temperature coefficient for module temperature correction formula", "-0.5 %/degC")),
        ("NOCT[degF]", "double", prop("Nominal operating cell temperature NOCT in deg F", "118.4 degF")),
        ("Tmodule[degF]", "double", prop("Temperature of PV module")),
        ("Tambient[degC]", "double", prop("Ambient temperature for cell efficiency calculations", "25 degC")),
        ("wind_speed[mph]", "double", prop("Wind speed", "0 mph")),
        ("ambient_temperature[degF]", "double", prop("Current ambient temperature of air from climate data", "77 degF")),
        ("Insolation[W/sf]", "double", prop(default="0 W/sf")),
        ("Rinternal[Ohm]", "double", prop(default="0.05 Ohm")),
        ("Rated_Insolation[W/sf]", "double", prop(default="92.902 W/sf")),
        ("Pmax_temp_coeff", "double", prop("temperature coefficient of rated power in %/degC")),
        ("Voc_temp_coeff", "double", prop()),
        ("V_Max[V]", "complex", prop("Vmax of solar module found on specs", "27.1+0i")),
        ("Voc_Max[V]", "complex", prop("Voc max of solar module", "34+0i")),
        ("Voc[V]", "complex", prop(default="34+0i")),
        ("efficiency[unit]", "double", prop()),
        ("area[sf]", "double", prop("solar panel area")),
        ("soiling[pu]", "double", prop("Soiling of array factor - representing dirt on array", "0.95 pu")),
        ("derating[pu]", "double", prop("Panel derating to account for manufacturing variances", "0.95 pu")),
        ("Tcell[degC]", "double", prop(default="69.8 degF")),
        ("rated_power[W]", "double", prop("Used to define the size of the solar panel in power rather than square footage.")),
        ("P_Out[kW]", "complex", prop()),
        ("V_Out[V]", "complex", prop()),
        ("I_Out[A]", "complex", prop()),
        ("VA_Out[VA]", "complex", prop()),
        ("weather", "object", prop()),
        ("shading_factor[pu]", "double", prop("Shading factor for scaling solar power to the array", "1 pu")),
        ("tilt_angle[deg]", "double", prop("Tilt angle of PV array", "45 deg")),
        ("orientation_azimuth[deg]", "double", prop("Facing direction of the PV array", "180 deg")),
        ("latitude_angle_fix", "bool", prop("Fix tilt angle to installation latitude value", "FALSE")),
        ("orientation", "enumeration", prop(default="DEFAULT", keywords=keywords(("DEFAULT", DEFAULT), ("FIXED_AXIS", FIXED_AXIS)))),
    )
    """Published properties as `(name, type, Class.publish() options)`, in
    gridlabd's publication order"""

    @classmethod
    def register(cls, module:Any) -> Any:
        """Register the class for `module` with its properties and event
        handlers"""
        return register(cls, module)

    #
    # Initialization
    #
    @classmethod
    def init(cls, model:Any, name:str, t:int) -> bool|int: # pylint: disable=too-many-branches,too-many-statements,too-many-locals
        """`solar::init()`: `False` fails, 2 defers"""
        out = msg(model, name)
        parent = ref(model, name, "parent")
        if parent is not None and not initialized(model, parent):
            out.verbose(f"solar::init(): deferring initialization on {parent}")
            return INIT_DEFER
        st = object_state(model, name)
        st.update({"prevTemp": 15.0, "currTemp": 15.0, "prevTime": 0, "clock": t})
        mode = get_int(model, name, "generator_mode")
        if mode == UNKNOWN:
            out.warning("Generator control mode is not specified! Using default: SUPPLY_DRIVEN")
            set_int(model, name, "generator_mode", SUPPLY_DRIVEN)
        elif mode in (CONSTANT_V, CONSTANT_PQ, CONSTANT_PF):
            text = {CONSTANT_V: "CONSTANT_V", CONSTANT_PQ: "CONSTANT_PQ", CONSTANT_PF: "CONSTANT_PF"}[mode]
            out.error(f"Generator control mode is {text}. The Solar object only operates in SUPPLY_DRIVEN generator control mode.")
            return False
        if get_int(model, name, "generator_status") == UNKNOWN:
            out.warning("Solar panel status is unknown! Using default: ONLINE")
            set_int(model, name, "generator_status", ONLINE)
        panel = get_int(model, name, "panel_type")
        if panel == UNKNOWN:
            out.warning("Solar panel type is unknown! Using default: SINGLE_CRYSTAL_SILICON")
            panel = SINGLE_CRYSTAL_SILICON
            set_int(model, name, "panel_type", panel)
        efficiency = get_double(model, name, "efficiency")
        pmax_coeff = get_double(model, name, "Pmax_temp_coeff")
        voc_coeff = get_double(model, name, "Voc_temp_coeff")
        defaults = {
            SINGLE_CRYSTAL_SILICON: (0.2, -0.00437/33.8, -0.00393/33.8),
            MULTI_CRYSTAL_SILICON: (0.15, -0.00416/33.8, -0.0039/33.8),
            AMORPHOUS_SILICON: (0.07, 0.1745/33.8, -0.00407/33.8),
            THIN_FILM_GA_AS: (0.3, None, None),
            CONCENTRATOR: (0.15, None, None),
        }.get(panel, (0.10, None, None))
        if efficiency == 0.0:
            efficiency = defaults[0]
        if pmax_coeff == 0.0 and defaults[1] is not None:
            pmax_coeff = defaults[1]
        if voc_coeff == 0.0 and defaults[2] is not None:
            voc_coeff = defaults[2]
        max_p = get_double(model, name, "rated_power")
        rated = get_double(model, name, "Rated_Insolation")
        area = get_double(model, name, "area")
        if max_p == 0:
            max_p = rated * efficiency * area
            out.verbose("init(): Rated_kVA was not specified.  Calculating from other defaults.")
            if max_p == 0:
                out.warning("init(): Rated_kVA or {area or rated insolation or effiency} were not specified or specified as zero.  Leads to maximum power output of 0.")
        elif efficiency != 0 and area != 0 and rated != 0:
            temp = rated * efficiency * area
            if temp < max_p * .99 or temp > max_p * 1.01:
                max_p = temp
                out.warning("init(): Rated_kVA, efficiency, Rate_Insolation, and area did not calculated to the same value.  Ignoring Rated_kVA.")
        if rated == 0:
            if area != 0 and efficiency != 0:
                rated = max_p / area / efficiency
            else:
                out.error("init(): Rated Insolation was not specified (or zero).  Power outputs cannot be calculated without a rated insolation value.")
        set_double(model, name, "efficiency", efficiency)
        set_double(model, name, "Pmax_temp_coeff", pmax_coeff)
        set_double(model, name, "Voc_temp_coeff", voc_coeff)
        set_double(model, name, "rated_power", max_p)
        set_double(model, name, "Rated_Insolation", rated)
        if parent is not None and class_name(model, parent) == "inverter":
            st["inverter"] = parent
            par = object_state(model, parent)
            phases = par.get("number_of_phases_out", 0)
            p_rated = get_double(model, parent, "rated_power")
            if get_int(model, parent, "use_multipoint_efficiency"):
                if max_p > get_double(model, parent, "maximum_dc_power"):
                    out.warning("The PV is over rated for its parent inverter.")
            elif get_int(model, parent, "inverter_type") == 4:
                eta = get_double(model, parent, "inverter_efficiency")
                limit = p_rated/eta if phases == 4 else phases*p_rated/eta
                if max_p > limit:
                    out.warning("The PV is over rated for its parent inverter.")
            else:
                eff = par.get("efficiency", 0.0)
                limit = (p_rated/eff if phases == 4 else phases*p_rated/eff) if eff != 0 else math.copysign(math.inf, p_rated) if p_rated else math.nan
                if max_p > limit:
                    out.warning("The PV is over rated for its parent inverter.")
        elif parent is not None:
            raise Throw("Solar panel can only have an inverter as its parent.")
        else:
            out.warning(f"solar panel:{object_id(model, name)} has no parent defined. Using static voltages.")
            st["inverter"] = None
            st["V_In"] = complex(get_complex(model, name, "V_Max").real/math.sqrt(3.0), 0)
            st["I_In"] = 0j
        result = cls._init_climate(model, name, st)
        if result != 1:
            return result
        soiling = get_double(model, name, "soiling")
        if soiling < 0 or soiling > 1.0:
            set_double(model, name, "soiling", 0.95)
            out.warning("Invalid soiling factor specified, defaulting to 95%")
        derating = get_double(model, name, "derating")
        if derating < 0 or derating > 1.0:
            set_double(model, name, "derating", 0.95)
            out.warning("Invalid derating factor specified, defaulting to 95%")
        enabled = model.globals.isdefined(f"{MODULE}::enable_subsecond_models") and \
            str(model.globals.get(f"{MODULE}::enable_subsecond_models")).upper() in ("TRUE", "1")
        if object_flags(model, name) & OF_DELTAMODE:
            if not enabled:
                out.warning(f"solar:{label(model, name)} indicates it wants to run deltamode, but the module-level flag is not set!")
            if isa(model, parent, "inverter", MODULE):
                if not object_flags(model, parent) & OF_DELTAMODE: # type: ignore[arg-type]
                    raise Throw(f"solar:{object_id(model, name)} {label(model, name, 'Unnamed')} is attached to an inverter, but that inverter is not set up for deltamode")
            else:
                raise Throw(f"solar:{object_id(model, name)} {label(model, name, 'Unnamed')} is not parented to an inverter -- deltamode operations do not support this")
        elif enabled:
            out.warning(f"solar:{object_id(model, name)} {label(model, name, 'Unnamed')} - Deltamode is enabled for the module, but not this solar array!")
        return True

    @classmethod
    def _init_climate(cls, model:Any, name:str, st:dict[str,Any]) -> int: # pylint: disable=too-many-branches,too-many-statements
        """`solar::init_climate()`: 1 succeeds, 0 fails, 2 defers"""
        out = msg(model, name)
        st["climate"] = None
        st["function"] = None
        if get_int(model, name, "SOLAR_TILT_MODEL") == PLAYERVAL:
            out.warning(f"Solar object:{label(model, name, '(null)')} is in player mode - be sure to specify relevant values")
            return 1
        weather = ref(model, name, "weather")
        if weather is not None:
            if not isa(model, weather, "climate"):
                out.error(f"weather property refers to a(n) \"{class_name(model, weather)}\" object and not a climate object")
                return 0
        else:
            climates = [x for x in model.objects if class_name(model, x) == "climate"]
            if climates:
                if len(climates) > 1:
                    out.warning(f"solarpanel: {len(climates)} climates found, using first one defined")
                out.verbose("solar init: climate data was found!")
                weather = climates[0]
                model.objects[name]["weather"] = weather
        orientation = get_int(model, name, "orientation")
        if weather is None:
            out.warning("solarpanel: no climate data found, using static data")
            if orientation == FIXED_AXIS:
                raise Throw("FIXED_AXIS requires a climate file!")
            return 1
        if not initialized(model, weather):
            out.verbose(f"solar::init(): deferring initialization on {weather}")
            return INIT_DEFER
        st["climate"] = weather
        if get_int(model, name, "latitude_angle_fix"):
            latitude = header_double(model, weather, "latitude")
            set_double(model, name, "tilt_angle", -latitude if latitude < 0 else latitude)
        tilt = get_double(model, name, "tilt_angle")
        if tilt < 0:
            raise Throw("Invalid tilt_angle - tilt must be between 0 and 90 degrees")
        if tilt > 90.0:
            raise Throw("Invalid tilt angle - values above 90 degrees are unsupported!")
        model_tilt = get_int(model, name, "SOLAR_TILT_MODEL")
        oclass = model.objects[weather].oclass
        if orientation == DEFAULT:
            st["function"] = oclass.get_function("calc_solar_ideal_shading_position_radians")
        elif orientation == FIXED_AXIS:
            fname = "calculate_solar_radiation_shading_position_radians" if model_tilt == LIUJORDAN else \
                "calculate_solpos_radiation_shading_position_radians" if model_tilt == SOLPOS else None
            st["function"] = oclass.get_function(fname) if fname else None
            if st["function"] is None:
                raise Throw(f"Unable to map solar radiation function on {label(model, weather, '(null)')} in {label(model, name, '(null)')}")
            azimuth = get_double(model, name, "orientation_azimuth")
            if azimuth < 0.0 or azimuth > 360.0:
                raise Throw("orientation_azimuth must be a value representing a valid cardinal direction of 0 to 360 degrees!")
            if model_tilt == LIUJORDAN:
                latitude = header_double(model, weather, "latitude")
                if latitude > 0.0:
                    corrected = 180.0 - azimuth
                elif latitude < 0.0:
                    out.warning(f"solar:{label(model, name, '(null)')} - Default solar position model is not recommended for southern hemisphere!")
                    if 0.0 <= azimuth <= 180.0:
                        corrected = azimuth
                    elif azimuth == 360.0:
                        corrected = 0.0
                    else:
                        corrected = azimuth - 360.0
                else:
                    raise Throw("Exact equator location of array detected - unknown how to handle orientation")
            else:
                corrected = azimuth
            st["azimuth"] = corrected
        return 1

    #
    # Synchronization
    #
    @classmethod
    def presync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`solar::presync()`"""
        set_complex(model, name, "I_Out", 0j)
        return TS_NEVER

    @classmethod
    def sync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=too-many-locals,too-many-branches,too-many-statements
        """`solar::sync()`: the array output at the current weather"""
        st = object_state(model, name)
        t0 = st.get("clock", t)
        shading = get_double(model, name, "shading_factor")
        if shading < 0 or shading > 1:
            raise Throw(f"Shading factor outside [0 1] limits in {label(model, name, '(null)')}")
        insolation = get_double(model, name, "Insolation")
        tamb = get_double(model, name, "ambient_temperature")
        wind_speed = get_double(model, name, "wind_speed")
        tilt = get_double(model, name, "tilt_angle")
        if get_int(model, name, "SOLAR_TILT_MODEL") != PLAYERVAL:
            weather = st.get("climate")
            if weather is None:
                tout, solar, wsout, albedo = 59.0, 92.902, 0.0, 0.2
                solar_d = solar_h = solar_g = solar
            else:
                tout = get_double(model, weather, "temperature")
                solar_d = get_double(model, weather, "solar_direct")
                solar_h = get_double(model, weather, "solar_diffuse")
                solar_g = get_double(model, weather, "solar_global")
                albedo = get_double(model, weather, "ground_reflectivity")
                wsout = get_double(model, weather, "wind_speed")
            wind_speed = wsout
            tamb = tout
            orientation = get_int(model, name, "orientation")
            latitude = header_double(model, name, "latitude")
            longitude = header_double(model, name, "longitude")
            if orientation == DEFAULT:
                if weather is None:
                    insolation = shading*solar_d + solar_h + solar_g*(1 - math.cos(tilt))*albedo/2.0
                else:
                    value = st["function"](model, weather, rad(tilt), latitude, longitude, shading)
                    if value is not None:
                        insolation = value
            elif orientation == FIXED_AXIS:
                value = st["function"](model, weather, rad(tilt), rad(st["azimuth"]), latitude, longitude, shading)
                if value is None:
                    raise Throw(f"Calculation of solar radiation failed in {label(model, name, '(null)')}")
                insolation = value
            else:
                raise Throw("Unknown or unsupported orientation detected")
            set_double(model, name, "wind_speed", wind_speed)
            set_double(model, name, "ambient_temperature", tamb)
        if insolation < 0.0: # pylint: disable=consider-using-max-builtin
            insolation = 0.0
        set_double(model, name, "Insolation", insolation)
        max_p = get_double(model, name, "rated_power")
        rated = get_double(model, name, "Rated_Insolation")
        soiling = get_double(model, name, "soiling")
        derating = get_double(model, name, "derating")
        power_model = get_int(model, name, "SOLAR_POWER_MODEL")
        if power_model == BASEEFFICIENT:
            set_double(model, name, "Tambient", (tamb-32.0)*5.0/9.0)
            tmodule = tamb + (get_double(model, name, "NOCT")-68)/74.32 * insolation
            va_out = complex(_div(max_p * insolation, rated) * (1+get_double(model, name, "Pmax_temp_coeff")*(tmodule-77))*derating*soiling, 0)
        elif power_model == FLATPLATE:
            if st["prevTime"] != t0:
                st["prevTemp"] = st["currTemp"]
                st["currTemp"] = (tamb-32.0)*5.0/9.0
                st["prevTime"] = t0
            tambient = st["prevTemp"] + (st["currTemp"]-st["prevTemp"])/2.0
            set_double(model, name, "Tambient", tambient)
            insolwmsq = insolation*10.7639104*soiling
            corrwindspeed = wind_speed*0.44704
            tback = insolwmsq*math.exp(get_double(model, name, "a_coeff") + get_double(model, name, "b_coeff")*corrwindspeed) + tambient
            tcell = tback + insolwmsq/1000.0*get_double(model, name, "dT_coeff")
            set_double(model, name, "Tcell", tcell)
            tmodule = tcell*9.0/5.0 + 32.0
            ftempcorr = 1.0 + get_double(model, name, "T_coeff")*(tcell-25.0)/100.0
            p_out = insolation*soiling*derating*_div(max_p, rated)*ftempcorr
            set_complex(model, name, "P_Out", complex(p_out, 0))
            va_out = complex(p_out, 0)
        else:
            raise Throw("Unknown solar power output model selected!")
        set_double(model, name, "Tmodule", tmodule)
        set_complex(model, name, "VA_Out", va_out)
        voc_max = get_complex(model, name, "Voc_Max")
        voc = voc_max * (1+get_double(model, name, "Voc_temp_coeff")*(tmodule-77))
        v_out = get_complex(model, name, "V_Max") * _cdiv(voc, voc_max)
        i_out = _cdiv(va_out, v_out)
        set_complex(model, name, "Voc", voc)
        set_complex(model, name, "V_Out", v_out)
        set_complex(model, name, "I_Out", i_out)
        inverter = st.get("inverter")
        if inverter is not None:
            set_complex(model, inverter, "I_In", i_out)
            set_complex(model, inverter, "V_In", v_out)
        else:
            st["I_In"] = i_out
            st["V_In"] = v_out
        st["clock"] = t
        return TS_NEVER

    @classmethod
    def postsync(cls, model:Any, name:str, t:int) -> int: # pylint: disable=unused-argument
        """`solar::postsync()`"""
        return TS_NEVER

def _div(a:float, b:float) -> float:
    if b == 0:
        return math.nan if a == 0 or math.isnan(a) else math.copysign(math.inf, a)
    return a / b

def _cdiv(a:complex, b:complex) -> complex:
    if b == 0:
        return complex(math.nan, math.nan)
    return a / b

def initialized(model:Any, name:str) -> bool:
    """`(obj->flags & OF_INIT) == OF_INIT` for a parent or weather object:
    generators objects once their `init` succeeded, climate objects once
    their `init` handler has run, other objects always"""
    oclass = model.objects[name].oclass
    if oclass.module == MODULE:
        return has_state(model, name) and object_state(model, name).get("initialized", False)
    if oclass.module == "climate" and oclass.name == "climate":
        from climate._common import get_state # pylint: disable=import-outside-toplevel
        return get_state(model, name) is not None
    return True
