#!/usr/bin/env python3
"""
uniproto_sim.py — a simulated UniProto Arduino, for trying the dashboard without hardware.

  python dashboard/uniproto_sim.py [--board dc_motor|qtr8|sensor_shield]
      Simulated UniProto device 'SimLab' is listening on /dev/ttys005
      Try it:   python dashboard/dashboard.py --port /dev/ttys005

It creates a pseudo-terminal (macOS / Linux; not Windows) and answers exactly like the
UniProto library does: the same command grammar (?  ?key  !key:value  @action), the same
replies (key:value, OK, ERR no-such-param, ...), the same 63-character line limit, and the
same CSV output with an optional seconds-since-boot prefix (!timestamp:1).
It always emits CSV, whatever !format says.

The demo device has six streams, picked to exercise the dashboard:
  1 mot     pos,set,cmd,err,vel   a position servo — change mot.set / mot.kp / mot.pwm_lim
  2 env     3 fields whose units string repeats ("V,V,degC") -> generic labels
  3 wave    s0..s7                 eight phase-shifted sine waves (like an 8-sensor array)
  4 piezo   A0..A3                 baseline + decaying spikes (tests peak-preserving drawing)
  5 tagged  sid,A0,A1              first field is a constant stream id (hidden by default)
  6 frame   id,off,cnt + 48 samples   a 51-field capture chunk, like the LVDT / synchro frames
"""
import argparse
import math
import os
import pty
import random
import select
import time
import tty

LINE_MAX = 63          # UNIPROTO_CMD_BUF - 1: longer lines overflow and the tail is parsed on its own


class Stream:
    def __init__(self, sid, name, schema, units, emit):
        self.id, self.name, self.schema, self.units, self.emit = sid, name, schema, units, emit


