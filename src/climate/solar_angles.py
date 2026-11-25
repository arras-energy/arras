# pylint: disable=line-too-long,invalid-name
"""Solar position (gridlabd `SolarAngles`)

The `SolarAngles` functions compute the position of the sun and the
cosine of the angle at which its beam strikes a surface, as gridlabd's
`module/climate/solar_angles.cpp` does: the Duffie and Beckman formulas
that the `climate` class uses for its solar flux, and NREL's SOLPOS 2.0
with the Perez diffuse tilt model, which the published function
`calculate_solpos_radiation_shading_position_radians` uses.

Syntax
------

    from climate.solar_angles import SolarAngles, SolposData
    SolarAngles.day_of_yr(month, day)
    SolarAngles.solar_time(std_time, day_of_yr, std_meridian, longitude)
    SolarAngles.cos_incident(latitude, slope, az, sol_time, day_of_yr)
    pdat = SolposData(); SolarAngles.S_solpos(pdat)

Description
-----------

The functions are expected to satisfy:

1. Angles are in radians, except where SOLPOS uses degrees (its
   `longitude`, `azim`, `zenref`, ...); times are decimal hours.
2. `day_of_yr()` ignores leap years (February 29 and March 1 are the same
   day), as gridlabd's does.
3. `cos_incident()` returns 0 when the sun is behind the surface.
4. `S_init()` sets the SOLPOS inputs to the values of gridlabd's
   `S_init()` (its `aspect` is in radians and its solar constant is
   126.998456 W/sf), and `S_solpos()` runs the SOLPOS steps in gridlabd's
   order, ending with `perez_tilt()`.

Examples
--------

    >>> from climate.solar_angles import SolarAngles
    >>> SolarAngles.day_of_yr(3, 1)
    60
    >>> round(SolarAngles.declination(172), 6)
    0.409276
    >>> round(SolarAngles.cos_incident(0.8, 0.0, 0.0, 12.0, 172), 6)
    0.924634

Caveats
-------

- `azimuth()` is gridlabd's, whose source notes that it does not compute
  the azimuth correctly; the `climate` class publishes its result as
  `solar_azimuth`.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

None.

References
----------

- `arras-energy/gridlabd`: `module/climate/solar_angles.cpp`,
  `solar_angles.h`
- Duffie, J. A. and Beckman, W. A., *Solar Engineering of Thermal
  Processes*
- NREL SOLPOS 2.0, https://www.nrel.gov/grid/solar-resource/solpos.html
- Perez, R. et al., "Modeling daylight availability and irradiance
  components from direct and global irradiance," *Solar Energy* 44(5),
  pp. 271-289, 1990
"""

import math
from dataclasses import dataclass

from ._common import PI

HR_PER_RADIAN = 12.0 / PI
"""Hours per radian of hour angle"""

PI_OVER_180 = PI / 180
"""Radians per degree"""

raddeg = PI / 180
"""Radians per degree (SOLPOS)"""

degrad = 180 / PI
"""Degrees per radian (SOLPOS)"""

COS85DEG = 0.08715574274765817355806427083747
"""Cosine of 85 degrees"""

DAYS_THRU_MONTH = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
"""Days before each month of a non-leap year"""

MONTH_DAYS = ((0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334),
    (0, 0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335))
"""Days before each month (SOLPOS), non-leap and leap years"""

PEREZ_TILT_COEFF_F1 = ((-0.008, 0.130, 0.330, 0.568, 0.873, 1.132, 1.060, 0.678),
    (0.588, 0.683, 0.487, 0.187, -0.392, -1.237, -1.600, -0.327),
    (-0.062, -0.151, -0.221, -0.295, -0.362, -0.412, -0.359, -0.250))
"""Perez model F1 coefficients (Perez et al., 1990)"""

PEREZ_TILT_COEFF_F2 = ((-0.060, -0.019, 0.055, 0.109, 0.226, 0.288, 0.264, 0.156),
    (0.072, 0.066, -0.064, -0.152, -0.462, -0.823, -1.127, -1.377),
    (-0.022, -0.029, -0.026, -0.014, 0.001, 0.056, 0.131, 0.251))
"""Perez model F2 coefficients (Perez et al., 1990)"""

PEREZ_CLEARNESS_LIMITS = (1.0, 1.065, 1.230, 1.500, 1.950, 2.800, 4.500, 6.200)
"""Bounds of the Perez model sky clearness categories"""

