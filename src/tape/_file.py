# pylint: disable=line-too-long
"""@private File tapes (gridlabd `module/tape_file`)

The file operations that gridlabd loads from the separate `tape_file`
module (`tape_file.cpp`) when a tape's `mode` is `file`, built into the
`tape` package: opening, reading, writing, flushing, and closing the CSV
files of players, shapers, recorders, collectors, and histograms, with the
header lines that the `tape::csv_data_only` (or `tape::csv_header_type`)
global selects and the `tape::csv_keep_clean` option.

Only the `file` mode exists. gridlabd loads a module `tape_MODE` for any
other mode; `memory` and `plot` are not supported here (see the package
documentation), so `get_ftable()` fails for them with gridlabd's message.
"""

import os
import time
from typing import Any

from ._common import MODULE, TS_OPEN, TS_DONE, TS_ERROR, TS_ZERO, gl_error, runner

def csv_data_only(model:Any) -> int:
    """Header type of CSV output: 0 (`FULL`), 1 (`NONE`), or 2 (`NAME`)

    gridlabd's `tape::csv_data_only` and `tape::csv_header_type` globals
    share one integer; `load()` keeps the two in step.
    """
    value = model.globals.getvalue(f"{MODULE}::csv_data_only")
    return int(value or 0)

def csv_keep_clean(model:Any) -> bool:
    """`True` when every row is flushed (`tape::csv_keep_clean`)"""
    return bool(model.globals.getvalue(f"{MODULE}::csv_keep_clean"))

def asctime() -> str:
    """C `asctime(localtime(&now))` without the newline"""
    return time.asctime(time.localtime())

def getenv(name:str) -> str:
    """C `getenv()` as `printf("%s")` writes it: `(null)` when not set"""
    value = os.environ.get(name)
    return "(null)" if value is None else value

class _Stdout:
    """File `-`: lines written to the runner's output"""

    def __init__(self):
        self.buffer = ""

    def write(self, text:str) -> int:
        """Write text; each complete line goes to the runner's output"""
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            runner().output(line)
        return len(text)

    def flush(self) -> None:
        """Flush a partial line"""
        if self.buffer:
            runner().output(self.buffer)
            self.buffer = ""

    def readline(self) -> str: # pragma: no cover
        """Standard input is not read"""
        return ""

    def close(self) -> None:
        """Close (flush a partial line)"""
        self.flush()

def get_ftable(mode:str) -> bool:
    """`True` for the `file` mode; else an error line as gridlabd's
    `get_ftable()` writes it when no `tape_MODE` module is found"""
    if mode in ("file", ""):
        return True
    gl_error(f"unable to locate tape_{mode}.so")
    return False

def _header_target(model:Any, name:str) -> str|None:
    parent = model.objects[name].get("parent")
    if not parent:
        return None
    pobj = model.objects[parent]
    return f"{pobj.oclass.name} {pobj.id}"

#
# Players
#
def open_player(st:Any, fname:str) -> bool:
    """`open_player()`: open the file for reading"""
    try:
        st.fp = _Stdout() if fname == "-" else open(fname, "r", encoding="utf-8", errors="replace") # pylint: disable=consider-using-with
    except OSError as err:
        st.lasterr = f"player file {fname}: {err.strerror}"
        st.status = TS_DONE
        return False
    st.loopnum = st.loop
    st.status = TS_OPEN
    return True

def read_player(st:Any) -> str|None:
    """`read_player()`: the next line (C `fgets()` with a 1024-byte buffer),
    or `None` at the end of the file"""
    line = st.fp.readline(1023)
    return line if line else None

def rewind_player(st:Any) -> None:
    """`rewind_player()`: back to the start of the file"""
    st.fp.seek(0)

def close_player(st:Any) -> None:
    """`close_player()`"""
    st.fp.close()
    st.status = TS_DONE

