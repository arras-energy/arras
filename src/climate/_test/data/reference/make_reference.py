"""Make the gridlabd reference values of the climate tests

Runs gridlabd on the test weather files and writes the values that its
`recorder` objects write, one CSV file per case, into this folder. The
tests compare `arras` with these files. This script is not run by the
tests; it needs a gridlabd build with the `climate`, `tape`, `powerflow`,
and `generators` modules.

Syntax:

    python3 make_reference.py GRIDLABD [WORKDIR]

`GRIDLABD` is the gridlabd command; `WORKDIR` is a scratch folder
(default is a new temporary folder).
"""

import os
import sys
import shutil
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import climate_test_files as files # pylint: disable=wrong-import-position

PROPERTIES = ["temperature", "humidity", "heat_index", "solar_flux", "solar_horiz", "solar_north",
    "solar_northeast", "solar_east", "solar_southeast", "solar_south", "solar_southwest", "solar_west",
    "solar_northwest", "solar_direct", "solar_diffuse", "solar_global", "extraterrestrial_direct_normal",
    "extraterrestrial_global_horizontal", "pressure", "wind_speed", "wind_dir", "rainfall", "snowdepth",
    "solar_zenith", "solar_elevation", "solar_azimuth", "opq_sky_cov", "solar_raw"]
"""Climate properties recorded"""

CSV_PROPERTIES = ["temperature", "humidity", "solar_direct", "solar_diffuse", "solar_global",
    "extraterrestrial_global_horizontal", "wind_speed", "wind_dir", "opq_sky_cov", "rainfall",
    "snowdepth", "pressure", "solar_zenith", "solar_flux", "solar_horiz", "solar_north",
    "solar_northeast", "solar_east", "solar_southeast", "solar_south", "solar_southwest",
    "solar_west", "solar_northwest"]
"""Climate properties recorded with CSV files"""

TMY_CASES = [
    # name, file, interpolate, start, stop, interval
    ("yakima_none", "WA-Yakima_Air_Terminal.tmy3", "NONE", "2006-03-26 00:00:00", "2006-04-09 00:00:00", 3600),
    ("yakima_linear", "WA-Yakima_Air_Terminal.tmy3", "LINEAR", "2006-04-01 00:00:00", "2006-04-03 00:00:00", 900),
    ("yakima_quadratic", "WA-Yakima_Air_Terminal.tmy3", "QUADRATIC", "2006-10-28 00:00:00", "2006-10-30 00:00:00", 900),
    ("yakima_tmy2_none", "yakima.tmy2", "NONE", "2006-07-01 00:00:00", "2006-07-03 00:00:00", 3600),
]
"""TMY cases (time zone PST+8PDT)"""

CSV_CASES = [
    # name, file, reader options, start, stop, interval, time zone
    ("csv_weather", "weather.csv", "", "2001-01-01 00:00:00", "2001-01-02 00:00:00", 3600, "PST+8PDT"),
    ("csv_weather_dst", "weather_dst.csv", "", "2001-06-30 20:00:00", "2001-07-03 00:00:00", 1800, "PST+8PDT"),
    ("csv_year_wrap", "year.csv", "", "2001-12-30 00:00:00", "2002-01-03 00:00:00", 3600, "PST+8PDT"),
    ("csv_year_leap", "year.csv", "", "2004-02-27 00:00:00", "2004-03-02 00:00:00", 3600, "EST+5EDT"),
    ("csv_fmt", "fmt.csv", 'timefmt "%hd/%hd-%hd"; columns "temperature,humidity,solar_direct";',
        "2004-02-26 00:00:00", "2004-03-04 00:00:00", 3600, "PST+8PDT"),
]
"""CSV cases"""

SOLAR = """
object triplex_meter {{ name tm{i}; phases AS; voltage_1 120; voltage_2 120; voltage_N 0; nominal_voltage 120; }}
object triplex_meter {{ name tpm{i}; phases AS; parent tm{i}; nominal_voltage 120; }}
object inverter {{ name inv{i}; phases CS; parent tpm{i}; rated_power 2500000; }}
object solar {{ name {name}; parent inv{i}; area 141.76 ft^2; tilt_angle 30.0; efficiency 0.05;
    SOLAR_POWER_MODEL FLATPLATE; {options} latitude 46.6; longitude -120.5;
    object recorder {{ file "{name}.csv"; interval 900; property Insolation; }}; }}
"""
"""A generators `solar` object whose `Insolation` is a climate function"""