@dataclass
class SolposData: # pylint: disable=too-many-instance-attributes
    """SOLPOS inputs, outputs, and transitional values (gridlabd
    `SOLPOS_POSDATA`); see the SOLPOS documentation for each field"""
    day: int = 0
    daynum: int = 0
    function: int = 0
    hour: int = 0
    interval: int = 0
    minute: int = 0
    month: int = 0
    second: int = 0
    year: int = 0
    amass: float = 0.0
    ampress: float = 0.0
    aspect: float = 0.0
    azim: float = 0.0
    cosinc: float = 0.0
    coszen: float = 0.0
    dayang: float = 0.0
    declin: float = 0.0
    eclong: float = 0.0
    ecobli: float = 0.0
    ectime: float = 0.0
    elevetr: float = 0.0
    elevref: float = 0.0
    eqntim: float = 0.0
    erv: float = 0.0
    etr: float = 0.0
    etrn: float = 0.0
    etrtilt: float = 0.0
    gmst: float = 0.0
    hrang: float = 0.0
    julday: float = 0.0
    latitude: float = 0.0
    longitude: float = 0.0
    lmst: float = 0.0
    mnanom: float = 0.0
    mnlong: float = 0.0
    rascen: float = 0.0
    press: float = 0.0
    prime: float = 0.0
    sbcf: float = 0.0
    sbwid: float = 0.0
    sbrad: float = 0.0
    sbsky: float = 0.0
    solcon: float = 0.0
    ssha: float = 0.0
    sretr: float = 0.0
    ssetr: float = 0.0
    temp: float = 0.0
    tilt: float = 0.0
    timezone: float = 0.0
    tst: float = 0.0
    tstfix: float = 0.0
    unprime: float = 0.0
    utime: float = 0.0
    zenetr: float = 0.0
    zenref: float = 0.0
    diff_horz: float = 0.0
    dir_norm: float = 0.0
    extra_irrad: float = 0.0
    perez_horz: float = 0.0
    perez_skyclear_idx: int = 0
    perez_skyclear: float = 0.0
    perez_brightness: float = 0.0
    perez_F1: float = 0.0
    perez_F2: float = 0.0

@dataclass
class _Trig:
    cd: float = 1.0
    ch: float = 1.0
    cl: float = 1.0
    sd: float = -999.0
    sl: float = 1.0

def _cint(value:float) -> int:
    """C conversion of a double to `int` (toward zero)"""
    return int(value)