#
# Shapers
#
def setmap(spec:str, size:int) -> set[int]|None:
    """Bits set by a cron-like field (`setmap()`): `*`, numbers, `a-b`
    spans (wrapping), `;` to stop a span; `None` when not valid"""
    bits: set[int] = set()
    last = -1
    pos = 0
    while pos < len(spec):
        char = spec[pos]
        if char == "*":
            bits.update(range(size))
            pos += 1
        elif char.isdigit():
            end = pos
            while end < len(spec) and spec[end].isdigit():
                end += 1
            i = int(spec[pos:end])
            if last < 0:
                bits.add(i)
            elif i > last:
                bits.update(range(last, i+1))
            else:
                bits.update(range(last, size))
                bits.update(range(0, i+1))
            last = i
            pos = end
        elif char == "-":
            pos += 1
        elif char == ";":
            last = -1
            pos += 1
        else:
            return None
    return bits

def open_shaper(st:Any, fname:str) -> bool:
    """`open_shaper()`: read the shape file into `st.shape`, keyed on
    `(month, day, weekday, hour)` with values 0 to 255, and set `st.scale`"""
    # pylint: disable=too-many-locals,too-many-branches,too-many-return-statements,too-many-statements,too-many-nested-blocks
    try:
        fp = open(fname, "r", encoding="utf-8", errors="replace") # pylint: disable=consider-using-with
    except OSError as err:
        st.lasterr = f"shaper file {fname}: {err.strerror}"
        st.status = TS_ERROR
        return False
    st.status = TS_OPEN
    st.step = 3600
    st.interval = 24
    st.shape = {}
    group = "(unnamed)"
    total = peak = 0.0
    scale: dict[tuple[int,int,int,int],float] = {}
    with fp:
        for linenum, line in enumerate(fp, 1):
            text = line.lstrip()
            if text == "" or text[0] == "#":
                continue
            if group != "" and (text[0].isdigit() or text[0] == "*"):
                fields = line.split(None, 4)
                if len(fields) < 5 or "," not in fields[4]:
                    st.lasterr = f"{fname}({linenum}) : shape '{group}' missing specification '{line}'"
                    st.status = TS_ERROR
                    return False
                minute, hour, day, month = fields[:4]
                weekday, value = fields[4].split(",", 1)
                value = value.split(",", 1)[0].split("\n", 1)[0]
                if minute[0] != "*":
                    st.lasterr = f"{fname}({linenum}) : minutes are ignored in '{line}'"
                    st.status = TS_ERROR
                    return False
                maps = []
                for what, spec, size in (("hours", hour, 24), ("days", day, 31), ("months", month, 12), ("weekdays", weekday, 7)):
                    bits = setmap(spec, size)
                    if bits is None:
                        st.lasterr = f"{fname}({linenum}): {what} in '{line}' not valid"
                        st.status = TS_ERROR
                        return False
                    maps.append(bits)
                hours, days, months, weekdays = maps # pylint: disable=unbalanced-tuple-unpacking
                load = float(_float32(_atof(value)))
                for m in range(12):
                    if m not in months:
                        continue
                    for w in range(7):
                        if w not in weekdays:
                            continue
                        for d in range(31):
                            if d not in days:
                                continue
                            for h in range(24):
                                if h in hours:
                                    scale[(m, d, w, h)] = -load
                total = _float32(total + load)
                peak = max(peak, load)
            elif text[0] == "}":
                st.scale = _float32(_float32(peak/255)/total) if total else float("inf")
                for key, value in scale.items():
                    if value < 0:
                        st.shape[key] = int(-value/peak*255 + 0.5) & 0xFF
                group = ""
            else:
                # sscanf(p,"%s {",group) reads the first word whatever follows
                group = text.split()[0]
                total = 0.0
    st.status = TS_OPEN
    return True

def _float32(value:float) -> float:
    import struct # pylint: disable=import-outside-toplevel
    return struct.unpack("f", struct.pack("f", value))[0]

def _atof(text:str) -> float:
    from ._common import atof # pylint: disable=import-outside-toplevel
    return atof(text)

#
# Recorders, collectors, and histograms
#
def _open_output(st:Any, fname:str, what:str) -> bool:
    try:
        st.fp = _Stdout() if fname == "-" else open(fname, "w", encoding="utf-8") # pylint: disable=consider-using-with
    except OSError as err:
        runner().stderr.append(f"{what} file {fname}: {err.strerror}")
        return False
    return True

