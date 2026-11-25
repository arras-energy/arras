# pylint: disable=line-too-long
"""Cumulus cloud model (`climate` property `cloud_model CUMULUS`)

`CloudPattern` is gridlabd's fractal cloud model: a square pattern of
pixels, 20 m on a side, covering the `solar` objects of the model and a
border one tile (512 pixels) wide. A fractal surface is built by midpoint
displacement, cut at the elevation that gives the sky cover of the
weather data (`opq_sky_cov`, doubled), and given a fuzzy edge of random
layers. The pattern moves with the wind every time the climate object
updates it, and the cloud value of a location dims the direct solar
irradiance that the published solar functions use.

Syntax
------

    from climate.cloud import CloudPattern
    pattern = CloudPattern(locations, rng)       # [(latitude, longitude), ...]
    pattern.convert_to_binary_cloud(opq_sky_cov)
    pattern.convert_to_fuzzy_cloud(EMPTY_VALUE, num_layers, alpha)
    pattern.update(delta_t, wind_speed, wind_dir, cloud_speed_factor, opq_sky_cov, solar_zenith, num_layers, alpha)
    pattern.fuzzy_value(latitude, longitude)

Description
-----------

`CloudPattern` is expected to satisfy:

1. The pattern has `(n+2)*TILE_SIZE+1` pixels on a side, where `n` is
   the number of tiles needed to cover the locations (at least 1), and
   maps latitude and longitude onto the inner `n` tiles as gridlabd's
   `calc_cloud_pattern_size()` does.
2. Tiles are filled by `build_cloud_pattern()`'s midpoint displacement
   (fractal dimension 1.9 for the first four levels, then 1.33), with
   normal random values whose standard deviation is the square of
   gridlabd's `delta`, as gridlabd passes it.
3. `convert_to_binary_cloud()` normalizes the pattern and searches by
   bisection for the cut elevation at which the share of on-screen pixels
   at or below it is within 0.005 of twice `opq_sky_cov` (at most 0.99);
   pixels at or below the cut are cloud (0), others blue sky (1).
4. `convert_to_fuzzy_cloud()` adds, for each layer `i` (from 0) whose
   threshold `cut-(i+1)/alpha` a cloud pixel's normalized elevation does
   not exceed, a uniform random value between `i/layers` and
   `(i+1)/layers` times the cut, to the pixel's previous value; other
   pixels are 0. The result is normalized to 0 to 1, and pixels outside
   the pattern are `EMPTY_VALUE`.
5. `update()` moves the pattern by the whole pixels that the wind covers
   in `delta_t` seconds, rebuilding the edge that comes into view, and
   recomputes the binary and fuzzy patterns when it moved and the solar
   zenith is less than 110 degrees.

Caveats
-------

- The model is slow in Python: building the smallest pattern (1537 by
  1537 pixels) takes about 15 seconds, and each update that moves it about
  6 seconds, once per simulated minute. gridlabd warns that the model is
  a large burden too. `TILE_SIZE` can be lowered for tests; this changes
  the scale of the clouds, and a tile must be wider than the distance the
  wind moves the pattern in one update.
- Random values come from a Python `random.Random` per climate object, so
  cloud patterns differ from gridlabd's for the same `randomseed`.
- gridlabd's wind shift accumulators are local variables reset at each
  update, so a shift shorter than one pixel is lost; this is reproduced.
- The wind direction is read in degrees, as the TMY data holds it, even
  though `wind_dir` is published in radians.

Differences from gridlabd (as of gridlabd master 076e78a, 2026-08-16)
-----------------------------------------------------------------

1. Each climate object has its own pattern; gridlabd keeps one pattern
   for the module, shared by all climate objects with the cloud model.
2. `solar` objects without a latitude or longitude are left out, as the
   code intends; gridlabd's test `longitude != NaN` is always true, so
   it includes them.
3. With no located `solar` objects the pattern is one tile centered on
   latitude 0 and longitude 0; gridlabd reads an empty list.
4. A location outside the pattern, or not a number, raises
   `ClimateError`; gridlabd reads outside its arrays.
5. The search for the cut elevation stops after 100 steps; gridlabd's
   loop does not end when no cut gives the cover within the tolerance.
6. A pattern of one elevation normalizes to 0; gridlabd divides by 0.

References
----------

- `arras-energy/gridlabd`: `module/climate/climate.cpp`
  (`init_cloud_pattern()`, `calc_cloud_pattern_size()`,
  `build_cloud_pattern()`, `convert_to_binary_cloud()`,
  `convert_to_fuzzy_cloud()`, `update_cloud_pattern()`,
  `rebuild_cloud_pattern_edge()`, `trim_pattern_edge()`,
  `erase_off_screen_pattern()`, `get_fuzzy_cloud_value_for_location()`,
  `get_binary_cloud_value_for_location()`)
- Hansen, C. W., Stein, J. S., and Ellis, A., "Simulation of one-minute
  power output from utility-scale photovoltaic generation systems,"
  SAND2011-5529, 2011
"""

