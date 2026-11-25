"""Weather files made for the tests (see `data/README.md`)

The functions write files that the tests and `data/reference/make_reference.py`
both use, so `arras` and the gridlabd reference read the same input:

- `make_tmy2()`: a TMY2 file with the Yakima TMY3 data in TMY2 columns,
  because no TMY2 file is available to check in;
- `make_year_csv()`: a CSV file with random samples every 3 hours of a
  year, with every `weather` column and the location properties;
- `make_fmt_csv()`: a CSV file with a `timefmt` time format, a leap day,
  a discarded sample, and a blank line.
"""

import os
import random
import calendar

DATA = os.path.join(os.path.dirname(__file__), "data")
"""Folder of the test data"""

TMY3 = os.path.join(DATA, "WA-Yakima_Air_Terminal.tmy3")
"""The Yakima TMY3 file"""

def make_tmy2(path:str) -> str:
    """Write the Yakima data as a TMY2 file; returns `path`"""
    with open(TMY3, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out = [" 24243 YAKIMA           WA  -8 N 46 34 W 120 33   325"]
    for line in lines[2:]:
        f = line.split(",")
        month, day, _ = f[0].split("/")
        hour = int(f[1].split(":")[0])
        def i(x):
            return int(float(x))
        tdb = int(round(float(f[31])*10))
        text = " 85" + f"{int(month):02d}{int(day):02d}{hour:02d}"
        text += f"{i(f[2]):04d}{i(f[3]):04d}{i(f[4]):04d}A1{i(f[7]):04d}A1{i(f[10]):04d}" + "X"*26
        text += f"{i(f[25]):02d}A7{i(f[28]):02d}A7" + (f"{tdb:04d}" if tdb >= 0 else f"-{-tdb:03d}")
        text += "X"*8 + f"{i(f[37]):03d}A7{i(f[40]):04d}A7{i(f[43]):03d}A7{int(round(float(f[46])*10)):03d}"
        text += "X"*25 + f"{i(float(f[64])*10):03d}" + "X"*7 + "007"
        out.append(text)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    return path

def make_year_csv(path:str) -> str:
    """Write a year of random samples every 3 hours; returns `path`"""
    rng = random.Random(4)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# full year\n$city_name=Testville\n$lat_deg=37\n$lat_min=30\n$long_deg=-122\n$long_min=15\n$timezone_offset=-8\n")
        fh.write("temperature,humidity,solar_direct,solar_diffuse,solar_global,wind_speed,wind_dir,"
            "opq_sky_cov,tot_sky_cov,rainfall,snowdepth,pressure,global_horizontal_extra\n")
        for month in range(1, 13):
            for day in range(1, calendar.monthrange(2001, month)[1]+1):
                for hour in range(0, 24, 3):
                    fh.write(f"{month}:{day}:{hour}:00:00,{rng.uniform(20,90):.2f},{rng.uniform(0,1):.3f},"
                        f"{rng.uniform(0,90):.2f},{rng.uniform(0,20):.2f},{rng.uniform(0,100):.2f},"
                        f"{rng.uniform(0,10):.1f},{rng.randint(0,359)},{rng.uniform(0,1):.2f},"
                        f"{rng.uniform(0,1):.2f},{rng.uniform(0,0.2):.3f},{rng.uniform(0,3):.2f},"
                        f"{rng.uniform(950,1030):.1f},{rng.uniform(0,120):.1f}\n")
    return path

def make_fmt_csv(path:str) -> str:
    """Write samples with a `MM/DD-HH` time format; returns `path`"""
    rng = random.Random(5)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("$lat_deg=-33\n$lat_min=52\n$long_deg=151\n$long_min=12\n$timezone_offset=10\n")
        for month, day, hour in [(2,27,0), (2,28,6), (2,29,12), (3,1,0), (3,1,0), (3,2,18), (12,31,12)]:
            fh.write(f"{month:02d}/{day:02d}-{hour:02d},{rng.uniform(30,80):.1f},{rng.uniform(0.1,0.9):.2f},{rng.uniform(10,80):.1f}\n")
        fh.write("\n")
    return path