class SimDevice:
    def __init__(self, name="SimLab", drop_first_caps=False):
        self.name = name
        self.drop_first_caps = drop_first_caps
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)                     # no echo / CRLF translation on the "wire"
        os.set_blocking(self.master, False)
        self.path = os.ttyname(self.slave)
        self.t0 = time.monotonic()
        self.rate, self.fmt, self.timestamp = 20, "csv", False
        self.active = []                           # stream ids, in registration order
        self.buf = ""
        self._rand = random.Random(7)
        self._spike = [0.0] * 4
        self.closed = False
        self.readonly, self.text_params = set(), {"sim.label"}
        self._init_params()
        self._init_streams()

    # ── device model ──────────────────────────────────────────────────────────
    def _init_params(self):
        self.p = {"mot.enable": "1", "mot.kp": "2.0", "mot.set": "0.0", "mot.pwm_lim": "100",
                  "sim.gain": "1.0", "sim.label": "demo"}
        self.defaults = dict(self.p)
        self.pos = self.vel = 0.0
        self.cmd = 0.0

    def _init_streams(self):
        self.streams = [
            Stream(1, "mot", "i32,f32,i32,f32,f32", "pos,set,cmd,err,vel", self._emit_mot),
            Stream(2, "env", "f32,f32,f32", "V,V,degC", self._emit_env),
            Stream(3, "wave", "u16,u16,u16,u16,u16,u16,u16,u16", "s0,s1,s2,s3,s4,s5,s6,s7", self._emit_wave),
            Stream(4, "piezo", "u16,u16,u16,u16", "A0,A1,A2,A3", self._emit_piezo),
            Stream(5, "tagged", "u16,u16,u16", "sid,A0,A1", self._emit_tagged),
            Stream(6, "frame", "u16,u16,u16,...", "id,off,cnt,s0..sN", self._emit_frame),
        ]
        self._frame_id = 0
        self.actions = {"mot.zero": self._act_zero, "sim.reset": self._act_reset, "sim.fail": lambda: False}

    def _now(self):
        return time.monotonic() - self.t0

    def step(self, dt):
        enable = self.p["mot.enable"] != "0"
        kp, lim, sp = float(self.p["mot.kp"]), float(self.p["mot.pwm_lim"]), float(self.p["mot.set"])
        err = sp - self.pos
        self.cmd = max(-lim, min(lim, kp * err)) if enable else 0.0
        acc = 30.0 * self.cmd - 6.0 * self.vel
        self.vel += acc * dt
        self.pos += self.vel * dt

    def _emit_mot(self):
        sp = float(self.p["mot.set"])
        return [str(int(round(self.pos))), f"{sp:.1f}", str(int(round(self.cmd))),
                f"{sp - self.pos:.1f}", f"{self.vel + self._rand.gauss(0, 1.5):.1f}"]

    def _emit_env(self):
        t, g = self._now(), float(self.p["sim.gain"])
        return [f"{g * 2.5 * math.sin(t * 1.3):.3f}", f"{g * 1.8 * math.sin(t * 0.7 + 1):.3f}",
                f"{21.5 + 0.4 * math.sin(t * 0.2) + self._rand.gauss(0, 0.03):.3f}"]

    def _emit_wave(self):
        t = self._now()
        return [str(int(512 + 400 * math.sin(2 * math.pi * 0.5 * t + k * math.pi / 4) + self._rand.gauss(0, 6)))
                for k in range(8)]

    def _emit_piezo(self):
        out = []
        for k in range(4):
            if self._rand.random() < 0.004 * (k + 1):
                self._spike[k] = self._rand.uniform(250, 480) * self._rand.choice((-1, 1))
            self._spike[k] *= 0.82
            out.append(str(int(512 + self._spike[k] + self._rand.gauss(0, 3))))
        return out

    def _emit_tagged(self):
        t = self._now()
        return ["5", str(int(300 + 200 * math.sin(t))), str(int(700 + 150 * math.cos(1.7 * t)))]

    def _emit_frame(self):
        """An LVDT/synchro-style capture chunk: id, off, cnt, then 48 samples of one sine cycle."""
        self._frame_id += 1
        ph = self._now() * 6.0
        return ["%d" % (self._frame_id % 65535), "0", "48"] + \
               [str(int(127 + 110 * math.sin(2 * math.pi * k / 48 + ph))) for k in range(48)]

    def _act_zero(self):
        self.pos = self.vel = 0.0
        self.p["mot.set"] = "0.0"
        self._write("mot.zero")
        return True

    def _act_reset(self):
        self.p = dict(self.defaults)
        return True

    # ── protocol: a port of UniProto::handleLine ──────────────────────────────
    def _write(self, text):
        data = (text + "\n").encode()
        try:
            os.write(self.master, data)
        except BlockingIOError:
            pass                                    # host not reading: drop, like a full UART buffer
        except OSError:
            self.closed = True

    def get_param(self, key):
        return self.p[key]

    def set_param(self, key, value):
        """True if accepted. Numbers only, except the text parameters; read-only ones refuse."""
        if key in self.readonly:
            return False
        if key not in self.text_params:
            try:
                float(value)
            except ValueError:
                return False
        self.p[key] = value
        return True

    def set_rate(self, n):
        self.rate = max(1, min(500, n))

    @staticmethod
    def parse_int(s):
        s = s.strip()
        try:
            return int(float(s))
        except ValueError:
            return 0

    def handle_line(self, line):
        line = line.strip()
        if not line:
            return
        if line == "?":
            if self.drop_first_caps:
                self.drop_first_caps = False        # simulate a board that is still booting
                return
            return self._caps()
        if line[0] == "?":
            key = line[1:]
            if key == "rate":
                return self._write(f"rate:{self.rate}")
            if key == "timestamp":
                return self._write(f"timestamp:{1 if self.timestamp else 0}")
            if key == "format":
                return self._write(f"format:{self.fmt}")
            if key == "stream":
                return self._write("stream:" + (",".join(str(i) for i in self.active) if self.active else "0"))
            if key in self.p:
                return self._write(f"{key}:{self.get_param(key)}")
            return self._write("ERR no-such-param")
        if line[0] == "!":
            body = line[1:]
            if not body:
                return self._write("ERR set-missing-key")
            if ":" not in body:
                return self._write("ERR set-missing-colon")
            key, value = body.split(":", 1)
            if not key:
                return self._write("ERR set-missing-key")
            if key == "rate":
                self.set_rate(self.parse_int(value))
                return self._write("OK")
            if key == "timestamp":
                self.timestamp = self.parse_int(value) != 0
                return self._write("OK")
            if key == "format":
                if value not in ("csv", "txt", "ap", "bin"):
                    return self._write("ERR bad-format")
                self.fmt = value
                return self._write("OK")
            if key == "stream":
                if value == "":
                    return self._write("ERR set-missing-value")
                ids = [s.id for s in self.streams]
                if value[0] == "+":
                    n = self.parse_int(value[1:])
                    if n in ids and n not in self.active:
                        self.active = [i for i in ids if i in self.active or i == n]
                elif value[0] == "-":
                    n = self.parse_int(value[1:])
                    self.active = [i for i in self.active if i != n]
                else:
                    n = self.parse_int(value)
                    self.active = [] if n == 0 else ([n] if n in ids else [])
                return self._write("OK")
            if key in self.p:
                return self._write("OK" if self.set_param(key, value) else "ERR set-failed")
            return self._write("ERR no-such-param")
        if line[0] == "@":
            body = line[1:]
            if not body:
                return self._write("ERR no-such-action")
            name = body.split(":", 1)[0]
            fn = self.actions.get(name)
            if fn is None:
                return self._write("ERR no-such-action")
            return self._write("OK" if fn() else "ERR action-failed")
        self._write("ERR unknown-cmd")

    def _caps(self):
        streams = ",".join(f'{{"id":{s.id},"name":"{s.name}","schema":"{s.schema}","units":"{s.units}"}}'
                           for s in self.streams)
        params = ",".join([f'"{k}"' for k in self.p] + ['"rate"', '"format"', '"timestamp"', '"stream"'])
        actions = ",".join(f'"{a}"' for a in self.actions)
        self._write(f'{{"device":"{self.name}","streams":[{streams}],"params":[{params}],'
                    f'"actions":[{actions}],"cmds":["?","?key","!key:value","@action[:args]"]}}')

    def feed(self, data):
        """Bytes from the host, with the library's 64-byte line buffer behaviour."""
        for ch in data.decode("utf-8", "replace"):
            if ch == "\r":
                continue
            if ch == "\n":
                if self.buf:
                    self.handle_line(self.buf)
                self.buf = ""
                continue
            if len(self.buf) < LINE_MAX:
                self.buf += ch
            else:
                self.buf = ""                       # overflow: discard the front, keep parsing the rest

    # ── main loop ─────────────────────────────────────────────────────────────
    def emit_tick(self):
        prefix = f"{self._now():.3f}," if self.timestamp else ""
        for s in self.streams:
            if s.id in self.active:
                self._write(prefix + ",".join(s.emit()))

    def run(self, stop=lambda: False):
        last = time.monotonic()
        next_tick = last
        while not stop() and not self.closed:
            now = time.monotonic()
            self.step(min(now - last, 0.1))
            last = now
            r, _, _ = select.select([self.master], [], [], 0.002)
            if r:
                try:
                    data = os.read(self.master, 4096)
                    if data:
                        self.feed(data)
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    self.closed = True
            if now >= next_tick:
                next_tick += 1.0 / self.rate
                if next_tick < now:
                    next_tick = now + 1.0 / self.rate
                self.emit_tick()

    def close(self):
        self.closed = True
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass


class DCMotorSim(SimDevice):
    """Looks like src/dc_motor: stream pos,set,cmd,err,vel,mA; position / velocity PID; mot.* parameters."""

    def __init__(self, name="DCMotor", drop_first_caps=False):
        super().__init__(name, drop_first_caps)
        self.readonly = {"mot.pos", "mot.vel"}
        self.text_params = set()

    def _init_params(self):
        self.p = {"mot.enable": "1", "mot.mode": "1", "mot.kp": "2.0", "mot.ki": "0.0", "mot.kd": "0.0",
                  "mot.pwm_lim": "100", "mot.set": "0.0", "mot.pot_scale": "12000", "mot.vel_scale": "20000",
                  "mot.pos": "0", "mot.vel": "0", "mot.ctrl_hz": "500", "mot.vel_alpha": "0.5"}
        self.defaults = dict(self.p)
        self.pos = self.vel = self.cmd = self.integ = self.prev_err = self.mA = 0.0
        self.coast = False

    def _init_streams(self):
        self.streams = [Stream(1, "mot", "i32,f32,i32,f32,f32,f32", "pos,set,cmd,err,vel,mA", self._emit_mot)]
        self.actions = {"mot.zero": self._act_zero, "mot.brake": self._act_brake, "mot.coast": self._act_coast}

    def get_param(self, key):
        if key == "mot.pos":
            return str(int(round(self.pos)))
        if key == "mot.vel":
            return f"{self.vel:.1f}"
        return self.p[key]

    def step(self, dt):
        P = {k: float(v) for k, v in self.p.items() if k not in ("mot.pos", "mot.vel")}
        lim, sp = P["mot.pwm_lim"], P["mot.set"]
        if P["mot.enable"] == 0:
            self.cmd = 0.0
        elif P["mot.mode"] == 0:
            self.cmd = max(-lim, min(lim, sp))
        else:
            err = (sp - self.pos) if P["mot.mode"] == 1 else (sp - self.vel)
            self.integ = max(-lim, min(lim, self.integ + P["mot.ki"] * err * dt))
            d = (err - self.prev_err) / dt if dt > 0 else 0.0
            self.prev_err = err
            self.cmd = max(-lim, min(lim, P["mot.kp"] * err + self.integ + P["mot.kd"] * d))
        damping = 60.0 if self.coast is False and P["mot.enable"] == 0 else 6.0
        self.vel += (30.0 * self.cmd - damping * self.vel) * dt
        self.pos += self.vel * dt
        self.mA = abs(self.cmd) * 3.2 + abs(self.vel) * 0.02

    def _emit_mot(self):
        sp = float(self.p["mot.set"])
        err = sp - self.pos if float(self.p["mot.mode"]) == 1 else sp - self.vel
        return [str(int(round(self.pos))), f"{sp:.1f}", str(int(round(self.cmd))), f"{err:.1f}",
                f"{self.vel + self._rand.gauss(0, 1.5):.1f}", f"{self.mA + self._rand.gauss(0, 4):.1f}"]

    def _act_zero(self):
        self.pos = self.vel = self.integ = 0.0
        self.p["mot.set"] = "0.0"
        return True

    def _act_brake(self):
        self.p["mot.enable"], self.p["mot.set"], self.vel = "0", "0.0", 0.0
        return True

    def _act_coast(self):
        self.p["mot.enable"], self.coast = "0", True
        return True