import math
import random
from typing import Any

from ._common import ClimateError, rad, lerp

TILE_SIZE = 512
"""Pixels on a side of a tile (gridlabd `CLOUD_TILE_SIZE`)"""

PIXEL_EDGE_SIZE = 20
"""Meters on a side of a pixel"""

KM_PER_DEG = 111.32
"""Kilometers per degree of latitude"""

EMPTY_VALUE = -999
"""Value of a pixel outside the pattern"""

SEARCH_TOLERANCE = 0.005
"""Tolerance of the sky cover when searching for the cut elevation"""

MAX_SEARCH_STEPS = 100
"""Most bisection steps in the search for the cut elevation"""

class CloudPattern: # pylint: disable=too-many-instance-attributes
    """A cloud pattern; see the module documentation

    Attributes
    ----------
    - `tile`: pixels on a side of a tile
    - `size`: pixels on a side of the pattern
    - `on_screen`: pixels on a side of the area that covers the locations
    - `cloud`, `normalized`, `binary`, `fuzzy`: the fractal, normalized,
      binary, and fuzzy patterns (`size` lists of `size` values)
    - `min_lat`, `max_lat`, `min_lon`, `max_lon`: corners of the area
    - `min_index`, `max_index`: pixel indexes of the corners
    """

    def __init__(self, locations:list[tuple[float,float]], rng:random.Random):
        self.rng = rng
        self.tile = TILE_SIZE
        self.min_lat = self.max_lat = self.min_lon = self.max_lon = 0.0
        self.min_index = self.max_index = 0
        edges = self._pattern_size(locations)
        self.size = edges * self.tile + 1
        self.on_screen = (edges - 2) * self.tile
        size = self.size
        self.cloud = [[float(EMPTY_VALUE)] * size for _ in range(size)]
        self.binary = [[EMPTY_VALUE] * size for _ in range(size)]
        self.normalized = [[float(EMPTY_VALUE)] * size for _ in range(size)]
        self.fuzzy: list[list[float]] = []
        for i in range(edges):
            for j in range(edges):
                self.build(i*self.tile, (i+1)*self.tile, j*self.tile, (j+1)*self.tile)

    def _pattern_size(self, locations:list[tuple[float,float]]) -> int:
        """gridlabd `calc_cloud_pattern_size()`: tiles on a side, with the
        border"""
        if locations:
            lat_max = lat_min = locations[0][0]
            long_max = long_min = locations[0][1]
        else:
            lat_max = lat_min = long_max = long_min = 0.0
        lat_delta = long_delta = 0.0
        num_tile_edge = 1
        if len(locations) > 1:
            for lat, lon in locations[1:]:
                lat_max, lat_min = max(lat_max, lat), min(lat_min, lat)
                long_max, long_min = max(long_max, lon), min(long_min, lon)
            lat_delta = abs(lat_max - lat_min)
            long_delta = abs(long_max - long_min)
            x_size_km = lat_delta * KM_PER_DEG
            y_size_km = long_delta * math.cos(rad(lat_min)) * KM_PER_DEG
            max_dim_km = max(x_size_km, y_size_km)
            num_tile_edge = math.ceil((max_dim_km * 1000. / PIXEL_EDGE_SIZE) / self.tile)
        self.min_index = self.tile
        self.max_index = self.tile + num_tile_edge * self.tile
        degree_range_lat = (num_tile_edge * self.tile * PIXEL_EDGE_SIZE)/1000./KM_PER_DEG
        degree_range_lon = (num_tile_edge * self.tile * PIXEL_EDGE_SIZE)/1000./KM_PER_DEG/math.cos(rad(lat_min))
        self.min_lat = lat_min - (degree_range_lat-lat_delta)/2.
        self.max_lat = self.min_lat + degree_range_lat
        self.min_lon = long_min - (degree_range_lon-long_delta)/2.
        self.max_lon = self.min_lon + degree_range_lon
        return num_tile_edge + 2

    def build(self, col_min:int, col_max:int, row_min:int, row_max:int) -> None: # pylint: disable=unused-argument,too-many-locals
        """gridlabd `build_cloud_pattern()`: fill the empty pixels of a
        tile by midpoint displacement"""
        sigma = 5
        pattern = self.cloud
        empty = EMPTY_VALUE * 0.98
        gauss = self.rng.gauss
        step = col_max - col_min
        half_step = step // 2
        max_num_recursions = int(math.log(float(col_max - col_min))/math.log(2.0))
        stdev = float(sigma * sigma)
        for row, col in ((row_min, col_min), (row_min+step, col_min), (row_min, col_min+step), (row_min+step, col_min+step)):
            if pattern[row][col] < empty:
                pattern[row][col] = gauss(0, stdev)
        delta = 0.0
        for k in range(max_num_recursions):
            col_start = col_min
            dim = 1.9 if k <= 3 else 1.33
            delta = sigma * 0.5**(0.5 * (2-dim)) if k == 0 else delta * 0.5**(0.5 * (2-dim))
            stdev = delta*delta
            end = 2**k
            for _ in range(end):
                row_start = row_min
                for _ in range(end):
                    top, bottom = pattern[row_start], pattern[row_start + step]
                    middle = pattern[row_start + half_step]
                    c1, c2 = top[col_start], top[col_start + step]
                    c3, c4 = bottom[col_start], bottom[col_start + step]
                    x = (c1 + c2 + c3 + c4)/4 + gauss(0, stdev)
                    e_a = (x + c1 + c3)/3 + gauss(0, stdev)
                    e_b = (x + c1 + c2)/3 + gauss(0, stdev)
                    e_c = (x + c2 + c4)/3 + gauss(0, stdev)
                    e_d = (x + c3 + c4)/3 + gauss(0, stdev)
                    if middle[col_start + half_step] < empty:
                        middle[col_start + half_step] = x
                    if middle[col_start] < empty:
                        middle[col_start] = e_a
                    if top[col_start + half_step] < empty:
                        top[col_start + half_step] = e_b
                    if middle[col_start + step] < empty:
                        middle[col_start + step] = e_c
                    if bottom[col_start + half_step] < empty:
                        bottom[col_start + half_step] = e_d
                    row_start += step
                col_start += step
            step = half_step
            half_step = half_step // 2

    def convert_to_binary_cloud(self, opq_sky_cov:float) -> float: # pylint: disable=too-many-locals,too-many-branches
        """gridlabd `convert_to_binary_cloud()`; returns the cut elevation"""
        cloud_value = opq_sky_cov * 2.0
        if cloud_value >= 1:
            cloud_value = 0.99
        size, tile = self.size, self.tile
        pattern = self.cloud
        pmax = pmin = pattern[tile][tile]
        for row in pattern:
            for value in row:
                if value != EMPTY_VALUE:
                    pmax = max(pmax, value)
                    pmin = min(pmin, value)
        span = pmax - pmin
        for i in range(size):
            row, out = pattern[i], self.normalized[i]
            for j in range(size):
                if row[j] != EMPTY_VALUE:
                    out[j] = (row[j] - pmin)/span if span != 0 else 0.0
        cut = pmin
        step = 0.0
        max_cut, min_cut = pmax, pmin
        area = self.on_screen * self.on_screen
        steps = 0
        while True:
            cut += step
            count = 0
            for i in range(tile, tile + self.on_screen):
                row = self.normalized[i]
                for j in range(tile, tile + self.on_screen):
                    value = row[j]
                    if value != EMPTY_VALUE and value <= cut:
                        count += 1
            coverage = count/area if area else 0.0
            if coverage > cloud_value + SEARCH_TOLERANCE:
                max_cut = cut
                step = (max_cut - min_cut)/-2
            elif coverage < cloud_value - SEARCH_TOLERANCE:
                min_cut = cut
                step = (max_cut - min_cut)/2
            steps += 1
            if cloud_value - SEARCH_TOLERANCE <= coverage <= cloud_value + SEARCH_TOLERANCE or steps >= MAX_SEARCH_STEPS:
                break
        for i in range(size):
            row, out = self.normalized[i], self.binary[i]
            for j in range(size):
                value = row[j]
                if value == EMPTY_VALUE:
                    out[j] = EMPTY_VALUE
                elif value <= cut:
                    out[j] = 0
                else:
                    out[j] = 1
        return cut

    def convert_to_fuzzy_cloud(self, cut_elevation:float, num_fuzzy_layers:int, alpha:float) -> None: # pylint: disable=too-many-locals,too-many-branches
        """gridlabd `convert_to_fuzzy_cloud()`; `cut_elevation` is
        `EMPTY_VALUE` on the first call, which creates the fuzzy pattern"""
        size = self.size
        layers = int(num_fuzzy_layers)
        shade_step_size = 1.0/alpha
        if cut_elevation == EMPTY_VALUE or not self.fuzzy:
            self.fuzzy = [[0.0] * size for _ in range(size)]
        uniform = self.rng.uniform
        bounds = [(((i+1)-1)/layers*cut_elevation, (i+1)/layers*cut_elevation,
            cut_elevation - (i+1)*shade_step_size) for i in range(layers)]
        for j in range(size):
            binary, normal, fuzzy = self.binary[j], self.normalized[j], self.fuzzy[j]
            for k in range(size):
                value = fuzzy[k]
                first = 0
                if value == EMPTY_VALUE:
                    # gridlabd's first layer sets the pixel to 0; later layers add to it
                    value = 0.0
                    first = 1
                if binary[k] != 0 or normal[k] == EMPTY_VALUE or layers == 0:
                    fuzzy[k] = 0.0
                    continue
                elevation = normal[k]
                for i in range(first, layers):
                    lower, upper, threshold = bounds[i]
                    if elevation > threshold:
                        break
                    value = uniform(lower, upper) + value
                fuzzy[k] = value
        vmax = vmin = self.fuzzy[0][0]
        for row in self.fuzzy:
            vmax = max(vmax, *row)
            vmin = min(vmin, *row)
        span = vmax - vmin
        if span != 0:
            for row in self.fuzzy:
                for k, value in enumerate(row):
                    row[k] = (value - vmin)/span
        for j in range(size):
            source, fuzzy = self.cloud[j], self.fuzzy[j]
            for k in range(size):
                if source[k] == EMPTY_VALUE:
                    fuzzy[k] = EMPTY_VALUE

    def update(self, delta_t:float, wind_speed:float, wind_dir:float, solar_zenith:float, # pylint: disable=too-many-arguments,too-many-positional-arguments
            opq_sky_cov:float, num_layers:int, alpha:float) -> None:
        """gridlabd `update_cloud_pattern()`: move the pattern with the
        wind (`wind_speed` already multiplied by `cloud_speed_factor`,
        `wind_dir` in degrees) over `delta_t` seconds"""
        direction = -1 * ((wind_dir - 180) - 90)
        if direction <= -360:
            direction += 360
        elif direction >= 360:
            direction -= 360
        direction = rad(direction)
        col_shift_px = (wind_speed * math.cos(direction) * delta_t)/PIXEL_EDGE_SIZE
        row_shift_px = (wind_speed * math.sin(direction) * delta_t)/PIXEL_EDGE_SIZE
        col_shift = math.floor(col_shift_px) if abs(col_shift_px) >= 1 else 0
        row_shift = math.floor(row_shift_px) if abs(row_shift_px) >= 1 else 0
        if row_shift == 0 and col_shift == 0:
            return
        self._shift(row_shift, col_shift)
        if solar_zenith < (110*math.pi/180):
            cut = self.convert_to_binary_cloud(opq_sky_cov)
            self.convert_to_fuzzy_cloud(cut, num_layers, alpha)

    def _edge_empty(self, fixed:int, along_rows:bool, inclusive:bool=False) -> bool:
        tile, on_screen = self.tile, self.on_screen
        stop = tile + on_screen + (1 if inclusive else 0)
        if along_rows:
            return any(self.cloud[row][fixed] == EMPTY_VALUE for row in range(tile, stop))
        return any(self.cloud[fixed][col] == EMPTY_VALUE for col in range(tile, stop))

    def _shift(self, row_shift:int, col_shift:int) -> None: # pylint: disable=too-many-branches
        tile, on_screen, size = self.tile, self.on_screen, self.size
        if row_shift >= 0 and col_shift >= 0:
            if col_shift > 0 and self._edge_empty(tile - col_shift, True):
                self.rebuild_edge("W")
            if row_shift > 0 and self._edge_empty(tile - row_shift, False):
                self.rebuild_edge("S")
        elif col_shift <= 0 <= row_shift:
            if col_shift < 0 and self._edge_empty(tile + on_screen - col_shift, True):
                self.rebuild_edge("E")
            if row_shift > 0 and self._edge_empty(tile - row_shift, False):
                self.rebuild_edge("S")
        elif row_shift <= 0 <= col_shift:
            if col_shift > 0 and self._edge_empty(tile - col_shift, True, inclusive=True):
                self.rebuild_edge("W")
            if row_shift < 0 and self._edge_empty(tile + on_screen - row_shift, False):
                self.rebuild_edge("N")
        else:
            if col_shift < 0 and self._edge_empty(tile + on_screen - col_shift, True):
                self.rebuild_edge("E")
            if row_shift < 0 and self._edge_empty(tile + on_screen - row_shift, False):
                self.rebuild_edge("N")
        # move every value by the shift, in the order gridlabd moves them
        # (rows and columns descending in the direction of the shift)
        rows = range(size-1, -1, -1) if row_shift >= 0 else range(size)
        cols = range(size-1, -1, -1) if col_shift >= 0 else range(size)
        pattern = self.cloud
        empty = float(EMPTY_VALUE)
        for row in rows:
            source = pattern[row]
            target_row = row + row_shift
            if target_row < 0 or target_row > size - 1:
                for col in cols:
                    source[col] = empty
                continue
            target = pattern[target_row]
            for col in cols:
                target_col = col + col_shift
                if target_col < 0 or target_col > size - 1:
                    source[col] = empty
                else:
                    target[target_col] = source[col]
                    source[col] = empty

    def rebuild_edge(self, edge:str) -> None:
        """gridlabd `rebuild_cloud_pattern_edge()`"""
        tile, on_screen = self.tile, self.on_screen
        count = 1 + on_screen//tile + 1
        if edge in "WE":
            col_min = 0 if edge == "W" else tile + on_screen - 1
            row_min = 0
            self.erase_off_screen(edge)
            for _ in range(count):
                self.build(col_min, col_min + tile, row_min, row_min + tile)
                row_min += tile
        else:
            col_min = 0
            row_min = tile + on_screen - 1 if edge == "N" else 0
            self.erase_off_screen(edge)
            for _ in range(count):
                self.build(col_min, col_min + tile, row_min, row_min + tile)
                col_min += tile
        self.trim_edge(edge)

    def trim_edge(self, edge:str) -> None: # pylint: disable=too-many-locals
        """gridlabd `trim_pattern_edge()`"""
        tile, on_screen, size = self.tile, self.on_screen, self.size
        pattern = self.cloud
        probes = (10, tile + 10, tile + on_screen + 10)
        if edge in "WE":
            def value(i:int, probe:int) -> float:
                return pattern[i][probe]
        else:
            def value(i:int, probe:int) -> float:
                return pattern[probe][i]
        mins = []
        for probe in probes:
            found = 0
            for i in range(tile):
                if value(i, probe) != EMPTY_VALUE:
                    found = i
                    break
            mins.append(found)
        maxs = []
        for probe in probes:
            found = tile + on_screen + tile
            for i in range(tile + on_screen, size):
                if value(i, probe) == EMPTY_VALUE:
                    found = i
                    break
            maxs.append(found)
        min_edge, max_edge = max(mins), min(maxs)
        empty = float(EMPTY_VALUE)
        if edge in "WE":
            for i in list(range(min_edge)) + list(range(max_edge, size)):
                pattern[i] = [empty] * size
        else:
            for row in pattern:
                for j in list(range(min_edge)) + list(range(max_edge, size)):
                    row[j] = empty

    def erase_off_screen(self, edge:str) -> None:
        """gridlabd `erase_off_screen_pattern()`"""
        tile, size = self.tile, self.size
        empty = float(EMPTY_VALUE)
        pattern = self.cloud
        if edge == "W":
            for row in pattern:
                row[0:tile-1] = [empty] * (tile-1)
        elif edge == "E":
            for row in pattern:
                row[size-tile+1:size] = [empty] * (tile-1)
        elif edge == "N":
            for i in range(size-tile+1, size):
                pattern[i] = [empty] * size
        elif edge == "S":
            for i in range(0, tile-1):
                pattern[i] = [empty] * size

    def _pixel(self, latitude:float, longitude:float) -> tuple[int,int]:
        try:
            x = math.floor(lerp(latitude, self.min_lat, self.min_index, self.max_lat, self.max_index))
            y = math.floor(lerp(longitude, self.min_lon, self.min_index, self.max_lon, self.max_index))
        except (ValueError, OverflowError) as err:
            raise ClimateError(f"location ({latitude}, {longitude}) is not valid for the cloud pattern") from err
        if not (0 <= x < self.size and 0 <= y < self.size):
            raise ClimateError(f"location ({latitude}, {longitude}) is outside the cloud pattern")
        return x, y

    def fuzzy_value(self, latitude:float, longitude:float) -> float:
        """Fuzzy cloud value of a location (0 clear to 1 dark cloud;
        gridlabd `get_fuzzy_cloud_value_for_location()`)"""
        x, y = self._pixel(latitude, longitude)
        return self.fuzzy[x][y] if self.fuzzy else 0.0

    def binary_value(self, latitude:float, longitude:float) -> int:
        """Binary cloud value of a location (0 cloud, 1 blue sky;
        gridlabd `get_binary_cloud_value_for_location()`)"""
        x, y = self._pixel(latitude, longitude)
        return self.binary[x][y]

def solar_locations(model:Any) -> list[tuple[float,float]]:
    """Latitude and longitude of the objects of class `solar` that have
    both (gridlabd `gl_find_objects(FL_GROUP,"class=solar")`)"""
    result = []
    for name, obj in model.objects.items():
        if obj.oclass.name != "solar":
            continue
        try:
            lat = float(model.get_property(name, "latitude"))
            lon = float(model.get_property(name, "longitude"))
        except (TypeError, ValueError):
            continue
        if not (math.isnan(lat) or math.isnan(lon)):
            result.append((lat, lon))
    return result
