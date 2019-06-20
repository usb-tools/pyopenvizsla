"""
Core helper functions and definitions for OpenVizsla.
"""

import enum


class OVCaptureUSBSpeed(enum.IntEnum):
    """ Enumeration representing USB speeds.  """

    # The possible USB speeds capture by OV, encoded to match the values 
    # in the ULPI FUNC_CTRL register.
    HIGH  = 0
    FULL  = 1
    LOW   = 2

    def is_high_speed(self):
        return (self is self.HIGH)



def openvizsla_assets_directory():
    """ Provide a quick function that helps us get at our assets directory. """
    import os
 
    # Find the path to the module, and then find its assets folder.
    module_path = os.path.dirname(__file__)
    return os.path.join(module_path, 'assets')
 
 
def find_openvizsla_asset(filename):
    """ Returns the path to a given GreatFET asset, if it exists, or None if the GreatFET asset isn't provided."""
    import os
 
    asset_path = os.path.join(openvizsla_assets_directory(), filename)
 
    if os.path.isfile(asset_path):
        return asset_path
    else:
        return None


# Allow OpenVizsla devices to be refernced as if they were in this module directly.
from .device import OVDevice

# And allow the definition of a USBEventSink to be referenced as though it were in this namespace.
from .sniffer import USBEventSink