class QTR8Sim(SimDevice):
    """Looks like src/qtr8: raw decay times, thresholded bits, line position and gray code."""

    def __init__(self, name="QTR8", drop_first_caps=False):
        super().__init__(name, drop_first_caps)
        self.rate = 20

    def step(self, dt):
        pass                                  # no dynamics: the signals are computed from the clock

    def _init_params(self):
        self.p = {"qtr.thr": "1000", "qtr.timeout": "2500"}
        self.defaults = dict(self.p)

    def _init_streams(self):
        self.streams = [
            Stream(1, "raw", "u16,u16,u16,u16,u16,u16,u16,u16", "s0,s1,s2,s3,s4,s5,s6,s7", lambda: [str(v) for v in self._raw()]),
            Stream(2, "bin", "u8,u8,u8,u8,u8,u8,u8,u8", "b0,b1,b2,b3,b4,b5,b6,b7", lambda: [str(b) for b in self._bits()]),
            Stream(3, "line", "u16", "pos", lambda: [str(int(self._line()))]),
            Stream(4, "gray", "u16", "gray", lambda: [str(self._gray())]),
        ]
        self.actions = {"qtr.cal": self._act_cal}

    def _raw(self):
        t, to = self._now(), float(self.p["qtr.timeout"])
        x = 3.5 + 3.2 * math.sin(0.5 * t)                      # a dark line moving under the sensor
        return [int(max(0, min(to, 120 + (to - 120) * math.exp(-((i - x) ** 2) / 1.6) + self._rand.gauss(0, 25)))) for i in range(8)]

    def _bits(self):
        thr = float(self.p["qtr.thr"])
        return [1 if v > thr else 0 for v in self._raw()]

    def _line(self):
        raw = self._raw()
        tot = sum(raw) or 1
        return sum(i * v for i, v in enumerate(raw)) / tot * 255.0 / 7.0

    def _gray(self):
        b = int("".join(str(x) for x in self._bits()), 2)
        return b ^ (b >> 1)

    def _act_cal(self):
        self.p["qtr.thr"] = "1150"
        return True


