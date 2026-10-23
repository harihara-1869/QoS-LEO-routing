import glfw
from OpenGL.GL import *
from OpenGL.GLU import *
import numpy as np
import csv
import time
import math
from skyfield.api import load, EarthSatellite, wgs84
from datetime import timedelta
from collections import defaultdict
import igraph as ig
from logic_module import LogicalTopology, LinkType, GROUND_STATIONS, SCALE
CSV_FILENAME = 'customconstellation.csv'
MAX_SATS = 100
TIME_MULTIPLIER = 100.0

# ==========================================================
# VISUAL SIMULATION
# ==========================================================
class SatelliteSim:
    def __init__(self, sats):
        self.ts = load.timescale()
        self.start_real = time.time()
        self.start_sim = self.ts.now()

        self.time_multiplier = TIME_MULTIPLIER
        self.topology = LogicalTopology(sats[:MAX_SATS])

        self.distance = 3.0
        self.rx = 0
        self.ry = 0
        self.last_x = 0
        self.last_y = 0
        self.drag = False

    def sim_time(self):
        dt = (time.time() - self.start_real) * self.time_multiplier
        return self.ts.from_datetime(
            self.start_sim.utc_datetime() + timedelta(seconds=dt)
        )

    def draw_earth(self):
        glColor3f(0.2, 0.5, 1.0)
        q = gluNewQuadric()
        gluQuadricDrawStyle(q, GLU_LINE)
        gluSphere(q, 1, 32, 32)

    def draw_satellites(self, pos):
        glPointSize(4)
        glBegin(GL_POINTS)
        glColor3f(1, 1, 1)
        for p in pos.values():
            p = p * SCALE
            glVertex3f(p[0], p[2], p[1])
        glEnd()

    def draw_links(self, links, color):
        glColor3f(*color)
        glBegin(GL_LINES)
        for a, b in links:
            pa = a.sat.at(self.t).position.km * SCALE
            pb = b.sat.at(self.t).position.km * SCALE
            glVertex3f(pa[0], pa[2], pa[1])
            glVertex3f(pb[0], pb[2], pb[1])
        glEnd()

    def draw_ground_links(self, udl_links, color):
        glColor3f(*color)
        glBegin(GL_LINES)
        gs_dict = {name: wgs84.latlon(lat, lon, elevation_m=h) 
                for name, lat, lon, h in GROUND_STATIONS}
        for sat_node, gs_name in udl_links:
            pa = sat_node.sat.at(self.t).position.km * SCALE
            gs_pos = gs_dict[gs_name].at(self.t).position.km * SCALE
            glVertex3f(pa[0], pa[2], pa[1])
            glVertex3f(gs_pos[0], gs_pos[2], gs_pos[1])
        glEnd()
    def draw_active_route(self, path, color=(1.0, 1.0, 0.0), width=3.0):
        
        if not path or len(path) < 2:
                return

        glLineWidth(width)
        glColor3f(*color)
        
        # Use GL_LINE_STRIP to draw a continuous line through the path
        glBegin(GL_LINE_STRIP)
        for name in path:
            # Map the igraph ID back to your satellite object
            sat_node = next((n for n in self.topology.nodes if n.sat.name == name), None)
            if sat_node is None:
                p = self.topology.get_gs_position(name, self.t) * SCALE
            else:
                p = sat_node.sat.at(self.t).position.km * SCALE
            # Consistent coordinate mapping (X, Z, Y)
            glVertex3f(p[0], p[2], p[1])
        glEnd()
        
        # Reset line width so other links don't become thick
        glLineWidth(1.0)

    def draw_ground(self):
        glPointSize(8)
        glBegin(GL_POINTS)
        glColor3f(1, 1, 0)
        glVertex3f(0, 0, 0)
        glEnd()
    

    # ---------------- INPUT HANDLING ----------------
    def scroll(self, win, xoff, yoff):
        self.distance = max(1.2, self.distance - yoff * 0.2)

    def mouse_btn(self, win, button, action, mods):
        if button == glfw.MOUSE_BUTTON_LEFT:
            self.drag = action == glfw.PRESS

    def mouse_move(self, win, x, y):
        if self.drag:
            self.ry += (x - self.last_x) * 0.4
            self.rx += (y - self.last_y) * 0.4
        self.last_x, self.last_y = x, y

    def key(self, win, key, sc, action, mods):
        if action in (glfw.PRESS, glfw.REPEAT):
            if key == glfw.KEY_UP:
                self.start_sim = self.sim_time()
                self.start_real = time.time()
                self.time_multiplier *= 2
                print("Speed:", self.time_multiplier)
            elif key == glfw.KEY_DOWN:
                self.start_sim = self.sim_time()
                self.start_real = time.time()
                self.time_multiplier /= 2
                print("Speed:", self.time_multiplier)

    # ---------------- MAIN LOOP ----------------
    def run(self):
        if not glfw.init():
            raise RuntimeError("GLFW initialization failed; use run_scenario.py for headless runs")
        win = glfw.create_window(1200, 800, "Earth-Safe Logical Topology", None, None)
        if not win:
            glfw.terminate()
            raise RuntimeError("OpenGL window creation failed")
        glfw.make_context_current(win)
        glEnable(GL_DEPTH_TEST)

        glfw.set_scroll_callback(win, self.scroll)
        glfw.set_mouse_button_callback(win, self.mouse_btn)
        glfw.set_cursor_pos_callback(win, self.mouse_move)
        glfw.set_key_callback(win, self.key)

        while not glfw.window_should_close(win):
            self.t = self.sim_time()
            pos, links, _, _ = self.topology.compute(self.t)
            isl1, isl2, iol, udl = ([ (a, b) for kind, a, b in links if kind == selected ]
                                    for selected in LinkType)
            gs_positions = {
                    name: wgs84.latlon(lat, lon, elevation_m=h).at(self.t).position.km
                    for name, lat, lon, h in GROUND_STATIONS
                }
            g = self.topology.construct_unified_graph(pos, gs_positions)
            path = LogicalTopology.get_path(g, "GS_INDIA", "GS_AUSTRALIA")  # Example satellite name
            print("path:", path)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glLoadIdentity()
            gluPerspective(45, 1.5, 0.1, 100)

            glTranslatef(0, 0, -self.distance)
            glRotatef(self.rx, 1, 0, 0)
            glRotatef(self.ry, 0, 1, 0)

            self.draw_earth()
            self.draw_ground()
            self.draw_satellites(pos)

            self.draw_links(isl1, (1, 0, 0))       # Red
            self.draw_links(isl2, (1, 0.5, 0))     # Orange
            self.draw_links(iol, (0.7, 0, 1))      # Purple
            self.draw_ground_links(udl, (0, 1, 0)) # Green
            self.draw_active_route(path, color=(1.0, 1.0, 0.0), width=4.0)  # Yellow

            glfw.swap_buffers(win)
            glfw.poll_events()

        glfw.terminate()

# ==========================================================
# CSV PARSER
# ==========================================================
def parse_csv(filename):
    ts = load.timescale()
    sats = []
    with open(filename) as f:
        for r in csv.DictReader(f):
            sats.append(EarthSatellite.from_omm(ts, r))
    return sats

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    SatelliteSim(parse_csv(CSV_FILENAME)).run()
