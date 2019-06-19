"""
Functionality for working with OpenVizsla firmware packages.
"""

import re
import zipfile

class OVFirmwarePackage:
    """ Class that aides in extracting the various pieces of a OV firmware archive. """

    REGISTER_MAP_FILENAME = 'map.txt'
    BITSTREAM_FILENAME = 'ov3.bit'

    def __init__(self, package_filename):
        """ Set up our firmware package representation. """

        # Open the firmware package.
        self.archive = zipfile.ZipFile(package_filename, 'r')


    def get_bitstream_file(self):
        """ Returns a File object that can be used to access the relevant bitstream. """
        return self.archive.open(self.BITSTREAM_FILENAME, 'r')


    def get_bitstream(self):
        """ Returns the raw binary contents of the given bitstream. """
        with self.archive.open(self.BITSTREAM_FILENAME, 'r') as bitfile:
            return bitfile.read()


    def get_register_map(self):
        """ Returns a dictionary represneting the register map stored in the firmware package. """

        register_map = {}

        # Our firmware package contains a text file that describes our memory map.
        # Open it for parsing.
        with self.archive.open(self.REGISTER_MAP_FILENAME, 'r') as mapfile:

            for line in mapfile.readlines():
                line = line.strip().decode('utf-8')

                line = re.sub('#.*', '', line)
                if not line:
                    continue

                m = re.match('\s*(\w+)\s*=\s*(\w+)(:\w+)?\s*', line)
                if not m:
                    raise ValueError("Mapfile - could not parse %s" % line)

                name  = m.group(1)
                value = int(m.group(2), 16)

                if m.group(3) is None:
                    size = 1
                else:
                    size = int(m.group(3)[1:], 16) + 1 - value
                    assert size > 1

                register_map[name] = value, size

        return register_map

