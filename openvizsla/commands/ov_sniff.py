"""
New sniffer frontend for OpenVizsla.
"""

from .. import find_openvizsla_asset

from ..libov import OVDevice 
from ..firmware import OVFirmwarePackage

import argparse

def main():
    """ Core demonstration sniffer for OpenVizsla. """

    default_package = find_openvizsla_asset("ov3.fwpkg")

    parser = argparse.ArgumentParser()
    parser.add_argument("--firmware_package", "-p", type=OVFirmwarePackage, default=default_package)
    parser.add_argument("-l", "--load", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--config-only", "-C", action="store_true")
    parser.parse_args()

    dev = OVDevice(mapfile=args.pkg.open('map.txt', 'r'), verbose=args.verbose)
    err = dev.open(bitstream=args.pkg.open('ov3.bit', 'r') if args.load else None)