SOLAR_CASES = [
    ("solar_position", "orientation FIXED_AXIS; SOLAR_TILT_MODEL DEFAULT; orientation_azimuth 200;"),
    ("solar_solpos", "orientation FIXED_AXIS; SOLAR_TILT_MODEL SOLPOS; orientation_azimuth 200;"),
    ("solar_ideal", "orientation DEFAULT;"),
]
"""Solar objects: `calculate_solar_radiation_shading_position_radians`
(tilt 30 deg, azimuth 180-200 deg), `calculate_solpos_radiation_shading_position_radians`
(azimuth 200 deg), and `calc_solar_ideal_shading_position_radians`;
`solar_hawaii` is the solar object of `test_singleHouseSolarInverter.glm`"""

def run(gridlabd:str, folder:str, glm:str) -> None:
    """Run a model in `folder`"""
    with open(os.path.join(folder, "model.glm"), "w", encoding="utf-8") as fh:
        fh.write(glm)
    subprocess.run([gridlabd, "model.glm"], cwd=folder, check=True)

def keep(folder:str, name:str) -> None:
    """Copy a recorder file without its comment lines"""
    with open(os.path.join(folder, f"{name}.csv"), encoding="utf-8") as fh:
        lines = [x for x in fh if not x.startswith("#") or x.startswith("# timestamp")]
    with open(os.path.join(HERE, f"{name}.csv"), "w", encoding="utf-8") as fh:
        fh.writelines(lines)

def main(gridlabd:str, folder:str) -> None:
    """Make every reference file"""
    for name in ("WA-Yakima_Air_Terminal.tmy3", "weather.csv", "weather_dst.csv"):
        shutil.copy(os.path.join(files.DATA, name), folder)
    files.make_tmy2(os.path.join(folder, "yakima.tmy2"))
    files.make_year_csv(os.path.join(folder, "year.csv"))
    files.make_fmt_csv(os.path.join(folder, "fmt.csv"))
    for name, file, mode, start, stop, interval in TMY_CASES:
        run(gridlabd, folder, f"""clock {{ timezone PST+8PDT; starttime '{start}'; stoptime '{stop}'; }}
module tape;
module climate;
object climate {{ name site; tmyfile "{file}"; interpolate {mode};
    object recorder {{ file "{name}.csv"; interval {interval}; property "{','.join(PROPERTIES)}"; }}; }}
""")
        keep(folder, name)
    for name, file, options, start, stop, interval, zone in CSV_CASES:
        run(gridlabd, folder, f"""clock {{ timezone {zone}; starttime '{start}'; stoptime '{stop}'; }}
module tape;
module climate;
object csv_reader {{ name reader; filename "{file}"; {options} }}
object climate {{ name site; tmyfile "{file}"; reader reader;
    object recorder {{ file "{name}.csv"; interval {interval}; property "{','.join(CSV_PROPERTIES)}"; }}; }}
""")
        keep(folder, name)
    glm = """clock { timezone PST+8PDT; starttime '2006-05-01 00:00:00'; stoptime '2006-05-03 00:00:00'; }
module tape;
module powerflow { solver_method FBS; default_maximum_voltage_error 1e-9; line_limits FALSE; };
module generators;
module climate;
object climate { name Yakima; tmyfile "WA-Yakima_Air_Terminal.tmy3"; }
"""
    for i, (name, options) in enumerate(SOLAR_CASES):
        glm += SOLAR.format(i=i, name=name, options=options)
    run(gridlabd, folder, glm)
    for name, _ in SOLAR_CASES:
        keep(folder, name)
    glm = """clock { timezone HST+10; starttime '2000-05-05 05:00:00'; stoptime '2000-05-05 20:00:00'; }
module tape;
module powerflow { solver_method FBS; default_maximum_voltage_error 1e-9; line_limits FALSE; };
module generators;
module climate;
object climate { name NREL_climate; tmyfile "WA-Yakima_Air_Terminal.tmy3"; }
"""
    glm += SOLAR.format(i=0, name="solar_hawaii", options="orientation DEFAULT;").replace(
        "tilt_angle 30.0", "tilt_angle 90.0").replace("latitude 46.6; longitude -120.5;",
        "latitude 21.31236; longitude -158.08463;")
    run(gridlabd, folder, glm)
    keep(folder, "solar_hawaii")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp())
