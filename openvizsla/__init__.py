"""
Core helper functions for OpenVizsla.
"""


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


class ProtocolError(IOError):
    pass