class SensorShieldSim(SimDevice):
    """Looks like src/sensor_shield: 7 streams that each start with their own id (sid); no parameters, no actions."""

    def __init__(self, name="SensorShield", drop_first_caps=False, angle=True):
        self.angle = angle                     # the stream 8 'angle' (pot counts + Hall degrees) exists in the newer sketch
        super().__init__(name, drop_first_caps)
        self.foil = 0.0

    def _init_params(self):
        self.p = {}
        self.defaults = {}

    def _init_streams(self):
        self.streams = [
            Stream(1, "analog", "u16,u16,u16,u16,u16,u16,u16", "sid,A0,A1,A2,A3,A4,A5", self._emit_analog),
            Stream(2, "force", "u16,f32,f32", "sid,foil_g,strain_g", self._emit_force),
            Stream(3, "hall", "u16,f32", "sid,deg", self._emit_hall),
            Stream(4, "encoder", "u16,i32,f32", "sid,pos,vel", self._emit_encoder),
            Stream(5, "cap", "u16,f32,f32,f32", "sid,A,B,pos_mm", self._emit_cap),
            Stream(6, "rc", "u16,u16,f32", "sid,count,ref_v", self._emit_rc),
            Stream(7, "us", "u16,f32", "sid,cm", self._emit_us),
        ]
        if self.angle:
            self.streams.append(Stream(8, "angle", "u16,u16,f32", "sid,pot,hall_deg", self._emit_angle))
        self.actions = {}

    def _load(self):                           # a load slowly pressed and released (grams)
        return 400.0 * (0.5 - 0.5 * math.cos(0.8 * self._now()))

    def step(self, dt):                        # the foil sensor lags the true load: a hysteresis loop in an XY plot
        self.foil += (0.9 * self._load() + 20.0 - self.foil) * min(1.0, dt * 2.5)

    def _emit_analog(self):
        t = self._now()
        pot = (130 + 110 * math.sin(0.5 * t)) / 0.4                  # A0: the pot, on the same shaft as the Hall sensor
        vals = [pot, 340 + 40 * math.sin(2 * t), 200 + 0.5 * self.foil,
                330 + 0.4 * self._load(), 338 + 160 * math.sin(0.5 * t), 338 + 160 * math.cos(0.5 * t)]
        return ["1"] + [str(int(max(0, min(675, v + self._rand.gauss(0, 2))))) for v in vals]

    def _emit_force(self):
        return ["2", f"{self.foil + self._rand.gauss(0, 2):.1f}", f"{self._load() + self._rand.gauss(0, 1.5):.1f}"]

    def _emit_hall(self):
        return ["3", f"{150 + 110 * math.sin(0.5 * self._now()):.2f}"]

    def _emit_encoder(self):
        t = self._now()
        return ["4", str(int(1200 * math.sin(0.5 * t))), f"{600 * math.cos(0.5 * t):.1f}"]

    def _emit_cap(self):
        t = self._now()
        return ["5", f"{50 + 40 * math.sin(1.1 * t):.1f}", f"{50 - 40 * math.sin(1.1 * t):.1f}", f"{20 + 15 * math.sin(1.1 * t):.1f}"]

    def _emit_rc(self):
        return ["6", str(int(500 + 300 * math.sin(2 * self._now()))), f"{3.3 + self._rand.gauss(0, 0.004):.3f}"]

    def _emit_us(self):
        return ["7", f"{80 + 60 * math.sin(0.3 * self._now()):.1f}"]

    def _emit_angle(self):                     # pot on the same shaft as the Hall sensor: 0.4 deg per count, 20 deg offset
        hall = 150 + 110 * math.sin(0.5 * self._now())
        return ["8", str(int(max(0, min(675, (hall - 20) / 0.4 + self._rand.gauss(0, 3))))), f"{hall:.2f}"]


class SensorShieldSimOld(SensorShieldSim):
    """The sketch before the 'angle' stream existed (7 streams): to check that configs still work on older firmware."""

    def __init__(self, name="SensorShield", drop_first_caps=False):
        super().__init__(name, drop_first_caps, angle=False)


BOARDS = {"simlab": SimDevice, "dc_motor": DCMotorSim, "qtr8": QTR8Sim, "sensor_shield": SensorShieldSim,
          "sensor_shield_old": SensorShieldSimOld}


def main():
    ap = argparse.ArgumentParser(description="simulated UniProto device on a pseudo-terminal")
    ap.add_argument("--board", choices=sorted(BOARDS), default="simlab",
                    help="what to pretend to be: simlab (demo, default), or dc_motor / qtr8 / sensor_shield[_old] (same streams and parameters as the real sketches)")
    ap.add_argument("--name", default=None, help="device name reported by '?' (default depends on --board)")
    ap.add_argument("--drop-first-caps", action="store_true",
                    help="ignore the first '?' (simulates a board that is still booting)")
    args = ap.parse_args()
    cls = BOARDS[args.board]
    sim = cls(args.name, args.drop_first_caps) if args.name else cls(drop_first_caps=args.drop_first_caps)
    print(f"Simulated UniProto device '{sim.name}' is listening on {sim.path}")
    print(f"Try it:   python dashboard/dashboard.py --port {sim.path}")
    print("(Ctrl-C to stop)", flush=True)
    try:
        sim.run()
    except KeyboardInterrupt:
        pass
    finally:
        sim.close()


if __name__ == "__main__":
    main()