def open_recorder(model:Any, name:str, st:Any, fname:str, columns:str) -> bool:
    """`open_recorder()`: open the file and write its header with the
    column names `columns` (also used by multi-recorders)"""
    if not _open_output(st, fname, "recorder"):
        st.status = TS_DONE
        return False
    st.last_ts = TS_ZERO
    st.status = TS_OPEN
    st.samples = 0
    mode = csv_data_only(model)
    if mode == 0:
        lines = [f"# file...... {st.file}", f"# date...... {asctime()}",
            f"# user...... {getenv('USER')}", f"# host...... {getenv('HOST')}"]
        target = _header_target(model, name)
        if target is not None:
            lines.append(f"# target.... {target}")
        lines += [f"# trigger... {st.trigger or '(none)'}", f"# interval.. {st.interval}",
            f"# limit..... {st.limit}", f"# timestamp,{columns}"]
        st.fp.write("\n".join(lines) + "\n")
    elif mode == 2:
        st.fp.write(f"timestamp,{columns}\n")
    return True

def write_row(model:Any, st:Any, timestamp:str, value:str) -> bool:
    """`write_recorder()`, `write_collector()`, `write_histogram()`: a row
    `TIMESTAMP,VALUE`"""
    if st.fp is None:
        return False
    st.fp.write(f"{timestamp},{value}\n")
    if csv_keep_clean(model):
        st.fp.flush()
    return True

def flush(st:Any) -> None:
    """`flush_recorder()`, `flush_collector()`, `flush_histogram()`"""
    if st.fp is not None:
        st.fp.flush()

def close_recorder(model:Any, st:Any) -> None:
    """`close_recorder()` and `close_collector()`: the end-of-tape line
    (unless `csv_data_only` is set) and close"""
    if st.fp is not None:
        if not csv_data_only(model):
            st.fp.write("# end of tape\n")
        st.fp.close()
        st.fp = None

def open_collector(model:Any, st:Any, fname:str) -> bool:
    """`open_collector()`: open the file and write its header"""
    if not _open_output(st, fname, "collector"):
        st.status = TS_DONE
        return False
    st.last_ts = TS_ZERO
    st.status = TS_OPEN
    st.samples = 0
    mode = csv_data_only(model)
    if mode == 0:
        lines = [f"# file...... {st.file}", f"# date...... {asctime()}",
            f"# user...... {getenv('USER')}", f"# host...... {getenv('HOST')}",
            f"# group..... {st.group}", f"# trigger... {st.trigger or '(none)'}",
            f"# interval.. {st.interval}", f"# limit..... {st.limit}",
            f"# property.. timestamp,{st.property}"]
        st.fp.write("\n".join(lines) + "\n")
    elif mode == 2:
        st.fp.write(f"timestamp,{st.property}\n")
    return True

def open_histogram(model:Any, name:str, st:Any, fname:str) -> bool:
    """`open_histogram()`: open the file and write its header"""
    if not _open_output(st, fname, "histogram"):
        return False
    st.t_count = TS_ZERO
    st.t_sample = TS_ZERO
    mode = csv_data_only(model)
    if mode == 0:
        lines = [f"# file...... {st.fname}", f"# date...... {asctime()}",
            f"# user...... {getenv('USER')}", f"# host...... {getenv('HOST')}"]
        target = _header_target(model, name)
        lines.append(f"# target.... {target}" if target is not None else f"# group.... {st.group}")
        lines += [f"# counting interval.. {st.counting_interval:f}",
            f"# sampling interval.. {st.sampling_interval:f}", f"# limit..... {st.limit}"]
        st.fp.write("\n".join(lines) + "\n")
        if st.bins:
            st.fp.write(f"# timestamp,{st.bins}\n")
        else:
            st.fp.write(",".join(f"{'[' if b.low_inc else '('}{b.low:f}..{b.high:f}{']' if b.high_inc else ')'}" for b in st.bin_list) + "\n")
    elif mode == 2:
        st.fp.write(f"timestamp,{st.property}\n")
    return True

def close_histogram(st:Any) -> None:
    """`close_histogram()`: the end-of-tape line and close"""
    if st.fp is not None:
        st.fp.write("# end of tape\n")
        st.fp.close()
        st.fp = None