class SolarAngles: # pylint: disable=too-many-public-methods
    """Solar position functions; see the module documentation"""

    @staticmethod
    def eq_time(day_of_yr:int) -> float:
        """Equation of time (hours)"""
        r = (2.0 * PI * day_of_yr) / 365.0
        return (0.5501*math.cos(r) - 3.0195*math.cos(2*r) - 0.0771*math.cos(3*r)
            -7.3403*math.sin(r) - 9.4583*math.sin(2*r) - 0.3284*math.sin(3*r)) / 60.0

    @staticmethod
    def solar_time(std_time:float, day_of_yr:int, std_meridian:float, longitude:float) -> float:
        """Apparent solar time (decimal hours) from local standard time"""
        return std_time + SolarAngles.eq_time(day_of_yr) + HR_PER_RADIAN * (longitude-std_meridian)

    @staticmethod
    def local_time(sol_time:float, day_of_yr:int, std_meridian:float, longitude:float) -> float:
        """Local standard time (decimal hours) from apparent solar time"""
        return sol_time - SolarAngles.eq_time(day_of_yr) - HR_PER_RADIAN * (longitude-std_meridian)

    @staticmethod
    def declination(day_of_yr:int) -> float:
        """Solar declination (radians)"""
        return 0.409280*math.sin(2.0*PI*(284+day_of_yr)/365)

    @staticmethod
    def cos_incident(latitude:float, slope:float, az:float, sol_time:float, day_of_yr:int) -> float: # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Cosine of the angle of incidence of the beam on a surface of
        `slope` and azimuth `az` (from south, east positive); 0 when the
        sun is behind the surface"""
        hr_ang = -(15.0 * PI_OVER_180)*(sol_time-12.0)
        decl = SolarAngles.declination(day_of_yr)
        sindecl, cosdecl = math.sin(decl), math.cos(decl)
        sinlat, coslat = math.sin(latitude), math.cos(latitude)
        sinslope, cosslope = math.sin(slope), math.cos(slope)
        sinaz, cosaz = math.sin(az), math.cos(az)
        sinhr, coshr = math.sin(hr_ang), math.cos(hr_ang)
        answer = (sindecl*sinlat*cosslope
            -sindecl*coslat*sinslope*cosaz
            +cosdecl*coslat*cosslope*coshr
            +cosdecl*sinlat*sinslope*cosaz*coshr
            +cosdecl*sinslope*sinaz*sinhr)
        return 0.0 if answer < 0.0 else answer

    @staticmethod
    def incident(latitude:float, slope:float, az:float, sol_time:float, day_of_yr:int) -> float: # pylint: disable=too-many-arguments,too-many-positional-arguments
        """Angle of incidence (radians)"""
        return math.acos(SolarAngles.cos_incident(latitude, slope, az, sol_time, day_of_yr))

    @staticmethod
    def zenith(day_of_yr:int, latitude:float, sol_time:float) -> float:
        """Solar zenith angle (radians)"""
        hr_ang = -(15.0 * PI_OVER_180)*(sol_time-12.0)
        decl = SolarAngles.declination(day_of_yr)
        return math.acos(math.sin(decl)*math.sin(latitude) + math.cos(decl)*math.cos(latitude)*math.cos(hr_ang))

    @staticmethod
    def altitude(day_of_yr:int, latitude:float, sol_time:float) -> float:
        """Solar altitude angle (radians)"""
        return (90.0 * PI_OVER_180) - SolarAngles.zenith(day_of_yr, latitude, sol_time)

    @staticmethod
    def hr_sunrise(day_of_yr:int, latitude:float) -> float:
        """Solar hour of sunrise"""
        hr_ang = math.acos(-math.tan(latitude)*math.tan(SolarAngles.declination(day_of_yr))) / PI_OVER_180
        return (-hr_ang/15.0) + 12.0

    @staticmethod
    def day_len(day_of_yr:int, latitude:float) -> float:
        """Day length (hours)"""
        return 2.0 * math.acos(-math.tan(latitude)*math.tan(SolarAngles.declination(day_of_yr))) / (15.0 * PI_OVER_180)

    @staticmethod
    def day_of_yr(month:int, day:int) -> int:
        """Day of the year from 1, ignoring leap years"""
        return DAYS_THRU_MONTH[month-1] + day

    @staticmethod
    def elevation(day_of_yr:int, latitude:float, sol_time:float) -> float:
        """Solar elevation angle (radians)"""
        hr_ang = -(15.0 * PI_OVER_180)*(sol_time-12.0)
        decl = SolarAngles.declination(day_of_yr)
        return math.asin(math.sin(decl)*math.sin(latitude) + math.cos(decl)*math.cos(latitude)*math.cos(hr_ang))

    @staticmethod
    def azimuth(day_of_yr:int, latitude:float, sol_time:float) -> float:
        """gridlabd's solar azimuth (radians; see Caveats)"""
        hr_ang = -(15.0 * PI_OVER_180)*(sol_time-12.0)
        decl = SolarAngles.declination(day_of_yr)
        alpha = (90.0 * PI_OVER_180) - latitude + decl
        rs = (math.sin(decl)*math.cos(latitude) - math.cos(decl)*math.sin(latitude)*math.cos(hr_ang))/math.cos(alpha)
        rs = min(max(rs, -1.0), 1.0)
        return math.acos(rs)

    #
    # SOLPOS 2.0 and the Perez tilt model
    #
    @staticmethod
    def S_init(pdat:SolposData) -> None:
        """Set the SOLPOS inputs to gridlabd's initial values"""
        pdat.day = -99
        pdat.daynum = -999
        pdat.hour = -99
        pdat.minute = -99
        pdat.month = -99
        pdat.second = -99
        pdat.year = -99
        pdat.interval = 0
        pdat.aspect = PI
        pdat.latitude = -99.0
        pdat.longitude = -999.0
        pdat.press = 1013.0
        pdat.solcon = 126.998456
        pdat.temp = 15.0
        pdat.tilt = 0.0
        pdat.timezone = -99.0
        pdat.sbwid = 7.6
        pdat.sbrad = 31.7
        pdat.sbsky = 0.04
        pdat.perez_horz = 1.0

    @staticmethod
    def S_solpos(pdat:SolposData) -> int:
        """Run the SOLPOS steps and the Perez tilt model; returns 0"""
        tdat = _Trig()
        SolarAngles.doy2dom(pdat)
        SolarAngles.geometry(pdat)
        SolarAngles.zen_no_ref(pdat, tdat)
        SolarAngles.ssha(pdat, tdat)
        SolarAngles.sbcf(pdat, tdat)
        SolarAngles.tst(pdat)
        SolarAngles.srss(pdat)
        SolarAngles.sazm(pdat, tdat)
        SolarAngles.refrac(pdat)
        SolarAngles.amass(pdat)
        SolarAngles.prime(pdat)
        SolarAngles.etr(pdat)
        SolarAngles.tilt(pdat)
        SolarAngles.perez_tilt(pdat)
        return 0

    @staticmethod
    def doy2dom(pdat:SolposData) -> None:
        """Month and day of the month from the day number"""
        leap = 1 if (pdat.year % 4 == 0 and (pdat.year % 100 != 0 or pdat.year % 400 == 0)) else 0
        imon = 12
        while pdat.daynum <= MONTH_DAYS[leap][imon]:
            imon -= 1
        pdat.month = imon
        pdat.day = pdat.daynum - MONTH_DAYS[leap][imon]

    @staticmethod
    def geometry(pdat:SolposData) -> None:
        """Basic geometry for the time and place"""
        pdat.dayang = 2.0 * PI * (pdat.daynum - 1) / 365.0
        sd = math.sin(pdat.dayang)
        cd = math.cos(pdat.dayang)
        d2 = 2.0 * pdat.dayang
        c2 = math.cos(d2)
        s2 = math.sin(d2)
        pdat.erv = 1.000110 + 0.034221 * cd + 0.001280 * sd
        pdat.erv += 0.000719 * c2 + 0.000077 * s2
        pdat.utime = pdat.hour * 3600.0 + pdat.minute * 60.0 + pdat.second - float(pdat.interval) / 2.0
        pdat.utime = pdat.utime / 3600.0 - pdat.timezone
        delta = pdat.year - 1949
        leap = _cint(delta / 4.0)
        pdat.julday = 32916.5 + delta * 365.0 + leap + pdat.daynum + pdat.utime / 24.0
        pdat.ectime = pdat.julday - 51545.0
        pdat.mnlong = 280.460 + 0.9856474 * pdat.ectime
        pdat.mnlong -= 360.0 * _cint(pdat.mnlong / 360.0)
        if pdat.mnlong < 0.0:
            pdat.mnlong += 360.0
        pdat.mnanom = 357.528 + 0.9856003 * pdat.ectime
        pdat.mnanom -= 360.0 * _cint(pdat.mnanom / 360.0)
        if pdat.mnanom < 0.0:
            pdat.mnanom += 360.0
        pdat.eclong = pdat.mnlong + 1.915 * math.sin(pdat.mnanom * raddeg) + 0.020 * math.sin(2.0 * pdat.mnanom * raddeg)
        pdat.eclong -= 360.0 * _cint(pdat.eclong / 360.0)
        if pdat.eclong < 0.0:
            pdat.eclong += 360.0
        pdat.ecobli = 23.439 - 4.0e-07 * pdat.ectime
        pdat.declin = math.asin(math.sin(pdat.ecobli*raddeg)*math.sin(pdat.eclong*raddeg))
        top = math.cos(raddeg * pdat.ecobli) * math.sin(raddeg * pdat.eclong)
        bottom = math.cos(raddeg * pdat.eclong)
        pdat.rascen = degrad * math.atan2(top, bottom)
        if pdat.rascen < 0.0:
            pdat.rascen += 360.0
        pdat.gmst = 6.697375 + 0.0657098242 * pdat.ectime + pdat.utime
        pdat.gmst -= 24.0 * _cint(pdat.gmst / 24.0)
        if pdat.gmst < 0.0:
            pdat.gmst += 24.0
        pdat.lmst = pdat.gmst * 15.0 + pdat.longitude
        pdat.lmst -= 360.0 * _cint(pdat.lmst / 360.0)
        if pdat.lmst < 0.:
            pdat.lmst += 360.0
        pdat.hrang = pdat.lmst - pdat.rascen
        if pdat.hrang < -180.0:
            pdat.hrang += 360.0
        elif pdat.hrang > 180.0:
            pdat.hrang -= 360.0

    @staticmethod
    def zen_no_ref(pdat:SolposData, tdat:_Trig) -> None:
        """Zenith angle without refraction"""
        tdat.cd = math.cos(pdat.declin)
        tdat.ch = math.cos(raddeg*pdat.hrang)
        tdat.cl = math.cos(pdat.latitude)
        tdat.sd = math.sin(pdat.declin)
        tdat.sl = math.sin(pdat.latitude)
        cz = tdat.sd * tdat.sl + tdat.cd * tdat.cl * tdat.ch
        if abs(cz) > 1.0:
            cz = 1.0 if cz >= 0.0 else -1.0
        pdat.zenetr = math.acos(cz) * degrad
        pdat.zenetr = min(pdat.zenetr, 99.0)
        pdat.elevetr = 90.0 - pdat.zenetr

    @staticmethod
    def ssha(pdat:SolposData, tdat:_Trig) -> None:
        """Sunset hour angle (degrees)"""
        cdcl = tdat.cd * tdat.cl
        if abs(cdcl) >= 0.001:
            cssha = -tdat.sl * tdat.sd / cdcl
            if cssha < -1.0:
                pdat.ssha = 180.0
            elif cssha > 1.0:
                pdat.ssha = 0.0
            else:
                pdat.ssha = degrad * math.acos(cssha)
        elif (pdat.declin >= 0.0 and pdat.latitude > 0.0) or (pdat.declin < 0.0 and pdat.latitude < 0.0):
            pdat.ssha = 180.0
        else:
            pdat.ssha = 0.0

    @staticmethod
    def sbcf(pdat:SolposData, tdat:_Trig) -> None:
        """Shadow-band correction factor"""
        p = 0.6366198 * pdat.sbwid / pdat.sbrad * tdat.cd**3
        t1 = tdat.sl * tdat.sd * pdat.ssha * raddeg
        t2 = tdat.cl * tdat.cd * math.sin(pdat.ssha * raddeg)
        pdat.sbcf = pdat.sbsky + 1.0 / (1.0 - p * (t1 + t2))

    @staticmethod
    def tst(pdat:SolposData) -> None:
        """True solar time"""
        pdat.tst = (180.0 + pdat.hrang) * 4.0
        pdat.tstfix = pdat.tst - float(pdat.hour) * 60.0 - pdat.minute - float(pdat.second) / 60.0 + float(pdat.interval) / 120.0
        while pdat.tstfix > 720.0:
            pdat.tstfix -= 1440.0
        while pdat.tstfix < -720.0:
            pdat.tstfix += 1440.0
        pdat.eqntim = pdat.tstfix + 60.0 * pdat.timezone - 4.0 * pdat.longitude

    @staticmethod
    def srss(pdat:SolposData) -> None:
        """Sunrise and sunset times (minutes from midnight)"""
        if pdat.ssha <= 1.0:
            pdat.sretr, pdat.ssetr = 2999.0, -2999.0
        elif pdat.ssha >= 179.0:
            pdat.sretr, pdat.ssetr = -2999.0, 2999.0
        else:
            pdat.sretr = 720.0 - 4.0 * pdat.ssha - pdat.tstfix
            pdat.ssetr = 720.0 + 4.0 * pdat.ssha - pdat.tstfix

    @staticmethod
    def sazm(pdat:SolposData, tdat:_Trig) -> None:
        """Solar azimuth angle"""
        ce = math.cos(raddeg * pdat.elevetr)
        se = math.sin(raddeg * pdat.elevetr)
        pdat.azim = 180.0
        cecl = ce * tdat.cl
        if abs(cecl) >= 0.001:
            ca = (se * tdat.sl - tdat.sd) / cecl
            ca = min(max(ca, -1.0), 1.0)
            pdat.azim = 180.0 - math.acos(ca) * degrad
            if pdat.hrang > 0:
                pdat.azim = 360.0 - pdat.azim

    @staticmethod
    def refrac(pdat:SolposData) -> None:
        """Refraction correction"""
        if pdat.elevetr > 85.0:
            refcor = 0.0
        else:
            tanelev = math.tan(raddeg * pdat.elevetr)
            if pdat.elevetr >= 5.0:
                refcor = 58.1 / tanelev - 0.07 / (tanelev**3) + 0.000086 / (tanelev**5)
            elif pdat.elevetr >= -0.575:
                refcor = 1735.0 + pdat.elevetr * (-518.2 + pdat.elevetr * (103.4 + pdat.elevetr * (-12.79 + pdat.elevetr * 0.711)))
            else:
                refcor = -20.774 / tanelev
            prestemp = (pdat.press * 283.0) / (1013.0 * (273.0 + pdat.temp))
            refcor *= prestemp / 3600.0
        pdat.elevref = pdat.elevetr + refcor
        pdat.elevref = max(pdat.elevref, -9.0)
        pdat.zenref = 90.0 - pdat.elevref
        pdat.coszen = math.cos(raddeg * pdat.zenref)

    @staticmethod
    def amass(pdat:SolposData) -> None:
        """Air mass"""
        if pdat.zenref > 93.0:
            pdat.amass = -1.0
            pdat.ampress = -1.0
        else:
            pdat.amass = 1.0 / (math.cos(raddeg * pdat.zenref) + 0.50572 * (96.07995 - pdat.zenref)**-1.6364)
            pdat.ampress = pdat.amass * pdat.press / 1013.0

    @staticmethod
    def prime(pdat:SolposData) -> None:
        """Prime and unprime factors"""
        try:
            pdat.unprime = 1.031 * math.exp(-1.4 / (0.9 + 9.4 / pdat.amass)) + 0.1
        except ZeroDivisionError:
            pdat.unprime = math.nan
        pdat.prime = 1.0 / pdat.unprime if pdat.unprime else math.inf

    @staticmethod
    def etr(pdat:SolposData) -> None:
        """Extraterrestrial irradiance"""
        if pdat.coszen > 0.0:
            pdat.etrn = pdat.solcon * pdat.erv
            pdat.etr = pdat.etrn * pdat.coszen
        else:
            pdat.etrn = 0.0
            pdat.etr = 0.0

    @staticmethod
    def tilt(pdat:SolposData) -> None:
        """Cosine of incidence and extraterrestrial irradiance on the tilted surface"""
        ca = math.cos(raddeg * pdat.azim)
        cp = math.cos(pdat.aspect)
        ct = math.cos(pdat.tilt)
        sa = math.sin(raddeg * pdat.azim)
        sp = math.sin(pdat.aspect)
        st = math.sin(pdat.tilt)
        sz = math.sin(raddeg * pdat.zenref)
        pdat.cosinc = pdat.coszen * ct + sz * st * (ca * cp + sa * sp)
        pdat.etrtilt = pdat.etrn * pdat.cosinc if pdat.cosinc > 0.0 else 0.0

    @staticmethod
    def perez_tilt(pdat:SolposData) -> None:
        """Perez diffuse tilt model: the scalar `perez_horz` applied to the
        diffuse horizontal irradiance"""
        if pdat.diff_horz != 0.0:
            zen_rad = pdat.zenref * PI_OVER_180
            zen_rad_cubed = zen_rad * zen_rad * zen_rad * 1.041
            if pdat.dir_norm != 0.0:
                pdat.perez_skyclear = ((pdat.diff_horz + pdat.dir_norm)/pdat.diff_horz + zen_rad_cubed)/(1 + zen_rad_cubed)
            else:
                pdat.perez_skyclear = 1.0
            pdat.perez_skyclear_idx = -1
            for index in range(7):
                if PEREZ_CLEARNESS_LIMITS[index] <= pdat.perez_skyclear < PEREZ_CLEARNESS_LIMITS[index+1]:
                    pdat.perez_skyclear_idx = index
                    break
            if pdat.perez_skyclear_idx == -1:
                pdat.perez_skyclear_idx = 7
            if pdat.etrn == 0.0:
                pdat.perez_brightness = 0.0
            else:
                pdat.perez_brightness = pdat.diff_horz*pdat.amass/pdat.etrn
            idx = pdat.perez_skyclear_idx
            pdat.perez_F1 = PEREZ_TILT_COEFF_F1[0][idx] + PEREZ_TILT_COEFF_F1[1][idx]*pdat.perez_brightness + PEREZ_TILT_COEFF_F1[2][idx]*zen_rad
            pdat.perez_F2 = PEREZ_TILT_COEFF_F2[0][idx] + PEREZ_TILT_COEFF_F2[1][idx]*pdat.perez_brightness + PEREZ_TILT_COEFF_F2[2][idx]*zen_rad
            if pdat.perez_F1 < 0:
                pdat.perez_F1 = 0.0
            a_val = pdat.cosinc if pdat.cosinc > 0.0 else 0.0
            b_val = pdat.coszen if pdat.coszen > COS85DEG else COS85DEG
            pdat.perez_horz = (1 - pdat.perez_F1)*(1 + math.cos(pdat.tilt))/2.0 + pdat.perez_F1*a_val/b_val + pdat.perez_F2*math.sin(pdat.tilt)
        else:
            pdat.perez_horz = 0.0
