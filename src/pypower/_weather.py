"""@private Weather files read by `bus` and `weather` objects
(gridlabd `bus::load_weather()`, `add_weather()`, `get_weather()`, and the
same functions of `weather`)"""

import re
import calendar
from typing import Any

from arras.exceptions import ArrasException

from ._common import TS_NEVER, get_double, set_double

N_WEATHERDATA = 10
"""Values kept per weather record"""

_NUMBER = re.compile(r"\s*([-+]?(?:(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf(?:inity)?|nan))",
    re.IGNORECASE)

def atof(text:str) -> float:
    """C `atof()`: the leading number of the text, else 0"""
    match = _NUMBER.match(text)
    return float(match.group(1)) if match else 0.0

def strtok(text:str, delimiters:str) -> list[str]:
    """The tokens C `strtok()` returns"""
    return [x for x in re.split("[" + re.escape(delimiters) + "]+", text) if x]

_ISO_OFFSET = re.compile(
    r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)([-+])(\d\d):?(\d\d)")

_DAYS: dict[tuple[str,str,str],int|None] = {}
"""UTC timestamps of dates at midnight (`None` for dates that are not valid)"""

def parse_time(model:Any, text:str) -> int|None:
    """Timestamp of text as gridlabd's `gld_clock(text)` reads it (local
    time of the model, a time zone abbreviation of the model's zone, or a
    UTC offset), or `None` when it is not valid"""
    match = _ISO_OFFSET.fullmatch(text.strip())
    if match:
        date = match.group(1, 2, 3)
        midnight = _DAYS.get(date, False)
        if midnight is False:
            year, month, day = (int(x) for x in date)
            valid = 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]
            midnight = calendar.timegm((year, month, day, 0, 0, 0)) if valid else None
            _DAYS[date] = midnight
        hour, minute, second = int(match.group(4)), int(match.group(5)), int(match.group(6))
        if midnight is not None and hour < 24 and minute < 60 and second < 60:
            offset = (int(match.group(8))*60 + int(match.group(9)))*60
            sign = 1 if match.group(7) == "+" else -1
            return midnight + hour*3600 + minute*60 + second - sign*offset
    from tape._common import to_timestamp # pylint: disable=import-outside-toplevel
    try:
        return to_timestamp(model, text)
    except (ArrasException, ValueError, OverflowError):
        return None

class WeatherData:
    """Weather records of one object, and the record in use"""

    def __init__(self):
        self.records: list[tuple[int,list[float]]] = []
        """`(timestamp, values)` in time order"""
        self.mapper: list[str] = []
        """Properties that receive the values, in column order"""
        self.current = 0
        """Index of the record in use (`len(records)` past the end)"""

    def load(self, model:Any, name:str, file:str, variables:str, resolution:float, msg:Any) -> bool:
        """Read a weather file; `False` (with an error) on failure"""
        # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        oclass = model.objects[name].oclass
        self.mapper = []
        for var in strtok(variables, ","):
            if oclass.find_property(var) is None:
                msg.error(f"weather variable '{var}' is not valid")
                return False
            self.mapper.append(var)
        try:
            # pylint: disable-next=consider-using-with
            fh = open(file, "r", encoding="utf-8", errors="replace")
        except OSError:
            msg.error(f"file '{file}' open for read failed")
            return False
        result = False
        with fh:
            for lineno, line in enumerate(_lines(fh)):
                if "," not in line or not line[:1].isdigit():
                    continue
                stamp, data = line.split(",", 1)
                t = parse_time(model, stamp)
                if t is None:
                    msg.error(f"{file}@{lineno}: timestamp '{stamp}' is not valid")
                    result = False
                    break
                if resolution > 0 and t % int(resolution) == 0:
                    if not self.add(model, t, data, msg):
                        msg.error(f"{file}@{lineno}: weather data read failed")
                        result = False
                        break
                result = True
        self.current = 0
        return result

    def add(self, model:Any, t:int, data:str, msg:Any) -> bool:
        """Add a record (gridlabd `add_weather()`)"""
        if self.records and t <= self.records[-1][0]:
            ts = model.globals.timestamp_to_string
            last = ts(self.records[-1][0])
            msg.error(f"duplicate or out-of-sequence timestamp (t='{ts(t)}' <= last->t='{last}')")
            return False
        values = [atof(x) for x in strtok(data, ",")][:N_WEATHERDATA]
        values += [0.0]*(N_WEATHERDATA - len(values))
        self.records.append((t, values))
        return True

    def get(self, model:Any, name:str, t:int, msg:Any) -> None:
        """Set the properties from the first record at or after `t`
        (gridlabd `get_weather()`)"""
        if not self.records:
            return
        while self.current < len(self.records) and self.records[self.current][0] < t:
            self.current += 1
        if self.current >= len(self.records):
            msg.warning("weather data ended unexpectedly")
            return
        values = self.records[self.current][1]
        for n, prop in enumerate(self.mapper[:N_WEATHERDATA]):
            set_double(model, name, prop, values[n])

    def next_time(self) -> int:
        """Time of the record after the one in use, or `TS_NEVER`"""
        if self.current + 1 < len(self.records):
            return self.records[self.current + 1][0]
        return TS_NEVER

def _lines(fh:Any):
    """Lines as C `fgets(buffer,1023,fp)` returns them (long lines are
    split), with their newline"""
    for line in fh:
        while len(line) > 1022:
            yield line[:1022]
            line = line[1022:]
        yield line

def value(model:Any, name:str, prop:str) -> float:
    """A weather property value"""
    return get_double(model, name, prop)
