#!/usr/bin/env python3
"""
uniproto_sim.py — a simulated UniProto Arduino, for trying the dashboard without hardware.

  python dashboard/uniproto_sim.py
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
                return self._write(f"{key}:{self.p[key]}")
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
                try:
                    if key != "sim.label":
                        float(value)
                except ValueError:
                    return self._write("ERR set-failed")
                self.p[key] = value
                return self._write("OK")
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
        params = ",".join(f'"{k}"' for k in self.p) + ',"rate","format","timestamp","stream"'
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


def main():
    ap = argparse.ArgumentParser(description="simulated UniProto device on a pseudo-terminal")
    ap.add_argument("--name", default="SimLab")
    ap.add_argument("--drop-first-caps", action="store_true",
                    help="ignore the first '?' (simulates a board that is still booting)")
    args = ap.parse_args()
    sim = SimDevice(args.name, args.drop_first_caps)
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
