"""
FTDI interfacing objects for OpenVizsla
"""

import ctypes

from .libov import FTDI_Device, FTDIDevice_Open, FTDIDevice_Close, FTDIDevice_Write, FTDIDevice_ReadStream
from .libov import FTDIEEP_CheckAndProgram, FTDIEEP_Erase, FTDIEEP_SanityCheck
from .libov import p_cb_StreamCallback

# HACK from original openvizsla software
# replace me with a lifetime tracker in the FTDIDevice
keeper = []

class FTDIDevice:
    """ Class representing an OpenVizsla FTDI device connection. """

    # Constants for our two FTDI interfaces.
    INTERFACE_A = 1
    INTERFACE_B = 2

    def __init__(self):
        self.__is_open = False
        self._dev = FTDI_Device()

    def __del__(self):
        self.close()

    def open(self):
        err = FTDIDevice_Open(self._dev)
        if not err:
            self.__is_open = True

        return err

    def close(self):
        if self.__is_open:
            self.__is_open = False
            FTDIDevice_Close(self._dev)

    def write(self, intf, buf, async_=False):
        if not isinstance(buf, bytes):
            raise TypeError("buf must be bytes")

        return FTDIDevice_Write(self._dev, intf, buf, len(buf), async_)

    def read(self, intf, n):
        buf = []

        def callback(b, prog):
            buf.extend(b)
            return int(len(buf) >= n)

        self.read_async(intf, callback, 4, 4)

        return buf


    def read_async(self, intf, callback, packetsPerTransfer, numTransfers):

        def callback_wrapper(buf, ll, prog, user):
            if ll:
                b = ctypes.string_at(buf, ll)
            else:
                b = b''
            return callback(b, prog)

        cb = p_cb_StreamCallback(callback_wrapper)

        # HACK
        keeper.append(cb)

        return FTDIDevice_ReadStream(self._dev, intf, cb, 
                None, packetsPerTransfer, numTransfers)
        # uncomment next lines to use C code to parse packets
        #return FTDIDevice_ReadStream(self._dev, intf, p_cb_StreamCallback(libov.CStreamCallback), 
        #        cb, packetsPerTransfer, numTransfers)

    def eeprom_erase(self):
        return FTDIEEP_Erase(self._dev)

    def eeprom_program(self, serialno):
        return FTDIEEP_CheckAndProgram(self._dev, serialno)

    def eeprom_sanitycheck(self, verbose=False):
        return FTDIEEP_SanityCheck(self._dev, verbose)
