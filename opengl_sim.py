"""Legacy entry point; rendering and topology are now shared with test.py."""
from test import SatelliteSim, parse_csv

if __name__ == '__main__':
    SatelliteSim(parse_csv('starlink.csv')).run()
